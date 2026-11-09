"""The index-equivalent comparison (plan 9, "Index-equivalent comparison"). Pure Python, no Django imports.

Take the same cash flows (same dates, same amounts) and pretend each purchase bought index units at that day's index level and each
sale sold them. The XIRR of that hypothetical portfolio, with whatever index units remain valued at the end date's level, is the index's
XIRR over the same cash flows; the difference from the actual XIRR is Alpha. It needs only the index close on each transaction date and
on the end date. If any needed level is missing the answer is None, never a guess.
"""
from decimal import Decimal

from investments import xirr as xirr_module


def replay(flows, level, end_date):
    """``flows`` is ``[(date, amount)]`` with money paid in negative and received positive (the XIRR convention), ``level(date)`` the
    index close (or None), ``end_date`` where the remaining index units are valued. Returns ``(index flows, closing value)`` or None."""
    units = Decimal(0)
    out = []
    for day, amount in sorted(flows, key=lambda f: f[0]):
        if amount == 0:
            continue
        at = level(day)
        if at is None or at <= 0:
            return None
        units += (-amount) / at          # money paid in buys index units; money received sells them
        out.append((day, amount))
    final = level(end_date)
    if final is None or final <= 0:
        return None
    return out, units * final


def index_xirr(flows, level, end_date, min_days=xirr_module.MIN_DAYS):
    """The index's XIRR over the same cash flows, or None."""
    replayed = replay(flows, level, end_date)
    if replayed is None:
        return None
    out, closing = replayed
    return xirr_module.xirr([(d, float(a)) for d, a in out] + [(end_date, float(closing))], min_days=min_days)


def alpha(actual, index):
    """Actual XIRR less the index's, or None if either is unknown."""
    return None if actual is None or index is None else actual - index
