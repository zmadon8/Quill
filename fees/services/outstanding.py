"""Outstanding-memos read service for the Fee Register (T3.3, R-RD-1, brief 6.3).

Ports ``outstandingService.ts`` (``listOutstanding``, ``outstandingGrandTotal``,
``listOutstandingByFirm`` and ``listOutstandingScope``) to the Django ORM. The
Outstanding view lists UNPAID memos (a memo whose gross paid is strictly less
than its effective total fees) regardless of whether its matter is archived,
grouped by matter, each group sorted by ``seq`` ascending, with the groups
ordered by the lower-cased group name then the lower-cased matter name.

Naming: the desktop / TypeScript source calls it "partner" (``partnerId`` /
``partner_name`` / the ``partners`` table); the Django model calls it GROUP (the
``Group`` model, the ``group`` field and ``group_id`` on ``Memo``). So the
``partner_id`` filter maps to ``group_id`` and ``partner_name`` maps to the
group's name, exactly as in ``memo_lists`` and ``feebook``. A ``partner_id`` /
``group_id`` of ``"none"`` is a no-op (mirrors the sibling services).

Paid is GROSS (money toward the memo including the TDS withheld on its behalf),
consistent with ``memo_lists`` / ``feebook`` / ``payments``. The stored
``Memo.amount_paid`` column is that gross figure (``payments.recompute_paid`` is
its sole writer and sets it to ``round2(sum(amount + tds_amount))`` over the
memo's allocations), so this module reads that column directly rather than
running a per-row subquery. That matches the TypeScript (which aggregated the
allocations) while keeping the memo listing to ONE query.

Totals and derived values are never re-derived here (R-MEMO-1): the effective
total comes from ``memo_fees.effective_total_fees``, the informational net from
``memo_fees.net_of_tds`` at the settings default TDS rate, and the overdue flag
from ``memo_fees.compute_is_overdue`` using the settings overdue days. This
module does not multiply any fee count by its per-unit rate, so the single-fee
rule guard in ``test_memo_fees`` holds.

Filters (brief 6.3): ``firm_id``; ``partner_id`` (alias ``group_id``, ``"none"``
a no-op); ``selected_matter_ids`` (a list) OR ``matter_id``; ``include_written_off``
(written-off memos are hidden unless this is set, Req #7); and ``overdue_only``
(a written-off memo can never be overdue, so an overdue-only view implies them
off). Drafts are never outstanding and are always excluded.

Scoping (design section 11): every query is filtered by ``profile`` like the
sibling services. These are pure READS: they never bump ``data_version``.

Query-count discipline (asserted in the tests with ``assertNumQueries``):
``list_outstanding`` and ``list_outstanding_by_firm`` and ``list_outstanding_scope``
are each TWO queries, one to read the settings (the net-of-TDS rate and the
overdue days) and one for the memo rows (``select_related`` on firm, matter and
group so their names cost no per-row query, and the stored gross paid column is
on the row so there is no per-row subquery). The in-memory grouping, subtotals
and sorting add no query.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.db.models.functions import Lower

from fees.models import FeesSettings, Memo
from fees.services import memo_fees
from fees.services.money import round2

__all__ = [
    "list_outstanding",
    "outstanding_grand_total",
    "list_outstanding_by_firm",
    "list_outstanding_scope",
    "AGEING_BUCKETS",
    "age_bucket",
    "ageing_totals",
]

#: The status passed to ``compute_is_overdue`` for an outstanding memo: by
#: definition every memo reaching that call is unpaid (paid < total).
_UNPAID = "Unpaid"


def _settings_for(profile):
    """Reads ``default_tds_rate`` and ``overdue_days`` for ``profile`` in ONE query.

    Returns ``(default_tds_rate, overdue_days)`` as plain numbers, each falling
    back to 0 when the profile has no settings row yet. A read, so it does NOT
    get-or-create the row (mirrors ``memo_lists._settings_for``).
    """
    row = (
        FeesSettings.objects.filter(profile=profile)
        .values("default_tds_rate", "overdue_days")
        .first()
    ) or {}
    return (row.get("default_tds_rate") or 0, row.get("overdue_days") or 0)


def _scoped_memos(profile, filters):
    """The scoped, draft-free ``Memo`` queryset for the outstanding view.

    Applies the common filters (``firm_id``; ``partner_id`` alias ``group_id``,
    ``"none"`` a no-op; ``include_written_off``) shared by every entry point.
    Drafts are always excluded (a draft has no number and is never outstanding).
    ``select_related`` on firm, matter and group so their names cost no per-row
    query. The ``overdue_only`` and matter filters are applied by the callers
    that need them.
    """
    qs = (
        Memo.objects.filter(profile=profile, is_draft=False)
        .select_related("firm", "matter", "group")
    )

    firm_id = filters.get("firm_id")
    if firm_id is not None:
        qs = qs.filter(firm_id=firm_id)

    # The original UI calls this "partner"; the model field is group. A value of
    # "none" is a no-op (mirrors memo_lists / feebook).
    group_id = filters.get("partner_id", filters.get("group_id"))
    if group_id == "none":
        pass
    elif group_id is not None:
        qs = qs.filter(group_id=group_id)

    # Written-off memos are excluded unless explicitly included (Req #7).
    if not filters.get("include_written_off"):
        qs = qs.filter(written_off=False)

    return qs


def _in_age_range(memo, filters, today):
    """False when the ``age`` filter (an ``AGEING_BUCKETS`` key) is set and the memo falls outside that range."""
    age = filters.get("age")
    if not age:
        return True
    return age_index(age) == age_bucket(memo.date, today)


def age_index(key):
    """The index into ``AGEING_BUCKETS`` for a range key such as ``"31-60"`` (the last bucket if unknown)."""
    for index, bucket in enumerate(AGEING_BUCKETS):
        if bucket[0] == key:
            return index
    return len(AGEING_BUCKETS) - 1


def _is_overdue(memo, overdue_days):
    """Whether an (already unpaid) memo is overdue, via the shared rule.

    A written-off memo can never be overdue, which ``compute_is_overdue`` already
    enforces from the memo's ``written_off`` flag.
    """
    return memo_fees.compute_is_overdue(
        memo.date, _UNPAID, memo.written_off, overdue_days
    )


def list_outstanding(profile, filters=None):
    """Lists unpaid memos grouped by matter, with subtotals (R-RD-1, brief 6.3).

    Returns a list of group dicts, one per matter that has at least one unpaid
    memo, ordered by the lower-cased group (partner) name then the lower-cased
    matter name. Each group carries ``entries`` (sorted by ``seq`` ascending) and
    the subtotals ``subtotal`` (sum of ``due``), ``subtotal_total`` (sum of
    ``total_fees``), ``subtotal_net_of_tds`` and ``subtotal_paid``.

    ``filters`` is an optional dict with any of ``firm_id``, ``partner_id``
    (alias ``group_id``; ``"none"`` a no-op), ``selected_matter_ids`` (a list) OR
    ``matter_id``, ``include_written_off`` and ``overdue_only``. A memo is listed
    only when its gross paid is strictly less than its effective total fees;
    drafts are always excluded; archived matters are NOT excluded.

    Two queries: one for the settings (net-of-TDS rate and overdue days) and one
    for the memo rows. The grouping, subtotals and ordering are pure in-memory.
    """
    filters = filters or {}
    default_tds_rate, overdue_days = _settings_for(profile)

    qs = _scoped_memos(profile, filters)

    selected = filters.get("selected_matter_ids")
    if selected:
        qs = qs.filter(matter_id__in=list(selected))
    else:
        matter_id = filters.get("matter_id")
        if matter_id is not None:
            qs = qs.filter(matter_id=matter_id)

    qs = qs.order_by(Lower("group__name"), Lower("matter__name"), "seq")

    overdue_only = filters.get("overdue_only") is True
    today = datetime.date.today()
    groups = {}

    for memo in qs:
        total_fees = memo_fees.effective_total_fees(memo)
        paid = round2(memo.amount_paid)
        # Only unpaid memos (gross paid strictly below the total).
        if paid >= total_fees:
            continue

        is_overdue = _is_overdue(memo, overdue_days)
        if overdue_only and not is_overdue:
            continue
        if not _in_age_range(memo, filters, today):
            continue

        net = memo_fees.net_of_tds(total_fees, default_tds_rate)
        due = round2(max(Decimal("0"), total_fees - paid))
        entry = {
            "memo_id": memo.pk,
            "date": memo.date,
            "memo_number": memo.memo_number,
            "matter_id": memo.matter_id,
            "matter_name": memo.matter.name,
            "firm_id": memo.firm_id,
            "firm_name": memo.firm.name,
            "partner_name": memo.group.name,
            "total_fees": total_fees,
            "net_of_tds": net,
            "amount_paid": paid,
            "due": due,
            "is_overdue": is_overdue,
            "is_written_off": memo.written_off,
        }

        group = groups.get(memo.matter_id)
        if group is None:
            group = {
                "matter_id": memo.matter_id,
                "matter_name": memo.matter.name,
                "firm_id": memo.firm_id,
                "firm_name": memo.firm.name,
                "partner_id": memo.group_id,
                "partner_name": memo.group.name,
                "entries": [],
                "subtotal": Decimal("0.00"),
                "subtotal_total": Decimal("0.00"),
                "subtotal_net_of_tds": Decimal("0.00"),
                "subtotal_paid": Decimal("0.00"),
            }
            groups[memo.matter_id] = group

        group["entries"].append(entry)
        group["subtotal"] = round2(group["subtotal"] + due)
        group["subtotal_total"] = round2(group["subtotal_total"] + total_fees)
        group["subtotal_net_of_tds"] = round2(group["subtotal_net_of_tds"] + net)
        group["subtotal_paid"] = round2(group["subtotal_paid"] + paid)

    return list(groups.values())


def outstanding_grand_total(groups):
    """The round2 sum of every group's ``subtotal`` (the grand total of due)."""
    total = Decimal("0.00")
    for group in groups:
        total = round2(total + group["subtotal"])
    return total


