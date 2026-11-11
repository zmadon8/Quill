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


def interest_value(lots, on, rate_pct, interest_type="compound"):
    """Value on ``on`` of ``[(bought_on, cost), ...]`` earning ``rate_pct`` a year: simple ``cost * (1 + r * days / 365)`` or compound
    ``cost * (1 + r) ** (days / 365)``. A lot not yet bought is left out. The one place interest growth is worked out."""
    r = float(rate_pct) / 100
    total = Decimal(0)
    for bought_on, cost in lots:
        days = (on - bought_on).days
        if days < 0:
            continue
        factor = 1 + r * days / 365.0 if interest_type == "simple" else (1 + r) ** (days / 365.0)
        total += cost * Decimal(str(factor))
    return total.quantize(Decimal("0.01"))


def remaining_lots(buys, units_held):
    """``[(bought_on, cost)]`` still held from ``[(bought_on, units, cost), ...]`` when ``units_held`` units remain: the oldest lots are sold
    first (FIFO, as in ``lots.replay``) and a part-sold lot keeps its share of the cost. The one place the chart works out what a sale left."""
    ordered = sorted(buys, key=lambda b: b[0])
    to_sell = sum((u for _d, u, _c in ordered), Decimal(0)) - units_held
    out = []
    for bought_on, units, cost in ordered:
        if to_sell >= units:
            to_sell -= units
            continue
        if to_sell > 0:
            cost = cost * (units - to_sell) / units
            to_sell = Decimal(0)
        out.append((bought_on, cost))
    return out


def alt_or_interest_value(values, on, mode, lots, rate_pct=None, interest_type="compound"):
    """An alternative investment's value on ``on``. Without a rate: the manual value held or averaged (``None`` before the first, so the
    caller falls back to cost). With a rate: the latest manual value on or before ``on`` is a new base that keeps growing from its date, plus
    interest on the lots bought after that date; with no manual value yet, interest on every lot."""
    if not rate_pct:
        return alt_value_on(values, on, mode)
    index = bisect_right(values, (on, Decimal("Infinity")))
    if index == 0:
        return interest_value(lots, on, rate_pct, interest_type)
    base_on, base = values[index - 1]
    later = [lot for lot in lots if lot[0] > base_on]
    return interest_value([(base_on, base)] + later, on, rate_pct, interest_type)


def position_value(units, price):
    """Units times price (``None`` when either is unknown)."""
    if price is None or units is None:
        return None
    return units * price
