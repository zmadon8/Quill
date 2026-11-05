"""Year-end summary for the Fee Register statistics (T3.8).

Ports ``getYearEndSummary``. Appearances and appearances-per-week come from the
same period engine as the Statistics table (``get_period_statistics`` at
``financialYear`` granularity), so the two always agree (extras, overrides and
pro-rating included). Billed and written-off are from the non-draft memos of the
FY (summing the stored ``total_fees`` column); received and TDS are attributed
by the PAYMENT date's financial year (receipt basis); new matters are the
matters whose earliest non-draft memo falls in the FY; active firms are the
distinct firms billed that FY.

Guard note: billed is the summed stored ``total_fees`` column, so no line fee is
computed here.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Min, Q, Sum
from django.db.models.functions import ExtractMonth, ExtractYear

from fees.models import Allocation, Memo
from fees.services.money import round2
from fees.services.statistics.periods import get_period_statistics

__all__ = ["get_year_end_summary"]

_ZERO = Decimal("0")


def _payment_fy(year, month) -> str:
    """The FY label for a payment's calendar year and month (Apr-Mar)."""
    start_year = year if month >= 4 else year - 1
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def get_year_end_summary(profile, financial_year, options=None):
    """The year-end totals for one financial year (ports ``getYearEndSummary``).

    Returns a dict with snake_case keys: ``financial_year``, ``memo_count``,
    ``total_billed``, ``total_received``, ``total_tds``, ``total_written_off``,
    ``new_matters``, ``active_firms``, ``num_appearances``,
    ``appearances_per_week``.
    """
    options = options or {}

    # Appearances come from the period engine, so they match the table exactly.
    fy_periods = get_period_statistics(
        profile, "financialYear", None, options
    )["periods"]
    period = next(
        (p for p in fy_periods if p["financial_year"] == financial_year), None
    )

    # Billed (stored effective total) and written-off for the FY's non-draft memos.
    memo_agg = (
        Memo.objects.filter(
            profile=profile, is_draft=False, financial_year=financial_year
        )
        .aggregate(
            memo_count=Count("id"),
            total_billed=Sum("total_fees"),
            total_written_off=Sum(
                "total_fees", filter=Q(written_off=True)
            ),
        )
    )
    total_billed = round2(memo_agg["total_billed"] or _ZERO)
    total_written_off = round2(memo_agg["total_written_off"] or _ZERO)
    memo_count = memo_agg["memo_count"] or 0

    # Received (net) and TDS by PAYMENT date FY (receipt basis), bucketed in
    # Python from the grouped year + month rows so it stays one query.
    recv_rows = (
        Allocation.objects.filter(profile=profile)
        .annotate(
            pay_year=ExtractYear("payment__date_of_payment"),
            pay_month=ExtractMonth("payment__date_of_payment"),
        )
        .values("pay_year", "pay_month")
        .annotate(received=Sum("amount"), tds=Sum("tds_amount"))
    )
    total_received = _ZERO
    total_tds = _ZERO
    for r in recv_rows:
        if _payment_fy(r["pay_year"], r["pay_month"]) == financial_year:
            total_received = round2(total_received + (r["received"] or _ZERO))
            total_tds = round2(total_tds + (r["tds"] or _ZERO))

    # New matters: matters whose earliest non-draft memo falls in this FY.
    new_matters = 0
    first_rows = (
        Memo.objects.filter(profile=profile, is_draft=False)
        .values("matter_id")
        .annotate(first_fy=Min("financial_year"))
    )
    for r in first_rows:
        if r["first_fy"] == financial_year:
            new_matters += 1

    active_firms = (
        Memo.objects.filter(
            profile=profile, is_draft=False, financial_year=financial_year
        )
        .values("firm_id")
        .distinct()
        .count()
    )

    return {
        "financial_year": financial_year,
        "memo_count": memo_count,
        "total_billed": total_billed,
        "total_received": total_received,
        "total_tds": total_tds,
        "total_written_off": total_written_off,
        "new_matters": new_matters,
        "active_firms": active_firms,
        "num_appearances": period["num_appearances"] if period else 0,
        "appearances_per_week": period["appearances_per_week"] if period else _ZERO,
    }
