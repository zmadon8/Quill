"""Alerts (plan 14). Worked out from daily prices, never live ones: after each price update and when a page is opened (cached).

Global rules (Settings): Rule A against the previous close (fall or rise in a day, and optionally a fall over a window), Rule B against
the cost of the units still held after FIFO sales, checked per portfolio. Guardrails on one investment in one portfolio: target gain,
stop-loss, price level, fall from peak since purchase; a guardrail replaces the global rules for that holding unless Settings says
otherwise. Purchases awaiting allotment have no units and are left out. Alternative investments only use their last entered value.
An alert can be dismissed (for the price date it was raised on), snoozed to a date, or re-armed at a new level. It is a prompt only.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from investments.models import KIND_ALTERNATIVE, AlertState, Guardrail, ManualPrice, Portfolio, Price
from investments.services import core, holdings, statscache

HUNDRED = Decimal(100)


@dataclass
class Alert:
    key: str
    kind: str              # rule_a, rule_a_window, rule_b, guardrail, maturity
    label: str
    instrument_id: int
    instrument_name: str
    portfolio_name: str
    on: date
    price: Decimal
    change_pct: float
    gain: Decimal = None
    gain_pct: float = None
    term: str = ""
    days_to_long: int = None
    rearm: Decimal = None


def _closes(instrument, on, back):
    """``[(date, close)]`` of the last stored closes on or before ``on`` going back ``back`` days, oldest first."""
    since = on - timedelta(days=back + 7)
    merged = dict(Price.objects.filter(instrument=instrument, date__range=(since, on)).values_list("date", "close"))
    merged.update(ManualPrice.objects.filter(instrument=instrument, date__range=(since, on)).values_list("date", "close"))
    return sorted(merged.items())


def _recent_closes(instrument_ids, on, back):
    """``{instrument id: [(date, close)]}`` like ``_closes`` for many investments at once: one query per price table."""
    since = on - timedelta(days=back + 7)
    merged = {}
    for model in (Price, ManualPrice):   # hand-entered second, so it wins a tie (D108)
        rows = model.objects.filter(instrument_id__in=instrument_ids, date__range=(since, on)).values_list("instrument_id", "date", "close")
        for iid, d, c in rows.iterator(chunk_size=2000):
            merged.setdefault(iid, {})[d] = c
    return {iid: sorted(m.items()) for iid, m in merged.items()}


def _term(h, settings_row, on):
    oldest = min((lot.bought_on for lot in h.lots), default=None)
    if oldest is None:
        return "", None
    held = (on - oldest).days
    if held > settings_row.long_term_days:
        return "long-term", 0
    return "short-term", settings_row.long_term_days - held + 1


def evaluate(profile, today=None):
    """Every alert that holds now (before dismissal and snoozes)."""
    today = today or date.today()
    s = core.get_settings(profile, create=False)
    out = []
    guards = {}
    for g in Guardrail.objects.filter(profile=profile, active=True).select_related("instrument", "portfolio"):
        guards.setdefault((g.instrument_id, g.portfolio_id), []).append(g)
    states = {st.key: st for st in AlertState.objects.filter(profile=profile)}
    window_days = max(2, s.rule_a_window_days)
    per_portfolio = [(portfolio, holdings.compute(profile, portfolio=portfolio.pk, as_of=today, settings=s)[0])
                     for portfolio in Portfolio.objects.filter(profile=profile)]
    held_ids = {h.instrument.pk for _p, rows in per_portfolio for h in rows
                if h.units > 0 and not h.unpriced and not h.blocked and h.instrument.kind != KIND_ALTERNATIVE}
    recent = _recent_closes(held_ids, today, window_days) if held_ids else {}
    for portfolio, rows in per_portfolio:
        for h in rows:
            if h.units <= 0 or h.unpriced or h.blocked:
                continue
            inst = h.instrument
            if inst.kind == KIND_ALTERNATIVE:
                price, on, previous = h.value, h.price_date or today, None
            else:
                closes = recent.get(inst.pk, [])
                if not closes:
                    continue
                on, price = closes[-1]
                previous = closes[-2][1] if len(closes) > 1 else None
            cost = h.cost_of_units
            gain = h.value - h.cost_of_units if cost else None
            gain_pct = float(gain / cost * HUNDRED) if cost else None
            term, to_long = _term(h, s, today)
            own = guards.get((inst.pk, portfolio.pk), [])

            def add(kind, label, change, rearm=None, key_extra=""):
                key = f"{kind}:{inst.pk}:{portfolio.pk}{key_extra}"
                st = states.get(key)
                if st and st.rearm_level is not None and rearm is not None and rearm < st.rearm_level:
                    return
                out.append(Alert(key, kind, label, inst.pk, inst.name, portfolio.name, on, price, change, gain, gain_pct, term, to_long, rearm))

            use_global = not (own and s.guardrail_replaces_global)
            if use_global and s.rule_a_enabled and previous and inst.kind != KIND_ALTERNATIVE:
                change = float((price - previous) / previous * HUNDRED)
                if change <= -float(s.rule_a_fall_pct):
                    add("rule_a", f"Fell {abs(change):.2f}% in a day", change)
                elif change >= float(s.rule_a_rise_pct):
                    add("rule_a", f"Rose {change:.2f}% in a day", change)
                if s.rule_a_window_fall_pct:
                    window = [c for d, c in closes if d <= on - timedelta(days=s.rule_a_window_days)]
                    if window:
                        wchange = float((price - window[-1]) / window[-1] * HUNDRED)
                        if wchange <= -float(s.rule_a_window_fall_pct):
                            add("rule_a_window", f"Fell {abs(wchange):.2f}% over {s.rule_a_window_days} days", wchange)
            if use_global and s.rule_b_enabled and gain_pct is not None:
                if gain_pct <= -float(s.rule_b_loss_pct):
                    add("rule_b", f"{abs(gain_pct):.2f}% below cost", gain_pct, rearm=Decimal(str(-gain_pct)))
                elif gain_pct >= float(s.rule_b_gain_pct):
                    add("rule_b", f"{gain_pct:.2f}% above cost", gain_pct, rearm=Decimal(str(gain_pct)))
            for g in own:
                v = g.value
                hit, label, measure = False, "", None
                if g.kind == "target_gain" and gain_pct is not None and gain_pct >= float(v):
                    hit, label, measure = True, f"Target gain of {v.normalize():f}% reached", Decimal(str(gain_pct))
                elif g.kind == "stop_loss" and gain_pct is not None and gain_pct <= -float(v):
                    hit, label, measure = True, f"Stop-loss: {abs(gain_pct):.2f}% below cost", Decimal(str(-gain_pct))
                elif g.kind == "price_above" and price >= v:
                    hit, label = True, f"Price at or above {v.normalize():f}"
                elif g.kind == "price_below" and price <= v:
                    hit, label = True, f"Price at or below {v.normalize():f}"
                elif g.kind == "fall_from_peak" and h.lots and inst.kind != KIND_ALTERNATIVE:
                    since = min(lot.bought_on for lot in h.lots)
                    peak = max((c for _d, c in _closes(inst, today, (today - since).days)), default=None)
                    if peak and (peak - price) / peak * HUNDRED >= v:
                        hit, label = True, f"{float((peak - price) / peak * HUNDRED):.2f}% below its peak since purchase"
                if hit:
                    add("guardrail", label, gain_pct or 0.0, rearm=measure, key_extra=f":{g.pk}")
    # maturity and renewal dates of alternative investments (plan 11)
    from investments.models import Instrument

    for inst in Instrument.objects.filter(profile=profile, maturity_date__isnull=False):
        days = (inst.maturity_date - today).days
        if 0 <= days <= s.maturity_alert_days:
            out.append(Alert(f"maturity:{inst.pk}:{inst.maturity_date}", "maturity", f"Matures in {days} day{'s' if days != 1 else ''} ({inst.maturity_date:%-d %b %Y})",
                             inst.pk, inst.name, "", today, Decimal(0), 0.0))
    return out


def visible(profile, today=None):
    """The alerts after dismissals and snoozes, cached until the data or the prices change (plan 26.4)."""
    today = today or date.today()

    def compute():
        return [a.__dict__ for a in evaluate(profile, today)]

    raw = statscache.get_or_compute(profile, "alerts", {}, compute, today_sensitive=True, today=today)
    states = {st.key: st for st in AlertState.objects.filter(profile=profile)}
    out = []
    for item in raw:
        st = states.get(item["key"])
        on = date.fromisoformat(str(item["on"]))
        if st and st.dismissed_on and st.dismissed_on >= on:
            continue
        if st and st.snoozed_until and st.snoozed_until >= today:
            continue
        item["on"] = on
        for key in ("price", "gain", "rearm"):
            if item.get(key) is not None:
                item[key] = Decimal(str(item[key]))
        out.append(item)
    return out


def count(profile):
    try:
        return len(visible(profile))
    except Exception:  # never let the badge break a page
        return 0


def act(profile, key, action, until=None, level=None, today=None):
    today = today or date.today()
    st, _ = AlertState.objects.get_or_create(profile=profile, key=key[:120])
    if action == "dismiss":
        st.dismissed_on = today
    elif action == "snooze":
        st.snoozed_until = until or today + timedelta(days=7)
    elif action == "rearm":
        st.rearm_level = Decimal(str(level)) if level not in (None, "") else None
        st.dismissed_on = today
    elif action == "reset":
        st.dismissed_on = st.snoozed_until = st.rearm_level = None
    st.save()
    return st
