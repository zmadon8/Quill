"""XIRR (plan sections 9 and 16.5). Pure Python, floats (the plan keeps money as Decimal and XIRR itself as floats).

``xirr(flows)`` takes ``[(date, amount), ...]`` where money paid in is negative and money received (sale proceeds, and the
closing value counted as received today) is positive. It returns a yearly rate as a fraction (0.12 is 12 percent), or
``None`` when there is no answer: fewer than two flows, all flows the same sign, a total period shorter than
``MIN_DAYS`` (too short to annualise, proposed default 30 days), or no root in -0.99 to 10 (a loss of 99 percent to a
gain of 1,000 percent).
"""
from datetime import date

MIN_DAYS = 30
LOW, HIGH = -0.99, 10.0
_DAYS = 365.0


def _npv_t(rate, times, amounts):
    return sum(amount / (1.0 + rate) ** t for t, amount in zip(times, amounts))


def _npv_and_slope(rate, times, amounts):
    """The value and its slope at ``rate`` from one power per flow (the slope needs the same power, one step further)."""
    base = 1.0 + rate
    value = slope = 0.0
    for t, amount in zip(times, amounts):
        grown = base ** t
        value += amount / grown
        slope -= t * amount / (grown * base)
    return value, slope


def xirr(flows, min_days=MIN_DAYS):
    flows = [(d, float(a)) for d, a in flows if a]
    if len(flows) < 2:
        return None
    flows.sort(key=lambda f: f[0])
    t0 = flows[0][0]
    if (flows[-1][0] - t0).days < min_days:
        return None
    if not any(a < 0 for _, a in flows) or not any(a > 0 for _, a in flows):
        return None
    # Money on the same day is one flow as far as the answer goes (the value is a sum), and the year fractions do not change between
    # iterations: work both out once. A portfolio has thousands of flows but far fewer distinct days.
    by_day = {}
    for when, amount in flows:
        by_day[when] = by_day.get(when, 0.0) + amount
    times = [(when - t0).days / _DAYS for when in by_day]
    amounts = list(by_day.values())
    f_low, f_high = _npv_t(LOW, times, amounts), _npv_t(HIGH, times, amounts)
    if f_low == 0:
        return LOW
    if f_high == 0:
        return HIGH
    if (f_low > 0) == (f_high > 0):
        return None  # no sign change, so no root in range
    # Newton from a sensible start, kept inside the bracket; bisection takes over when Newton leaves it.
    rate = 0.1
    lo, hi = LOW, HIGH
    for _ in range(60):
        value, slope = _npv_and_slope(rate, times, amounts)
        if abs(value) < 1e-9:
            return rate
        if (value > 0) == (f_low > 0):
            lo = rate
        else:
            hi = rate
        step = rate - value / slope if slope else None
        rate = step if step is not None and lo < step < hi else (lo + hi) / 2.0
    for _ in range(200):  # bisection fallback
        mid = (lo + hi) / 2.0
        value = _npv_t(mid, times, amounts)
        if abs(value) < 1e-9 or (hi - lo) < 1e-12:
            return mid
        if (value > 0) == (f_low > 0):
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def simple_return(cost, value):
    """Plain percentage return as a fraction, for periods under a year (None when there was no cost)."""
    cost = float(cost)
    return (float(value) - cost) / cost if cost else None


def as_of_date(value):
    """A ``date`` from a date or an ISO ``YYYY-MM-DD`` string (helper for callers)."""
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
