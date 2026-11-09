"""The Dashboard figures (plan 5), computed once and cached (plan 26.4): valid while the profile's data and the prices are unchanged.

The payload is plain JSON (money as text so no float ever touches a rupee amount); `load` turns it back into Decimals."""
from datetime import date
from decimal import Decimal

from investments.services import core, holdings, performance, series, statscache

MONEY_FIELDS = ("units", "avg_cost", "price", "value", "gain", "awaiting", "cost")


def _row(h):
    return {"id": h.instrument.pk, "name": h.instrument.name, "kind": h.instrument.get_kind_display(), "kind_key": h.instrument.kind,
            "price_source": h.instrument.price_source, "units": str(h.units), "avg_cost": None if h.avg_cost is None else str(h.avg_cost),
            "price": None if h.price is None else str(h.price), "price_date": h.price_date.isoformat() if h.price_date else None,
            "value": str(h.value), "gain": str(h.gain), "gain_pct": h.gain_pct, "cost": str(h.cost), "awaiting": str(h.awaiting),
            "unpriced": h.unpriced, "xirr": h.xirr, "index_xirr": h.index_xirr, "alpha": h.alpha, "sect_xirr": h.sect_xirr,
            "sect_alpha": h.sect_alpha, "asset_class": h.instrument.get_asset_class_display()}


def compute(profile, portfolio=None, broker=None, as_of=None):
    as_of = as_of or date.today()
    settings_row = core.get_settings(profile, create=False)
    rows, totals = holdings.compute(profile, portfolio=portfolio, broker=broker, as_of=as_of, settings=settings_row)
    notes = performance.decorate_with_index(profile, rows, totals, as_of, settings_row)
    held = holdings.held(rows)
    chart = None
    if totals.flows:
        first = min(d for d, _ in totals.flows)
        if first < as_of:
            days = series.sample_dates(first, as_of)
            values, flows = series.portfolio_value_series(profile, days, portfolio=portfolio, broker=broker, settings_row=settings_row)
            index = performance._default_index(profile, settings_row)
            levels = series.sampled_prices(index, days) if index else [None] * len(days)
            equivalent = series.index_equivalent_values(days, flows, levels)
            chart = {"days": [d.isoformat() for d in days], "lines": [["Portfolio value", [float(v) for v in values]],
                                                                    [f"Same money in {index.name if index else 'the index'}", [None if v is None else float(v) for v in equivalent]]]}
    return {
        "rows": [_row(h) for h in held], "has_any": bool(rows),
        "totals": {"invested": str(totals.invested), "value": str(totals.value), "gain": str(totals.gain), "gain_pct": totals.gain_pct,
                   "xirr": totals.xirr, "index_xirr": totals.index_xirr, "alpha": totals.alpha, "count": totals.count},
        "allocation": [[label, str(value), share] for label, value, share in holdings.allocation(held)], "notes": notes, "chart": chart,
    }


def load(profile, portfolio=None, broker=None, as_of=None):
    as_of = as_of or date.today()
    payload = statscache.get_or_compute(profile, "dashboard", {"p": portfolio, "b": broker, "a": as_of},
                                        lambda: compute(profile, portfolio, broker, as_of), today_sensitive=True)
    for row in payload["rows"]:
        for key in MONEY_FIELDS:
            if row.get(key) is not None:
                row[key] = Decimal(row[key])
        row["price_date"] = date.fromisoformat(row["price_date"]) if row["price_date"] else None
    for key in ("invested", "value", "gain"):
        payload["totals"][key] = Decimal(payload["totals"][key])
    payload["allocation"] = [(label, Decimal(value), share) for label, value, share in payload["allocation"]]
    return payload
