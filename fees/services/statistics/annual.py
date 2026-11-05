"""Annual per-firm / per-matter breakdown for the Fee Register statistics (T3.8).

Ports ``getAnnualBreakdown``. For one financial year it puts the billing side
(non-draft memos issued in the FY) next to the receipt side (payments dated in
the FY), grouped by firm or by matter.

Two GROUP BY queries: the billed side (count of memos, summed appearance /
conference / draft counts and the stored ``total_fees`` as billed) and the
received side (allocations joined to their payment and memo, filtered to the
payment-date FY, summing net received and TDS). The rows are merged by id and
sorted by name case-insensitively.

Guard note: billed is the summed stored ``total_fees`` column, so no line fee is
computed here.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import ExtractMonth, ExtractYear

from fees.models import Allocation, Memo
from fees.services.money import round2

__all__ = ["get_annual_breakdown"]

_ZERO = Decimal("0")


def _payment_fy(year, month) -> str:
    start_year = year if month >= 4 else year - 1
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def _blank_row(name, firm_name):
    return {
        "name": name,
        "firm_name": firm_name,
        "memos": 0,
        "appearances": 0,
        "conferences": 0,
        "drafts": 0,
        "billed": _ZERO,
        "received": _ZERO,
        "tds": _ZERO,
    }


def get_annual_breakdown(profile, financial_year, by):
    """Per-firm or per-matter figures for one FY (ports ``getAnnualBreakdown``).

    ``by`` is ``'firm'`` or ``'matter'``. Returns a list of dicts
    ``{name, firm_name, memos, appearances, conferences, drafts, billed,
    received, tds}`` sorted by ``name`` case-insensitively.
    """
    if by == "firm":
        id_field = "firm_id"
        name_field = "firm__name"
    else:
        id_field = "matter_id"
        name_field = "matter__name"

    rows = {}

    def row_for(row_id, name, firm_name):
        r = rows.get(row_id)
        if r is None:
            r = _blank_row(name, firm_name)
            rows[row_id] = r
        return r

    # Billed side: memos issued in the FY.
    billed_rows = (
        Memo.objects.filter(
            profile=profile, is_draft=False, financial_year=financial_year
        )
        .values(id_field, name_field, "firm__name")
        .annotate(
            memos=Count("id"),
            apps=Sum("num_appearances"),
            confs=Sum("num_conferences"),
            drafts=Sum("num_drafts"),
            billed=Sum("total_fees"),
        )
    )
    for b in billed_rows:
        r = row_for(b[id_field], b[name_field], b["firm__name"])
        r["memos"] = b["memos"] or 0
        r["appearances"] = b["apps"] or 0
        r["conferences"] = b["confs"] or 0
        r["drafts"] = b["drafts"] or 0
        r["billed"] = round2(b["billed"] or _ZERO)

    # Received side: payments dated in the FY, bucketed in Python by payment FY so
    # the whole breakdown stays two queries. We group by the id, the name and the
    # payment's calendar year + month, then keep only the rows in this FY.
    recv_id = f"memo__{id_field}"
    recv_name = f"memo__{name_field}"
    received_rows = (
        Allocation.objects.filter(profile=profile, memo__is_draft=False)
        .annotate(
            pay_year=ExtractYear("payment__date_of_payment"),
            pay_month=ExtractMonth("payment__date_of_payment"),
        )
        .values("pay_year", "pay_month", recv_id, recv_name, "memo__firm__name")
        .annotate(received=Sum("amount"), tds=Sum("tds_amount"))
    )
    for x in received_rows:
        if _payment_fy(x["pay_year"], x["pay_month"]) != financial_year:
            continue
        r = row_for(x[recv_id], x[recv_name], x["memo__firm__name"])
        r["received"] = round2(r["received"] + (x["received"] or _ZERO))
        r["tds"] = round2(r["tds"] + (x["tds"] or _ZERO))

    out = list(rows.values())
    out.sort(key=lambda r: r["name"].lower())
    return out
