"""The extra figures on one investment's page (plan 10): purchase by purchase against the index, sold portions, a past date's price and value,
the 52-week range, days until each purchase turns long-term, and the price chart with purchases and sales marked."""
from datetime import date, timedelta
from decimal import Decimal

from investments import lots
from investments.models import Guardrail
from investments.services import core, masters, prices, series
from investments.services.performance import IndexSeries
from investments.svgchart import line_chart

ZERO = Decimal(0)


def _annualised(start_value, end_value, days):
    """CAGR for a year or more, plain percentage return for less (plan 10)."""
    if not start_value or start_value <= 0 or days <= 0:
        return None, False
    ratio = float(end_value / start_value)
    if days < 365:
        return ratio - 1.0, False
    return ratio ** (365.0 / days) - 1.0, True


def purchase_rows(profile, instrument, holding, as_of):
    """``(held, sold)``: each lot still held with its gain and CAGR next to the index CAGR over the same dates, and each sold portion."""
    settings_row = core.get_settings(profile, create=False)
    index = settings_row.default_index if settings_row.default_index_id else masters.default_index_for(profile)
    lots_held = sorted(holding.lots, key=lambda l: (l.bought_on, str(l.ref)))
    first = min([l.paid_on for l in lots_held] + [as_of])
    level = IndexSeries(index, first, as_of).level if index else (lambda d: None)
    now_level = level(as_of)
    price = holding.price
    held = []
    for lot in lots_held:
        value = lot.units * price if price else None
        days = (as_of - lot.bought_on).days
        ret, annual = _annualised(lot.cost, value, days) if value is not None else (None, False)
        then = level(lot.paid_on)
        iret, _ = _annualised(then, now_level, days) if then and now_level else (None, False)
        held.append({"lot": lot, "value": value, "gain": None if value is None else value - lot.cost, "days": days, "return": ret, "annual": annual,
                     "index_return": iret, "diff": None if ret is None or iret is None else ret - iret,
                     "to_long": max(0, settings_row.long_term_days - days + 1) if days <= settings_row.long_term_days else 0})
    sold = []
    result = lots.replay(core.events_for(profile, instrument.pk), as_of=as_of)
    for m in result.matches:
        ret, annual = _annualised(m.cost, m.proceeds, m.holding_days)
        sold.append({"m": m, "return": ret, "annual": annual})
    return held, sold


def range_52w(instrument, as_of):
    rows = prices.series(instrument, as_of - timedelta(days=365), as_of)
    if not rows:
        return None, None
    closes = [c for _d, c in rows]
    return min(closes), max(closes)


def price_chart(profile, instrument, start, end):
    days = series.sample_dates(start, end)
    raw = series.sampled_prices(instrument, days)
    if not any(raw):
        return None
    from investments.models import Transaction

    markers = []
    for t in Transaction.objects.filter(profile=profile, instrument=instrument, status="final", date__range=(start, end)):
        markers.append((t.date, f"{t.get_side_display()} {t.units.normalize():f} at {t.price.normalize():f} on {t.date:%-d %b %Y}", "buy" if t.side == "buy" else "sell"))
    return line_chart(days, [(instrument.name, [None if p is None else float(p) for p in raw])], height=220, markers=markers)


def guardrails(profile, instrument):
    return Guardrail.objects.filter(profile=profile, instrument=instrument).select_related("portfolio")


__all__ = ["purchase_rows", "range_52w", "price_chart", "guardrails", "ZERO", "date"]


def foreign_figures(profile, instrument, holding, as_of):
    """Gain and return in the investment's own currency next to rupees, and the difference: the currency effect (plan 22)."""
    from investments.models import STATUS_FINAL, Transaction
    from investments.services import fx

    if instrument.currency == "INR":
        return None
    events = []
    for t in Transaction.objects.filter(profile=profile, instrument=instrument, status=STATUS_FINAL, units__isnull=False, date__lte=as_of):
        local = t.units * t.price + (t.charges if t.side == "buy" else -t.charges)
        kind = lots.BUY if t.side == "buy" else lots.SELL
        events.append(lots.Event(kind, t.effective_date if t.side == "buy" else t.date, t.units, core.bucket_of(t), ("txn", t.pk), local, order=t.pk))
    result = lots.replay(events)
    local_cost = result.cost()
    local_value = (holding.units * holding.price) if holding.price else None
    rate = fx.rate_on(instrument.currency, as_of)
    local_gain = None if local_value is None else local_value - local_cost
    local_pct = float(local_gain / local_cost) if local_gain is not None and local_cost else None
    rupee_pct = holding.gain_pct
    return {"currency": instrument.currency, "local_value": local_value, "local_cost": local_cost, "local_gain": local_gain, "local_pct": local_pct,
            "rupee_pct": rupee_pct, "effect": None if local_pct is None or rupee_pct is None else rupee_pct - local_pct,
            "rate": rate[1] if rate else None, "rate_date": rate[0] if rate else None}


def sip_schedules(profile, instrument):
    from investments.models import SipSchedule

    return SipSchedule.objects.filter(profile=profile, instrument=instrument).select_related("portfolio", "broker", "folio")
