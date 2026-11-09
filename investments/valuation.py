"""As-of prices and alternative-investment values (plan sections 11, 12 and 16.5). Pure Python, no Django imports.

* ``as_of_price(series, on)``: the last close on or before ``on`` (weekends and holidays use the previous close). A
  series is a list of ``(date, price)`` sorted by date.
* ``alt_value_on(values, on, mode)``: an alternative investment's value on any date between dated entries. Mode
  ``"unchanged"`` keeps the earlier value until the next entry; ``"averaged"`` spreads the change evenly over the days in
  between. After the latest entry, and before the first, the nearest entry's value is held.
"""
from bisect import bisect_right
from decimal import Decimal

UNCHANGED = "unchanged"
AVERAGED = "averaged"


def as_of_price(series, on):
    """``(date, price)`` of the last entry on or before ``on``, or ``None`` when there is none."""
    index = bisect_right(series, (on, Decimal("Infinity")))
    return series[index - 1] if index else None


def alt_value_on(values, on, mode=UNCHANGED):
    """Value of an alternative investment on ``on`` from ``[(date, total value), ...]`` sorted by date, or ``None``."""
    if not values:
        return None
    index = bisect_right(values, (on, Decimal("Infinity")))
    if index == 0:
        return None  # before the first entry nothing is known; the caller falls back to cost
    d0, v0 = values[index - 1]
    if mode != AVERAGED or index >= len(values):
        return v0
    d1, v1 = values[index]
    span = (d1 - d0).days
    if span <= 0:
        return v0
    return v0 + (v1 - v0) * Decimal((on - d0).days) / Decimal(span)


def position_value(units, price):
    """Units times price (``None`` when either is unknown)."""
    if price is None or units is None:
        return None
    return units * price
