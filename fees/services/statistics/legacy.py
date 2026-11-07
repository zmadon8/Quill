"""Legacy statistics breakdown for the Fee Register (T3.8).

Ports ``getStatistics``: the legacy aggregate by financial year, firm, partner
(the Django ``Group``) or matter, used by the comparison table's secondary
breakdown and by the property test. Billed and appearances come from the memo
(billing period). For the financial-year breakdown, received is attributed by
the PAYMENT date's FY (receipt basis) and a row is ensured even for an FY that
only has receipts; for the firm / partner / matter breakdowns, received is the
per-memo net (intrinsic to the memo, not time-sensitive).

Guard note: billed is the summed stored ``total_fees`` column, so no line fee is
computed here.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import ExtractMonth, ExtractYear

from fees.models import Allocation, Memo
from fees.services.financial_year import derive_financial_year
from fees.services.money import round2

__all__ = ["get_statistics"]

_ZERO = Decimal("0")

#: breakdown -> (id values key, name values key, group-key prefix).
_DIMS = {
    "financialYear": ("financial_year", "financial_year", None),
    "firm": ("firm_id", "firm__name", "firm"),
    "partner": ("group_id", "group__name", "partner"),
    "matter": ("matter_id", "matter__name", "matter"),
}


def get_statistics(profile, breakdown):
    """Legacy aggregate by FY / firm / partner / matter (ports ``getStatistics``).

    ``breakdown`` is one of ``'financialYear'``, ``'firm'``, ``'partner'``,
    ``'matter'`` (``'partner'`` reads the ``Group``). Returns
    ``{"breakdown", "rows", "totals"}`` where each row and the totals carry
    ``num_appearances``, ``amount_billed`` and ``amount_received`` (snake_case).
    Rows are sorted by FY descending for the FY breakdown, else by label
    case-insensitively.
    """
    id_field, name_field, prefix = _DIMS[breakdown]
    by_fy_receipt = breakdown == "financialYear"

    groups = {}
    totals = {
        "num_appearances": 0,
        "amount_billed": _ZERO,
        "amount_received": _ZERO,
    }

    def key_label(row_id, name):
        if prefix is None:
            return name, name
        return f"{prefix}:{row_id}", name

    def group_for(key, label):
        g = groups.get(key)
        if g is None:
            g = {
                "key": key,
                "label": label,
                "num_appearances": 0,
                "amount_billed": _ZERO,
                "amount_received": _ZERO,
            }
            groups[key] = g
        return g

    # Billed and appearances (and per-memo net received for non-FY breakdowns),
    # grouped by the chosen dimension from non-draft memos.
    if by_fy_receipt:
        memo_rows = (
            Memo.objects.filter(profile=profile, is_draft=False)
            .values(id_field, name_field)
            .annotate(apps=Sum("num_appearances"), billed=Sum("total_fees"))
        )
    else:
        # Net received per memo is attached via the memo's allocations; summing
        # Sum("total_fees") would multiply by the allocation fan-out, so read the
        # stored net column on the memo instead (maintained by payments).
        memo_rows = (
            Memo.objects.filter(profile=profile, is_draft=False)
            .values(id_field, name_field)
            .annotate(
                apps=Sum("num_appearances"),
                billed=Sum("total_fees"),
                received=Sum("amount_received"),
            )
        )

    for r in memo_rows:
        billed = round2(r["billed"] or _ZERO)
        key, label = key_label(r[id_field], r[name_field])
        g = group_for(key, label)
        g["num_appearances"] += r["apps"] or 0
        g["amount_billed"] = round2(g["amount_billed"] + billed)
        totals["num_appearances"] += r["apps"] or 0
        totals["amount_billed"] = round2(totals["amount_billed"] + billed)
        if not by_fy_receipt:
            received = round2(r["received"] or _ZERO)
            g["amount_received"] = round2(g["amount_received"] + received)
            totals["amount_received"] = round2(
                totals["amount_received"] + received
            )

    if by_fy_receipt:
        # Received per FY of the PAYMENT; ensure a row exists for an FY that only
        # has receipts. Bucket the grouped year + month rows in Python.
        recv_rows = (
            Allocation.objects.filter(profile=profile)
            .annotate(
                pay_year=ExtractYear("payment__date_of_payment"),
                pay_month=ExtractMonth("payment__date_of_payment"),
            )
            .values("pay_year", "pay_month")
            .annotate(received=Sum("amount"))
        )
        per_fy = {}
        for r in recv_rows:
            fy = derive_financial_year(datetime.date(r["pay_year"], r["pay_month"], 1))
            per_fy[fy] = round2(per_fy.get(fy, _ZERO) + (r["received"] or _ZERO))
        for fy, received in per_fy.items():
            g = group_for(fy, fy)
            g["amount_received"] = round2(g["amount_received"] + received)
            totals["amount_received"] = round2(
                totals["amount_received"] + received
            )

    out = list(groups.values())
    if by_fy_receipt:
        out.sort(key=lambda g: g["key"], reverse=True)
    else:
        out.sort(key=lambda g: g["label"].lower())

    return {"breakdown": breakdown, "rows": out, "totals": totals}
