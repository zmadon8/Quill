"""Flexible pivot statistics for the Fee Register (T3.8, Options 1 to 4).

Ports ``getPivot`` and ``getPerWeekPivot``. A pivot picks a MEASURE and groups
it by a ROW dimension and an optional COLUMN dimension, which gives month-wise,
quarter-wise, year-wise, same-month-across-years and firm / partner / matter
breakdowns from one function.

Receipt measures (``received`` / ``receivedPlusTds``) are driven by
payment-allocation rows carrying the payment's date (for the time axes) and the
memo's firm / partner / matter (for those axes). All other measures are driven
by non-draft memo rows (billing period). ``appearancesPerWeek`` / ``feesPerWeek``
delegate to ``get_per_week_pivot``, whose values come from the period engine so
they always match the Statistics table.

Naming: the pivot ``partner`` dimension reads the memo's ``Group`` (the model
name for the desktop "partner").

Pivot cap: the TypeScript source applies NO explicit numeric cap to the number
of pivot rows or cells; the only bound is memory. This port therefore does not
invent a row / cell count limit (that would silently drop data the TS keeps).
Instead it honours the real constraint behind the "pivot cap" phrasing, the
pivot < 8 MB memory gate, by streaming the driving rows with ``.iterator()`` and
reading only the handful of columns each cell needs (via ``.values(...)``),
never materialising a per-memo object list. Row / column metadata and the cell
map are bounded by the number of distinct dimension values, not by the row
count, so a large dataset aggregates in near-constant memory. This choice is
documented here per the feature brief.

Guard note: for the billed measure the value read is the stored ``total_fees``
column, so no memo line fee is computed here.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models.functions import ExtractMonth, ExtractYear

from fees.errors import FeesError
from fees.models import Allocation, Memo
from fees.services.financial_year import quarter_of_month
from fees.services.money import round2
from fees.services.statistics._common import max_fy
from fees.services.statistics.periods import (
    _settings_initial_fy,
    get_period_statistics,
)
from fees.services.statistics.year_end import _payment_fy  # FY of a (year, month)

__all__ = ["get_pivot", "get_per_week_pivot"]

_ZERO = Decimal("0")

MONTH_SHORT = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

#: Measures whose values are money (drive the ``money`` flag on the result).
MONEY_MEASURES = frozenset(
    ["billed", "received", "receivedPlusTds", "feesPerWeek"]
)

#: Measures that count DISTINCT matters per cell (set size, not a sum).
_DISTINCT_MATTER_MEASURES = frozenset(["matters", "mattersNew"])

#: Per-week measures delegate to the period engine.
_PER_WEEK_MEASURES = frozenset(["appearancesPerWeek", "feesPerWeek"])


def _pad2(n) -> str:
    return f"{int(n):02d}"


def measure_value(measure, r) -> Decimal:
    """The numeric value a driving row contributes for ``measure``.

    ``r`` is a dict carrying ``num_appearances``, ``num_conferences``,
    ``num_drafts``, ``billed``, ``received``, ``received_plus_tds``. The
    distinct-matter and per-week measures return 0 here (handled separately).
    """
    if measure == "appearances":
        return Decimal(str(r["num_appearances"]))
    if measure == "conferences":
        return Decimal(str(r["num_conferences"]))
    if measure == "drafts":
        return Decimal(str(r["num_drafts"]))
    if measure == "billed":
        return r["billed"]
    if measure == "received":
        return r["received"]
    if measure == "receivedPlusTds":
        return r["received_plus_tds"]
    if measure == "memos":
        return Decimal("1")
    # matters / mattersNew / appearancesPerWeek / feesPerWeek.
    return _ZERO


def fy_quarter(cal_month) -> int:
    """FY quarter of a calendar month (Q1 Apr-Jun ... Q4 Jan-Mar)."""
    return quarter_of_month(cal_month)


def row_axis(r, dim):
    """The ``(key, label, sort)`` of a driving row on the ROW dimension ``dim``."""
    cal_month = int(r["cal_month"])
    fy = r["financial_year"]
    if dim == "month":
        key = f"{fy}-{_pad2(cal_month)}"
        return key, f"{MONTH_SHORT[cal_month - 1]} {fy}", key
    if dim == "quarter":
        q = fy_quarter(cal_month)
        return f"{fy}-Q{q}", f"Q{q} {fy}", f"{fy}-{q}"
    if dim == "financialYear":
        return fy, fy, fy
    if dim == "calendarMonth":
        return str(cal_month), MONTH_SHORT[cal_month - 1], _pad2(cal_month)
    if dim == "firm":
        return f"firm:{r['firm_id']}", r["firm_name"], (r["firm_name"] or "").lower()
    if dim == "partner":
        return (
            f"partner:{r['partner_id']}",
            r["partner_name"],
            (r["partner_name"] or "").lower(),
        )
    if dim == "matter":
        return (
            f"matter:{r['matter_id']}",
            r["matter_name"],
            (r["matter_name"] or "").lower(),
        )
    raise FeesError("UNKNOWN", f"Unknown pivot row dimension: {dim}")


def col_axis(r, dim):
    """The ``(key, label, sort)`` of a driving row on the COLUMN dimension ``dim``."""
    cal_month = int(r["cal_month"])
    fy = r["financial_year"]
    if dim == "none":
        return "value", "Value", "0"
    if dim == "financialYear":
        return fy, fy, fy
    if dim == "calendarMonth":
        return str(cal_month), MONTH_SHORT[cal_month - 1], _pad2(cal_month)
    raise FeesError("UNKNOWN", f"Unknown pivot column dimension: {dim}")


def _firm_ids(req):
    """The effective firm filter: ``firm_ids`` (multi) wins over single ``firm_id``."""
    firm_ids = req.get("firm_ids")
    if firm_ids:
        return list(firm_ids)
    firm_id = req.get("firm_id")
    if firm_id is not None:
        return [firm_id]
    return []


def _driving_rows(profile, req, firm_ids, is_receipt):
    """Yields the driving rows (as dicts) for the pivot, streamed with ``.iterator()``.

    For a receipt measure each row is one allocation carrying the PAYMENT date's
    FY + month and the memo's firm / partner / matter. Otherwise each row is a
    non-draft memo carrying its own FY + month, counts and stored billed total.
    """
    from_fy = req.get("from_fy")
    to_fy = req.get("to_fy")

    if is_receipt:
        qs = Allocation.objects.filter(profile=profile, memo__is_draft=False)
        if firm_ids:
            qs = qs.filter(memo__firm_id__in=firm_ids)
        qs = qs.annotate(
            pay_year=ExtractYear("payment__date_of_payment"),
            pay_month=ExtractMonth("payment__date_of_payment"),
        ).values(
            "pay_year",
            "pay_month",
            "memo__firm_id",
            "memo__firm__name",
            "memo__group_id",
            "memo__group__name",
            "memo__matter_id",
            "memo__matter__name",
            "amount",
            "tds_amount",
        )
        for a in qs.iterator():
            fy = _payment_fy(a["pay_year"], a["pay_month"])
            if from_fy and fy < from_fy:
                continue
            if to_fy and fy > to_fy:
                continue
            amount = a["amount"] or _ZERO
            tds = a["tds_amount"] or _ZERO
            yield {
                "memo_id": None,
                "financial_year": fy,
                "cal_month": a["pay_month"],
                "firm_id": a["memo__firm_id"],
                "firm_name": a["memo__firm__name"],
                "partner_id": a["memo__group_id"],
                "partner_name": a["memo__group__name"],
                "matter_id": a["memo__matter_id"],
                "matter_name": a["memo__matter__name"],
                "num_appearances": 0,
                "num_conferences": 0,
                "num_drafts": 0,
                "billed": _ZERO,
                "received": round2(amount),
                "received_plus_tds": round2(amount + tds),
            }
        return

    qs = Memo.objects.filter(profile=profile, is_draft=False)
    if firm_ids:
        qs = qs.filter(firm_id__in=firm_ids)
    if from_fy:
        qs = qs.filter(financial_year__gte=from_fy)
    if to_fy:
        qs = qs.filter(financial_year__lte=to_fy)
    qs = qs.annotate(cal_month=ExtractMonth("date")).values(
        "id",
        "financial_year",
        "cal_month",
        "firm_id",
        "firm__name",
        "group_id",
        "group__name",
        "matter_id",
        "matter__name",
        "num_appearances",
        "num_conferences",
        "num_drafts",
        "total_fees",
    )
    for m in qs.iterator():
        yield {
            "memo_id": m["id"],
            "financial_year": m["financial_year"],
            "cal_month": m["cal_month"],
            "firm_id": m["firm_id"],
            "firm_name": m["firm__name"],
            "partner_id": m["group_id"],
            "partner_name": m["group__name"],
            "matter_id": m["matter_id"],
            "matter_name": m["matter__name"],
            "num_appearances": m["num_appearances"],
            "num_conferences": m["num_conferences"],
            "num_drafts": m["num_drafts"],
            "billed": round2(m["total_fees"] or _ZERO),
            "received": _ZERO,
            "received_plus_tds": _ZERO,
        }


def _first_memo_by_matter(profile, firm_ids):
    """Each matter's first-ever memo id (earliest date, then lowest id).

    Honours the firm filter but IGNORES the FY range, so a matter whose true
    first memo predates the range is correctly not "new" within the range. One
    query, read in ``(matter, date, id)`` order; the first row per matter wins.
    """
    qs = Memo.objects.filter(profile=profile, is_draft=False)
    if firm_ids:
        qs = qs.filter(firm_id__in=firm_ids)
    first = {}
    rows = qs.order_by("matter_id", "date", "id").values_list(
        "matter_id", "id"
    )
    for matter_id, memo_id in rows.iterator():
        if matter_id not in first:
            first[matter_id] = memo_id
    return first


def get_pivot(profile, req):
    """Flexible pivot of a measure over a row and an optional column dimension.

    ``req`` is a dict with ``measure``, ``row_dim``, ``col_dim`` and optional
    ``firm_id`` / ``firm_ids`` / ``from_fy`` / ``to_fy``. ``from_fy`` is clamped
    up to the settings Initial FY. Returns a ``PivotResult`` dict with
    ``measure``, ``row_dim``, ``col_dim``, ``money``, ``columns``, ``rows``,
    ``column_totals`` and ``grand_total``.
    """
    measure = req["measure"]
    row_dim = req["row_dim"]
    col_dim = req["col_dim"]

    if measure in _PER_WEEK_MEASURES:
        return get_per_week_pivot(profile, req)

    # Clamp fromFy up to the Initial FY (the period engine reads it too, but the
    # pivot filters memos / payments directly, so clamp here).
    initial_fy = _settings_initial_fy(profile)
    req = dict(req)
    req["from_fy"] = max_fy(req.get("from_fy"), initial_fy)

    firm_ids = _firm_ids(req)
    is_receipt = measure in ("received", "receivedPlusTds")
    is_distinct_matters = measure in _DISTINCT_MATTER_MEASURES
    is_matters_new = measure == "mattersNew"

    first_memo_by_matter = (
        _first_memo_by_matter(profile, firm_ids) if is_matters_new else None
    )

    col_meta = {}
    row_meta = {}
    cells = {}  # row_key -> {col_key: value}
    matter_sets = {}  # "row_key|col_key" -> set of matter ids

    for r in _driving_rows(profile, req, firm_ids, is_receipt):
        if is_matters_new and first_memo_by_matter.get(r["matter_id"]) != r["memo_id"]:
            continue
        ra_key, ra_label, ra_sort = row_axis(r, row_dim)
        ca_key, ca_label, ca_sort = col_axis(r, col_dim)
        if ra_key not in row_meta:
            row_meta[ra_key] = (ra_label, ra_sort)
        if ca_key not in col_meta:
            col_meta[ca_key] = (ca_label, ca_sort)
        row_cells = cells.setdefault(ra_key, {})
        if is_distinct_matters:
            sk = f"{ra_key}|{ca_key}"
            matter_set = matter_sets.setdefault(sk, set())
            matter_set.add(r["matter_id"])
            row_cells[ca_key] = len(matter_set)
        else:
            value = measure_value(measure, r)
            row_cells[ca_key] = round2((row_cells.get(ca_key, _ZERO)) + value)

    columns = [
        {"key": key, "label": meta[0]}
        for key, meta in sorted(col_meta.items(), key=lambda kv: kv[1][1])
    ]

    column_totals = {}
    grand_total = _ZERO
    rows_out = []
    for row_key, meta in sorted(row_meta.items(), key=lambda kv: kv[1][1]):
        row_cells = cells.get(row_key, {})
        out_cells = {}
        total = _ZERO
        for col in columns:
            v = round2(row_cells.get(col["key"], _ZERO))
            out_cells[col["key"]] = v
            total = round2(total + v)
            column_totals[col["key"]] = round2(
                column_totals.get(col["key"], _ZERO) + v
            )
        grand_total = round2(grand_total + total)
        rows_out.append(
            {"key": row_key, "label": meta[0], "cells": out_cells, "total": total}
        )

    return {
        "measure": measure,
        "row_dim": row_dim,
        "col_dim": col_dim,
        "money": measure in MONEY_MEASURES,
        "columns": columns,
        "rows": rows_out,
        "column_totals": column_totals,
        "grand_total": grand_total,
    }


def get_per_week_pivot(profile, req):
    """Per-week measures (appearances / fees per week) from the period engine.

    Only time rows (``month`` / ``quarter`` / ``financialYear``) and no firm
    filter are allowed (``FeesError('UNKNOWN', ...)`` otherwise). Values come from
    ``get_period_statistics`` so they match the Statistics table; future periods
    are skipped; the total is the average of the periods that have data.
    """
    measure = req["measure"]
    row_dim = req["row_dim"]
    if row_dim not in ("month", "quarter", "financialYear"):
        raise FeesError(
            "UNKNOWN", "Per-week measures need Month, Quarter or Financial Year rows."
        )
    if _firm_ids(req):
        raise FeesError(
            "UNKNOWN", "Per-week measures are available for all firms only."
        )

    from_fy = req.get("from_fy")
    to_fy = req.get("to_fy")

    def pick(period):
        if measure == "appearancesPerWeek":
            return period["appearances_per_week"]
        return period["fees_per_week"]

    fy_periods = get_period_statistics(profile, "financialYear", None)["periods"]
    fys = sorted(
        p["financial_year"]
        for p in fy_periods
        if (not from_fy or p["financial_year"] >= from_fy)
        and (not to_fy or p["financial_year"] <= to_fy)
    )

    rows_out = []
    for fy in fys:
        if row_dim == "financialYear":
            periods = [p for p in fy_periods if p["financial_year"] == fy]
        else:
            periods = get_period_statistics(profile, row_dim, fy)["periods"]
        for p in periods:
            if p.get("is_future"):
                continue
            if row_dim == "month":
                label = f"{p['label']} {fy}"
            elif row_dim == "quarter":
                label = f"{p['label'][:2]} {fy}"
            else:
                label = fy
            v = pick(p)
            rows_out.append(
                {"key": p["key"], "label": label, "cells": {"value": v}, "total": v}
            )

    non_zero = [r for r in rows_out if r["total"] > 0]
    if non_zero:
        avg = round2(sum((r["total"] for r in non_zero), _ZERO) / len(non_zero))
    else:
        avg = _ZERO

    return {
        "measure": measure,
        "row_dim": row_dim,
        "col_dim": "none",
        "money": measure in MONEY_MEASURES,
        "columns": [{"key": "value", "label": "Value"}],
        "rows": rows_out,
        "column_totals": {"value": avg},
        "grand_total": avg,
    }
