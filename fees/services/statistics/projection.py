"""Projected Totals for the current financial year (owner round 2026-11).

For every total (Billed, Received, Received + TDS, Appearances, Conferences, Drafts, Memos)::

    projected for the year = so far / working days completed so far x working days in the whole financial year

The working days are the ones entered per month in Settings, Start Years & Statistics. A month with none entered counts 0, in
the days completed and in the year's total. Working days completed follow the Statistics rule: a past month in full, the
current month pro-rated by the days gone, a future month 0. Received is projected from its own pace (by payment date).

Split by month, the projection is: past months as they are; the current month its actual so far plus the rate a working day x
its working days still to come; a future month the rate x its working days. Those parts add up to the projected year.

Nothing is projected until at least one working day is completed. Rates (Fees / Day, Appearances / Week, % Recovered) are
averages already and are not projected. Pure arithmetic: the callers pass the figures and the working days in.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from fees.services.money import round2

__all__ = ["PROJECTED_MEASURES", "project_months", "project_total", "rounded"]

#: ``(period key, label, is_money)`` of the totals that are projected, in the Statistics table's order.
PROJECTED_MEASURES = (
    ("amount_billed", "Amount Billed", True),
    ("amount_received", "Amount Received", True),
    ("amount_received_plus_tds", "Received + TDS", True),
    ("num_appearances", "Appearances", False),
    ("num_conferences", "Conferences", False),
    ("num_drafts", "Drafts", False),
)


def rounded(value, money):
    """A money figure to two decimals, a count to a whole number."""
    value = Decimal(str(value))
    if money:
        return round2(value)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def project_total(so_far, done, total, money=True):
    """``so_far / done x total`` (rounded like the figure), or None when no working day is completed."""
    if not done or done <= 0:
        return None
    return rounded(Decimal(str(so_far)) / Decimal(done) * Decimal(total), money)


def project_months(actuals, working_days, money=True):
    """The projection of one total, month by month.

    ``actuals`` are the twelve monthly figures (financial-year order); ``working_days`` the twelve ``(entered, completed)``
    pairs. Returns None when no working day is completed, else ``{so_far, done, total, rate, projected, months}`` where
    ``months`` is twelve ``{"actual", "extra"}``: ``extra`` is the projected part still to come in that month (0 for a month
    already over).
    """
    done = sum(completed for _entered, completed in working_days)
    total = sum(entered for entered, _completed in working_days)
    if done <= 0:
        return None
    so_far = sum((Decimal(str(a or 0)) for a in actuals), Decimal("0"))
    rate = so_far / Decimal(done)
    months = []
    for actual, (entered, completed) in zip(actuals, working_days):
        to_come = max(entered - completed, 0)
        months.append({"actual": Decimal(str(actual or 0)), "extra": rate * to_come})
    return {
        "so_far": rounded(so_far, money),
        "done": done,
        "total": total,
        "rate": rate,
        "projected": rounded(rate * total, money),
        "months": months,
        "entered": [entered for entered, _completed in working_days],
    }