#: Ageing buckets for the Outstanding summary (owner round 2026-11): days since the memo date.
AGEING_BUCKETS = (("0-30", "0-30 days", 0, 30), ("31-60", "31-60 days", 31, 60), ("61-90", "61-90 days", 61, 90),
                  ("90+", "Over 90 days", 91, None))


def age_bucket(memo_date, today=None):
    """The index into ``AGEING_BUCKETS`` for a memo dated ``memo_date`` (a memo with no date, or dated ahead, counts as new)."""
    today = today or datetime.date.today()
    days = (today - memo_date).days if memo_date else 0
    for index, (_key, _label, _low, high) in enumerate(AGEING_BUCKETS):
        if high is not None and days <= high:
            return index
    return len(AGEING_BUCKETS) - 1


def ageing_totals(rows):
    """[{key, label, amount, memo_count}] summed over the firm rows of :func:`list_outstanding_by_firm`."""
    out = [{"key": key, "label": label, "amount": Decimal("0.00"), "memo_count": 0} for key, label, _l, _h in AGEING_BUCKETS]
    for row in rows:
        for index, (amount, count) in enumerate(row.get("ageing", ())):
            out[index]["amount"] = round2(out[index]["amount"] + amount)
            out[index]["memo_count"] += count
    return out


def list_outstanding_by_firm(profile, filters=None, sort="amount", today=None):
    """Firm-wise outstanding summary: one row per firm (Req #3, brief 6.3).

    Returns a list of dicts ``{firm_id, firm_name, outstanding, memo_count}``
    where ``outstanding`` is the total unpaid balance across the firm's memos and
    ``memo_count`` counts the unpaid memos. ``sort`` is ``"amount"`` (default,
    descending by outstanding) or ``"name"`` (firm name A to Z, case-insensitive).

    Honours the same ``firm_id`` / ``partner_id`` (alias ``group_id``) /
    ``include_written_off`` / ``overdue_only`` filters and the same unpaid rule as
    ``list_outstanding``; the matter filters do not apply here. Two queries: the
    settings and the memo rows.
    """
    filters = filters or {}
    _default_tds_rate, overdue_days = _settings_for(profile)
    overdue_only = filters.get("overdue_only") is True
    today = today or datetime.date.today()

    by_firm = {}
    for memo in _scoped_memos(profile, filters):
        total_fees = memo_fees.effective_total_fees(memo)
        outstanding = round2(total_fees - round2(memo.amount_paid))
        # Only unpaid balances.
        if outstanding <= 0:
            continue
        if overdue_only and not _is_overdue(memo, overdue_days):
            continue
        if not _in_age_range(memo, filters, today):
            continue

        summary = by_firm.get(memo.firm_id)
        if summary is None:
            summary = {
                "firm_id": memo.firm_id,
                "firm_name": memo.firm.name,
                "outstanding": Decimal("0.00"),
                "memo_count": 0,
                "ageing": [[Decimal("0.00"), 0] for _bucket in AGEING_BUCKETS],
            }
            by_firm[memo.firm_id] = summary
        summary["outstanding"] = round2(summary["outstanding"] + outstanding)
        summary["memo_count"] += 1
        bucket = summary["ageing"][age_bucket(memo.date, today)]
        bucket[0] = round2(bucket[0] + outstanding)
        bucket[1] += 1

    rows = list(by_firm.values())
    if sort == "name":
        rows.sort(key=lambda r: r["firm_name"].lower())
    else:
        rows.sort(key=lambda r: r["outstanding"], reverse=True)
    return rows


