"""Time series for charts and the Total Portfolio Value timeline (plan 9 "Charts", 12, 26.2 rule 6).

Long ranges are downsampled on the server: daily points up to three months, weekly up to three years, month-ends beyond, and never
more than `MAX_POINTS` points or `MAX_SERIES` lines. Prices are read one instrument at a time and sampled at once, so memory holds one
instrument's rows, never all prices.

* `portfolio_value_series`: the profile's value on each sample date (holdings at that date times the as-of price, alternative
  investments by the chosen treatment, awaiting purchases at cost). Dividends are never in it.
* `performance_index`: Chart A's portfolio line, rebased to 100, built so that money added or withdrawn does not cause jumps (each
  period's growth is (value at the end less money added in the period) over the value at the start: a time-weighted return).
* `price_lines`: Chart B and the index lines, each rebased to 100 on the first sample date it has a price.
"""
from bisect import bisect_right
from datetime import date, timedelta
from decimal import Decimal

from investments import valuation
from investments.models import (
    AWAITING_LEAVE_OUT, KIND_ALTERNATIVE, SIDE_BUY, STATUS_AWAITING, STATUS_FINAL, Instrument, Transaction, Transfer,
)
from investments.services import core, prices

ZERO = Decimal(0)
MAX_POINTS = 400
MAX_SERIES = 8


