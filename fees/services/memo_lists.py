"""Memo listing services for the Fee Register (T3.1, R-MEMO-7, brief 5.4 to 5.6).

Ports the list / filter / per-matter / drafts / recent-matters parts of
``memoService.ts`` (``listMemos``, ``listDrafts``, ``listMemosForMatter``,
``listRecentMatters`` and the shared ``listMemosInternal``) to the Django ORM,
and adds the two read-service helpers the web Memos page needs that the desktop
renderer computed client-side: pagination (``page`` / ``page_size``) and the
aggregated FOOTER TOTALS (the column sums shown under the table in the original
``MemosPage.tsx``).

Reuse, do NOT re-derive (R-MEMO-1, D3): every row's fees come from the stored
``total_fees`` via ``memo_fees.resolve_memo_fees`` / ``effective_total_fees`` and
the paid-driven values from ``memo_fees.status_and_due``; the stored
``amount_paid`` (gross), ``amount_received`` (net) and ``amount_tds`` columns are
read directly (payments.py keeps them in step, R-DATA-4). Nothing here
multiplies a count by its per-unit rate (the per-appearance and per-conference
products stay in memo_fees.py), so the T2.2 grep guard holds.

Scoping (design section 11): every query is filtered by ``profile`` exactly like
the sibling services. These are pure READS: they never bump ``data_version``.

Draft handling mirrors the original ``draftMode``:

* ``"exclude_drafts"`` (the main Memos page): only finalised, numbered memos;
* ``"drafts_only"`` (the Draft Memos page): only drafts;
* ``"all"`` (the Matter page): both.

Query-count discipline: the list is ONE query (the stored totals and paid
columns live on the memo row, so no per-row subquery is needed), plus ONE query
to read the settings used for net-of-TDS and the overdue flag. ``select_related``
on firm and matter means reading their names adds no per-row query. The footer
totals reuse the same in-memory rows, so they add no query of their own. The
tests assert these bounds with ``assertNumQueries``.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.db import connection
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Max, Sum, Value
from django.db.models.functions import Coalesce, Round

from fees.models import FeesSettings, Memo
from fees.services import client_scope
from fees.services import memo_fees
from fees.services.money import round2

logger = logging.getLogger(__name__)

__all__ = [
    "list_memos",
    "list_page",
    "list_drafts",
    "list_memos_for_matter",
    "list_recent_matters",
    "footer_totals",
    "paginate",
    "page_size_for",
    "FOOTER_FIELDS",
]

#: The most rows one page may hold, whatever the Items per page setting says.
MAX_PAGE_SIZE = 1000

#: Valid draft-handling modes (mirror the original ``draftMode``).
_DRAFT_MODES = ("exclude_drafts", "drafts_only", "all")

#: The numeric list-item fields the footer sums (matches the desktop MemosPage
#: footer: Total, Net of TDS, Paid (= amount received, net), TDS, Due).
FOOTER_FIELDS = (
    "total_fees",
    "net_of_tds",
    "amount_received",
    "amount_tds",
    "amount_due",
)


def _settings_for(profile):
    """Reads ``default_tds_rate``, ``overdue_days`` and ``written_off_enabled`` for ``profile`` in ONE query.

    Returns ``(default_tds_rate, overdue_days, written_off_on)``: the numbers fall
    back to 0 and the switch to True when the profile has no settings row yet. This is a read, so it
    does NOT get-or-create the row (unlike the mutating services' ``touch``).
    """
    row = (
        FeesSettings.objects.filter(profile=profile)
        .values("default_tds_rate", "overdue_days", "written_off_enabled")
        .first()
    ) or {}
    return (row.get("default_tds_rate") or 0, row.get("overdue_days") or 0, row.get("written_off_enabled", True))


def _row_to_item(memo, default_tds_rate, overdue_days, written_off_on=True):
    """Builds one list-item dict from a ``Memo`` row (derived values via ``memo_fees``).

    ``total_fees`` is the stored total resolved through the single fee rule;
    ``amount_paid`` / ``amount_received`` / ``amount_tds`` are the stored columns;
    ``status`` and ``amount_due`` come from ``status_and_due`` (gross paid vs
    total); ``net_of_tds`` is at the settings default rate; ``is_overdue`` uses the
    settings ``overdue_days``. With Written off memos switched off, ``written_off`` is False on every row.
    """
    written_off = memo.written_off and written_off_on
    total_fees = memo_fees.effective_total_fees(memo)
    amount_paid = round2(memo.amount_paid)
    amount_received = round2(memo.amount_received)
    amount_tds = round2(memo.amount_tds)
    due = memo_fees.status_and_due(total_fees, amount_paid)
    net = memo_fees.net_of_tds(total_fees, default_tds_rate)
    overdue = memo_fees.compute_is_overdue(
        memo.date, due.status, written_off, overdue_days
    )
    return {
        "id": memo.pk,
        "memo_number": memo.memo_number if memo.memo_number is not None else "(draft)",
        "is_draft": memo.is_draft,
        "financial_year": memo.financial_year,
        "date": memo.date,
        "firm_id": memo.firm_id,
        "firm_name": memo.firm.name,
        "matter_id": memo.matter_id,
        "matter_name": memo.matter.name,
        "total_fees": total_fees,
        "num_appearances": memo.num_appearances,
        "num_conferences": memo.num_conferences,
        "num_drafts": memo.num_drafts or 0,
        "net_of_tds": net,
        "amount_paid": amount_paid,
        "amount_received": amount_received,
        "amount_tds": amount_tds,
        "amount_due": due.amount_due,
        "status": due.status,
        "written_off": written_off,
        "is_overdue": overdue,
    }


def _filtered_queryset(profile, filters, draft_mode, related=True, ordered=True):
    """The ordered, scoped ``Memo`` queryset for a listing (no evaluation yet).

    Applies the draft mode and the optional filters (financial year, firm,
    group / partner, matter or an explicit set of matter ids) and orders newest
    first: drafts last, then financial year DESC, then ``seq`` DESC, then id DESC.
    ``unpaid_only`` is NOT applied here; it is a post-filter in ``list_memos`` so
    the Paid / Unpaid status (derived from the stored paid amount) is honoured.
    """
    if draft_mode not in _DRAFT_MODES:
        raise ValueError(f"unknown draft_mode: {draft_mode!r}")

    qs = Memo.objects.filter(profile=profile)
    if related:
        qs = qs.select_related("firm", "matter")

    if draft_mode == "exclude_drafts":
        qs = qs.filter(is_draft=False)
    elif draft_mode == "drafts_only":
        qs = qs.filter(is_draft=True)

    filters = filters or {}

    financial_year = filters.get("financial_year")
    if financial_year:
        qs = qs.filter(financial_year=financial_year)

    firm_id = filters.get("firm_id")
    if firm_id is not None:
        qs = qs.filter(firm_id=firm_id)

    # The original UI calls this "partner"; the model is Group. A filter value of
    # "none" is reserved for a future "unassigned" meaning and is a no-op for now.
    group_id = filters.get("group_id", filters.get("partner_id"))
    if group_id == "none":
        pass
    elif group_id is not None:
        qs = qs.filter(group_id=group_id)

    qs = client_scope.narrow(qs, filters.get("client_id"), "matter__")

    selected = filters.get("selected_matter_ids")
    if selected:
        qs = qs.filter(matter_id__in=list(selected))
    else:
        matter_id = filters.get("matter_id")
        if matter_id is not None:
            qs = qs.filter(matter_id=matter_id)

    return qs.order_by("is_draft", "-financial_year", "-seq", "-id") if ordered else qs


def list_memos(profile, filters=None, draft_mode="exclude_drafts"):
    """Lists memos for ``profile`` as list-item dicts, newest first (R-MEMO-7).

    ``filters`` is an optional dict with any of ``financial_year``, ``firm_id``,
    ``group_id`` (alias ``partner_id``), ``client_id`` (an id, or ``client_scope.BLANK``), ``matter_id``, ``selected_matter_ids``
    and ``unpaid_only``. ``draft_mode`` is ``"exclude_drafts"`` (default, the main
    Memos page), ``"drafts_only"`` or ``"all"``.

    Two queries total: one to read the settings (net-of-TDS rate and overdue
    days) and one for the memo rows (``select_related`` on firm and matter so
    their names cost no extra query, and the stored totals and paid columns are
    on the row so there is no per-row subquery). ``unpaid_only`` is applied in
    Python after the status is derived, so no third query is needed.
    """
    filters = filters or {}
    default_tds_rate, overdue_days, written_off_on = _settings_for(profile)
    qs = _filtered_queryset(profile, filters, draft_mode)
    items = [_row_to_item(memo, default_tds_rate, overdue_days, written_off_on) for memo in qs]
    if filters.get("unpaid_only"):
        items = [item for item in items if item["status"] == "Unpaid"]
    return items


def iter_memos(profile, filters=None, draft_mode="exclude_drafts", chunk_size=500):
    """Like ``list_memos`` but yields the list-item dicts one at a time, newest first.

    Same filters, same order, same item dicts; rows are read with ``.iterator(chunk_size)`` so a large export
    never holds every ``Memo`` object at once (R-NFR-2). Two queries (settings, then the memo rows).
    """
    filters = filters or {}
    default_tds_rate, overdue_days, written_off_on = _settings_for(profile)
    qs = _filtered_queryset(profile, filters, draft_mode)
    unpaid_only = bool(filters.get("unpaid_only"))
    for memo in qs.iterator(chunk_size=chunk_size):
        item = _row_to_item(memo, default_tds_rate, overdue_days, written_off_on)
        if unpaid_only and item["status"] != "Unpaid":
            continue
        yield item


def list_drafts(profile, filters=None):
    """Lists only draft memos (the Draft Memos page). Convenience over ``list_memos``."""
    return list_memos(profile, filters, draft_mode="drafts_only")


def list_memos_for_matter(profile, matter_id, filters=None):
    """Lists both drafts and finalised memos for one matter (the Matter page).

    Merges ``matter_id`` into ``filters`` and lists with ``draft_mode="all"``.
    """
    merged = dict(filters or {})
    merged["matter_id"] = matter_id
    return list_memos(profile, merged, draft_mode="all")


def footer_totals(items):
    """Sums the footer columns across already-built list ``items`` (R-MEMO-7).

    Ports the desktop MemosPage footer: the column sums for Total, Net of TDS,
    Paid (= net ``amount_received``), TDS and Due, plus a ``count``. Takes the
    SAME dicts ``list_memos`` returns, so it adds no query and honours whatever
    filter (including ``unpaid_only``) produced the list. Each sum is a
    two-decimal ``Decimal``.
    """
    totals = {field: Decimal("0") for field in FOOTER_FIELDS}
    for item in items:
        for field in FOOTER_FIELDS:
            totals[field] += Decimal(str(item[field]))
    result = {field: round2(totals[field]) for field in FOOTER_FIELDS}
    result["count"] = len(items)
    return result


def _page_window(total, page, page_size):
    """``(meta, start, end)`` for ``total`` rows: the page asked for (clamped into range) and which rows it holds.

    ``page_size`` of ``None`` (or <= 0) means "no paging": one page with every row (``end`` is None).
    """
    if not page_size or page_size <= 0:
        meta = {
            "page": 1,
            "page_size": None,
            "total": total,
            "total_pages": 1,
            "has_prev": False,
            "has_next": False,
        }
        return meta, 0, None

    total_pages = (total + page_size - 1) // page_size if total else 1
    current = page if page >= 1 else 1
    if current > total_pages:
        current = total_pages
    start = (current - 1) * page_size
    meta = {
        "page": current,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_prev": current > 1,
        "has_next": current < total_pages,
    }
    return meta, start, start + page_size


def paginate(items, page=1, page_size=None):
    """Returns ``(page_items, meta)`` for an already-built list of ``items``.

    ``page`` is 1-based. ``page_size`` of ``None`` (or <= 0) means "no paging":
    every item is returned on page 1. ``meta`` carries ``page``, ``page_size``,
    ``total`` (the unpaged count), ``total_pages`` and the ``has_prev`` /
    ``has_next`` flags, so a view renders the pager without re-counting. Slicing
    a Python list adds no query; the caller typically pairs this with a single
    ``list_memos`` call.
    """
    meta, start, end = _page_window(len(items), page, page_size)
    return (items if end is None else items[start:end]), meta


def _footer_aggregate(qs, default_tds_rate):
    """The footer totals of the memos in ``qs`` worked out by the database (same figures as ``footer_totals``).

    Each row's net of TDS is ``total - round2(total * rate / 100)`` (rounded per row, half away from zero, like
    ``memo_fees.net_of_tds``), so the sum is taken over those per-row figures, not over a rounded sum.
    """
    money = DecimalField(max_digits=20, decimal_places=2)
    less_tds = Round(
        ExpressionWrapper(
            F("total_fees") * Value(Decimal(str(default_tds_rate)), output_field=DecimalField(max_digits=7, decimal_places=2)) / Value(Decimal(100)),
            output_field=DecimalField(max_digits=30, decimal_places=8),
        ),
        2,
    )
    zero = Value(Decimal("0"), output_field=money)
    row = qs.order_by().aggregate(
        count=Count("pk"),
        total_fees=Coalesce(Sum("total_fees"), zero),
        net_of_tds=Coalesce(Sum(ExpressionWrapper(F("total_fees") - less_tds, output_field=money)), zero),
        amount_received=Coalesce(Sum("amount_received"), zero),
        amount_tds=Coalesce(Sum("amount_tds"), zero),
        amount_due=Coalesce(Sum(ExpressionWrapper(F("total_fees") - F("amount_paid"), output_field=money)), zero),
    )
    totals = {field: round2(row[field]) for field in FOOTER_FIELDS}
    totals["count"] = row["count"]
    return totals


def list_page(profile, filters=None, draft_mode="exclude_drafts", page=1, page_size=None):
    """One page of the memo list, its footer totals and the pager data: ``(page_items, meta, totals)``.

    Gives exactly what ``list_memos`` + ``paginate`` + ``footer_totals`` give, but the database counts, adds up and cuts out
    the page, so a long register costs about the same on every page: three queries (settings, the totals, the page's rows),
    and only the rows shown are built. ``unpaid_only`` is applied by the database as "stored total is more than stored paid"
    (what ``status_and_due`` says, on the stored columns that ``fees_check`` keeps honest).

    Every row shown is still worked out by ``_row_to_item`` (the one rule). If a row's effective total ever differs from its
    stored ``total_fees`` (the stored columns have drifted), or the database is not PostgreSQL (SQLite rounds differently),
    the old all-in-Python path is used for that request, so a wrong stored figure can never make this page disagree with
    the rest of the app.
    """
    filters = filters or {}
    if connection.vendor == "postgresql":
        default_tds_rate, overdue_days, written_off_on = _settings_for(profile)
        counted = _filtered_queryset(profile, filters, draft_mode, related=False, ordered=False)
        if filters.get("unpaid_only"):
            counted = counted.filter(total_fees__gt=F("amount_paid"))
        totals = _footer_aggregate(counted, default_tds_rate)
        meta, start, end = _page_window(totals["count"], page, page_size)
        rows = _filtered_queryset(profile, filters, draft_mode)
        if filters.get("unpaid_only"):
            rows = rows.filter(total_fees__gt=F("amount_paid"))
        rows = list(rows[start:end] if end is not None else rows)
        items = [_row_to_item(memo, default_tds_rate, overdue_days, written_off_on) for memo in rows]
        if all(item["total_fees"] == round2(memo.total_fees) for item, memo in zip(items, rows)):
            return items, meta, totals
        logger.warning("Memo list: stored total_fees differs from the fee rule on a listed memo; using the full path (run fees_check)")
    everything = list_memos(profile, filters, draft_mode=draft_mode)
    page_items, meta = paginate(everything, page, page_size)
    return page_items, meta, footer_totals(everything)


def page_size_for(items_per_page):
    """The ``page_size`` for ``paginate`` from the Items per page setting.

    0 (or nothing) means everything on one page, so ``None``; anything else is that many rows, at most 1000.
    """
    try:
        number = int(items_per_page or 0)
    except (TypeError, ValueError):
        return None
    return None if number <= 0 else min(number, MAX_PAGE_SIZE)


def list_recent_matters(profile, limit=10):
    """The most recently billed matters, newest memo first (brief 5.6, Dashboard).

    Groups finalised (non-draft) memos by matter and orders by the latest memo
    date (then matter id) descending, capped at ``limit``. Each row carries the
    matter, its firm, the latest memo's date / number / id, the memo count and
    the matter's archived flag. Two queries: the grouped aggregate and one to
    read the latest memo number / id per listed matter in a single ``IN`` query.
    Drafts are excluded so this reflects real, numbered memos.
    """
    grouped = list(
        Memo.objects.filter(profile=profile, is_draft=False)
        .values("matter_id", "matter__name", "firm_id", "firm__name", "matter__is_archived")
        .annotate(last_date=Max("date"), memo_count=Count("id"))
        .order_by("-last_date", "-matter_id")[:limit]
    )
    if not grouped:
        return []

    matter_ids = [row["matter_id"] for row in grouped]
    # One query for every finalised memo in the listed matters, newest first, so
    # the first row seen per matter is its latest memo (number and id).
    latest_by_matter = {}
    for memo in (
        Memo.objects.filter(profile=profile, is_draft=False, matter_id__in=matter_ids)
        .order_by("matter_id", "-date", "-seq", "-id")
        .values("matter_id", "id", "memo_number")
    ):
        latest_by_matter.setdefault(
            memo["matter_id"],
            {"id": memo["id"], "memo_number": memo["memo_number"]},
        )

    out = []
    for row in grouped:
        latest = latest_by_matter.get(row["matter_id"], {})
        out.append(
            {
                "matter_id": row["matter_id"],
                "matter_name": row["matter__name"],
                "firm_id": row["firm_id"],
                "firm_name": row["firm__name"],
                "last_memo_date": row["last_date"],
                "last_memo_number": latest.get("memo_number"),
                "last_memo_id": latest.get("id"),
                "memo_count": row["memo_count"],
                "is_archived": row["matter__is_archived"],
            }
        )
    return out