def list_outstanding_scope(profile, filters=None):
    """Distinct firms and partners (groups) with a qualifying outstanding memo.

    Returns ``{"firms": [{"id", "name"}], "partners": [{"id", "firm_id", "name"}]}``
    listing only the firms and groups that have at least one unpaid memo under the
    current view, so the Outstanding filter dropdowns show only names with
    applicable items. Honours ``include_written_off`` and ``overdue_only`` (the
    same unpaid rule as ``list_outstanding``). Each list is sorted by its name,
    case-insensitively. Two queries: the settings and the memo rows.
    """
    filters = filters or {}
    _default_tds_rate, overdue_days = _settings_for(profile)
    overdue_only = filters.get("overdue_only") is True

    # Scope ignores firm / partner narrowing so the dropdowns can offer every
    # firm / group that has an applicable memo; it honours include_written_off
    # and overdue_only only.
    qs = (
        Memo.objects.filter(profile=profile, is_draft=False)
        .select_related("firm", "group")
    )
    if not filters.get("include_written_off"):
        qs = qs.filter(written_off=False)

    firms = {}
    partners = {}
    for memo in qs:
        total_fees = memo_fees.effective_total_fees(memo)
        paid = round2(memo.amount_paid)
        if paid >= total_fees:
            continue
        if overdue_only and not _is_overdue(memo, overdue_days):
            continue
        firms[memo.firm_id] = memo.firm.name
        partners[memo.group_id] = {"firm_id": memo.firm_id, "name": memo.group.name}

    firm_list = [
        {"id": firm_id, "name": name} for firm_id, name in firms.items()
    ]
    firm_list.sort(key=lambda f: f["name"].lower())

    partner_list = [
        {"id": group_id, "firm_id": info["firm_id"], "name": info["name"]}
        for group_id, info in partners.items()
    ]
    partner_list.sort(key=lambda p: p["name"].lower())

    return {"firms": firm_list, "partners": partner_list}