def sample_dates(start, end):
    """Daily up to 92 days, weekly (Fridays) up to three years, month-ends beyond; always ends on ``end``; capped at MAX_POINTS."""
    span = (end - start).days
    days = []
    if span <= 92:
        days = [start + timedelta(days=n) for n in range(span + 1)]
    elif span <= 3 * 366:
        d = start + timedelta(days=(4 - start.weekday()) % 7)
        days = [start] + [d + timedelta(weeks=n) for n in range((end - d).days // 7 + 1)]
    else:
        y, m = start.year, start.month
        days = [start]
        while True:
            nxt = date(y + (m // 12), m % 12 + 1, 1)
            last = nxt - timedelta(days=1)
            if last >= end:
                break
            if last > start:
                days.append(last)
            y, m = nxt.year, nxt.month
    if not days or days[-1] != end:
        days.append(end)
    days = sorted(set(d for d in days if start <= d <= end))
    if len(days) > MAX_POINTS:
        step = len(days) / MAX_POINTS
        days = sorted({days[int(i * step)] for i in range(MAX_POINTS)} | {days[-1]})
    return days


def sampled_prices(instrument, days):
    """``[price or None]`` at each of ``days`` (the last close on or before each), from one query."""
    if not days:
        return []
    series = prices.series(instrument, days[0], days[-1])
    before = prices.latest_prices([instrument.pk], days[0] - timedelta(days=1)).get(instrument.pk)
    if before:
        series = [before] + series          # the last close before the window answers its first days
    keys = [d for d, _ in series]
    out = []
    for d in days:
        i = bisect_right(keys, d)
        out.append(series[i - 1][1] if i else None)
    return out


def portfolio_value_series(profile, days, *, portfolio=None, broker=None, instrument_ids=None, settings_row=None):
    """``(values, flows)``: the portfolio value on each sample date and the net money put in during each period (period 0: up to days[0])."""
    settings_row = settings_row or core.get_settings(profile, create=False)
    leave_out = settings_row.awaiting_treatment == AWAITING_LEAVE_OUT
    qs = Transaction.objects.filter(profile=profile, date__lte=days[-1]).select_related("instrument")
    if portfolio:
        qs = qs.filter(portfolio_id=portfolio)
    if broker:
        qs = qs.filter(broker_id=broker)
    if instrument_ids is not None:
        qs = qs.filter(instrument_id__in=list(instrument_ids))
    by_inst, instruments, fx = {}, {}, {}
    for t in qs.iterator(chunk_size=500):
        by_inst.setdefault(t.instrument_id, []).append(t)
        instruments[t.instrument_id] = t.instrument
        if t.fx_rate:
            fx[t.instrument_id] = t.fx_rate
    moves = {}
    transfer_flows = []
    tq = Transfer.objects.filter(profile=profile, date__lte=days[-1])
    if instrument_ids is not None:
        tq = tq.filter(instrument_id__in=list(instrument_ids))
    for tr in tq:
        # a transfer moves units between buckets; with a portfolio or broker filter it moves them in or out of view
        out_of = (not portfolio or tr.from_portfolio_id == portfolio) and (not broker or tr.from_broker_id == broker)
        into = (not portfolio or tr.to_portfolio_id == portfolio) and (not broker or tr.to_broker_id == broker)
        if out_of != into:
            moves.setdefault(tr.instrument_id, []).append((tr.date, tr.units if into else -tr.units))
            instruments.setdefault(tr.instrument_id, tr.instrument)
            at = prices.latest_prices([tr.instrument_id], tr.date).get(tr.instrument_id)
            if at:
                transfer_flows.append((tr.date, tr.units * at[1] * (1 if into else -1)))
    values = [ZERO] * len(days)
    flows = [ZERO] * len(days)

    def period_of(day):
        return min(bisect_right(days, day - timedelta(days=1)), len(days) - 1) if day > days[0] else 0

    for day, amount in transfer_flows:
        flows[period_of(day)] += amount
    alt = prices.alt_values(profile, [i for i, inst in instruments.items() if inst.kind == KIND_ALTERNATIVE])
    from investments import corporate as corporate_math
    from investments.services import corporate as corporate_service

    applied = corporate_service.applied(profile, list(instruments))
    for iid, inst in instruments.items():
        events = []
        for t in by_inst.get(iid, []):
            if t.status == STATUS_AWAITING:
                if not leave_out and t.side == SIDE_BUY:
                    events.append((t.date, ZERO, t.amount or ZERO))       # at cost, no units
                    flows[period_of(t.date)] += t.amount or ZERO
                continue
            if t.status != STATUS_FINAL or t.units is None:
                continue
            sign = 1 if t.side == SIDE_BUY else -1
            events.append((t.effective_date if sign > 0 else t.date, sign * t.units, ZERO))
            amount = core.buy_total(t) if sign > 0 else -core.sell_total(t)
            flows[period_of(t.date)] += amount
        events += [(d, u, ZERO) for d, u in moves.get(iid, [])]
        actions = applied.get(iid, [])
        # a split or bonus multiplies the units held at the end of the day before (marked with units=None and the factor in the cost slot)
        events += [(ex, None, (Decimal(v) if kind == "split" else 1 + Decimal(v))) for _pk, kind, ex, v in actions]
        events.sort(key=lambda e: (e[0], 0 if e[1] is None else 1))
        if not events:
            continue
        sampled = None if inst.kind == KIND_ALTERNATIVE else sampled_prices(inst, days)
        rates = None
        if inst.currency != "INR":
            from investments.services import fx as fx_service

            rates = [r or fx.get(iid, Decimal(1)) for r in fx_service.sampled(inst.currency, days)]
        units, at_cost, k = ZERO, ZERO, 0
        cost_basis = {}
        for i, day in enumerate(days):
            while k < len(events) and events[k][0] <= day:
                if events[k][1] is None:
                    units *= events[k][2]
                else:
                    units += events[k][1]
                    at_cost += events[k][2]
                k += 1
            if inst.kind == KIND_ALTERNATIVE:
                v = valuation.alt_value_on(alt.get(iid, []), day, settings_row.alt_treatment) if units else ZERO
                if v is None:
                    v = cost_basis.setdefault("c", sum((core.buy_total(t) for t in by_inst.get(iid, []) if t.status == STATUS_FINAL and t.side == SIDE_BUY), ZERO))
                values[i] += (v if units > 0 else ZERO) + at_cost
            else:
                price = sampled[i]
                rate = rates[i] if rates else Decimal(1)
                factor = corporate_math.basis_factor(actions, day, inst.price_basis)
                values[i] += (units * factor * price * rate if price is not None and units > 0 else ZERO) + at_cost
    return values, flows


def performance_index(values, flows):
    """Rebased to 100 at the first sample date with a value; ``None`` until then. Flows in a period count as arriving at its start."""
    out, level, prev = [], None, None
    for value, flow in zip(values, flows):
        if level is None:
            if value > 0:
                level, prev = Decimal(100), value
                out.append(level)
            else:
                out.append(None)
            continue
        base = prev + flow
        if base > 0:
            level = level * (value / base)
        out.append(level)
        prev = value
    return out


def price_lines(instruments, days):
    """``[(instrument, [level or None])]`` rebased to 100 on each line's first priced sample date."""
    lines = []
    for inst in list(instruments)[:MAX_SERIES]:
        raw = sampled_prices(inst, days)
        base = next((p for p in raw if p), None)
        lines.append((inst, [(p / base * 100) if (p is not None and base) else None for p in raw]))
    return lines


def index_equivalent_values(days, flows, index_levels):
    """The same money put into the index: index units bought or sold with each period's flow at the level of that sample date."""
    units, out = Decimal(0), []
    for flow, level in zip(flows, index_levels):
        if level:
            units += flow / level
            out.append(units * level)
        else:
            out.append(None)
    return out


def downsampled(days, *lines):
    return days, lines


__all__ = ["sample_dates", "sampled_prices", "portfolio_value_series", "performance_index", "price_lines", "index_equivalent_values", "Instrument"]
