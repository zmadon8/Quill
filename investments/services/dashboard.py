"""The Dashboard figures (plan 5), computed once and cached (plan 26.4): valid while the profile's data and the prices are unchanged.

The payload is plain JSON (money as text so no float ever touches a rupee amount); `load` turns it back into Decimals."""
from datetime import date
from decimal import Decimal

from investments.services import core, holdings, overview, performance, series, statscache

MONEY_FIELDS = ("units", "avg_cost", "price", "value", "gain", "awaiting", "cost", "dividends")


def _row(h):
    return {"id": h.instrument.pk, "name": h.instrument.name, "kind": h.instrument.get_kind_display(), "kind_key": h.instrument.kind,
            "price_source": h.instrument.price_source, "units": str(h.units), "avg_cost": None if h.avg_cost is None else str(h.avg_cost),
            "price": None if h.price is None else str(h.price), "price_date": h.price_date.isoformat() if h.price_date else None,
            "value": str(h.value), "gain": str(h.gain), "gain_pct": h.gain_pct, "cost": str(h.cost), "awaiting": str(h.awaiting),
            "unpriced": h.unpriced, "xirr": h.xirr, "index_xirr": h.index_xirr, "alpha": h.alpha, "sect_xirr": h.sect_xirr,
            "sect_alpha": h.sect_alpha, "asset_class": h.instrument.get_asset_class_display(), "provisional": h.provisional, "blocked": h.blocked,
            "dividends": str(h.dividends)}


def compute(profile, portfolio=None, broker=None, as_of=None, include_dividends=None, period="all", with_chart=True):
    """The Overview figures as JSON-ready data. ``with_chart=False`` leaves out the whole-history chart (``chart`` is None) unless a chosen
    figure (time-weighted return, largest fall) needs the sampled value line anyway: the chart for "All" is then drawn on demand and kept in
    its own cache entry (``chartview.value_chart``), so a cold Overview does not walk the whole history twice."""
    as_of = as_of or date.today()
    settings_row = core.get_settings(profile, create=False)
    rows, totals = holdings.compute(profile, portfolio=portfolio, broker=broker, as_of=as_of, settings=settings_row, include_dividends=include_dividends)
    notes = performance.decorate_with_index(profile, rows, totals, as_of, settings_row)
    held = holdings.held(rows)
    chart = sample = None
    index = performance._default_index(profile, settings_row)
    chosen = overview.choice(settings_row)
    needs_sample = with_chart or bool({"twr", "drawdown"} & set(chosen["metrics"]))
    if totals.flows and needs_sample:
        first = min(d for d, _ in totals.flows)
        if first < as_of:
            days = series.sample_dates(first, as_of)
            values, flows = series.portfolio_value_series(profile, days, portfolio=portfolio, broker=broker, settings_row=settings_row)
            sample = (days, values, flows)
            levels = series.sampled_prices(index, days) if index else [None] * len(days)
            equivalent = series.index_equivalent_values(days, flows, levels)
            chart = {"days": [d.isoformat() for d in days], "lines": [["Portfolio value", [float(v) for v in values]],
                                                                    [f"Same money in {index.name if index else 'the index'}", [None if v is None else float(v) for v in equivalent]]]}
    payload = {
        "rows": [_row(h) for h in held], "has_any": bool(rows),
        "totals": {"invested": str(totals.invested), "value": str(totals.value), "gain": str(totals.gain), "gain_pct": totals.gain_pct,
                   "xirr": totals.xirr, "index_xirr": totals.index_xirr, "alpha": totals.alpha, "count": totals.count,
                   "dividends": str(totals.dividends), "provisional": totals.provisional, "blocked": totals.blocked},
        "allocation": [[label, str(value), share] for label, value, share in holdings.allocation(held)], "notes": notes, "chart": chart,
    }
    figures = overview.period_figures(profile, portfolio=portfolio, broker=broker, as_of=as_of, include_dividends=include_dividends,
                                      settings_row=settings_row, totals=totals, period_key=period, index=index)
    if figures is not None:
        payload["period_totals"] = {"gain": str(figures["gain"]), "gain_pct": figures["gain_pct"], "xirr": figures["xirr"],
                                    "index_xirr": figures["index_xirr"], "alpha": figures["alpha"], "start": figures["start"].isoformat()}
    del rows, held   # the period figures replay the holdings again at each period's start: do not keep two sets at once (memory)
    payload["overview"] = overview.compute(profile, portfolio=portfolio, broker=broker, as_of=as_of, include_dividends=include_dividends,
                                           settings_row=settings_row, totals=totals, chosen=chosen, sample=sample,
                                           index=index)
    return payload


def _params(profile, portfolio, broker, as_of, include_dividends, period="all"):
    chosen = overview.choice(core.get_settings(profile, create=False))
    params = {"p": portfolio, "b": broker, "a": as_of, "d": include_dividends, "o": [chosen["metrics"], chosen["periods"]]}
    if period != "all":   # the default keeps the cache key it always had
        params["r"] = period
    return params


def _with_period(totals, payload):
    """``totals`` with Gain, Gain %, XIRR, index XIRR and Alpha replaced by the period's figures when the payload has them."""
    period = payload.get("period_totals")
    if period:
        totals.update({k: period[k] for k in ("gain_pct", "xirr", "index_xirr", "alpha")})
        totals["gain"] = Decimal(period["gain"])
        totals["period_start"] = date.fromisoformat(period["start"])
    return totals


def peek_totals(profile, today=None, period="all"):
    """The Overview's totals for all portfolios today if they are already worked out (else None): value, invested, gain, xirr.
    The suite Home page uses this so that it never starts the full calculation."""
    today = today or date.today()
    settings_row = core.get_settings(profile, create=False)
    payload = statscache.peek(profile, "dashboard", _params(profile, None, None, today, settings_row.include_dividends, period), today=today)
    if not payload:
        return None
    totals = dict(payload["totals"])
    for key in ("invested", "value", "gain"):
        totals[key] = Decimal(totals[key])
    return _with_period(totals, payload)


def load(profile, portfolio=None, broker=None, as_of=None, include_dividends=None, period="all"):
    as_of = as_of or date.today()
    payload = statscache.get_or_compute(profile, "dashboard", _params(profile, portfolio, broker, as_of, include_dividends, period),
                                        lambda: compute(profile, portfolio, broker, as_of, include_dividends, period, with_chart=False),
                                        today_sensitive=True)
    for row in payload["rows"]:
        for key in MONEY_FIELDS:
            if row.get(key) is not None:
                row[key] = Decimal(row[key])
        row["price_date"] = date.fromisoformat(row["price_date"]) if row["price_date"] else None
    for key in ("invested", "value", "gain", "dividends"):
        payload["totals"][key] = Decimal(payload["totals"][key])
    if payload.get("period_totals"):
        payload["period_totals"]["gain"] = Decimal(payload["period_totals"]["gain"])
        payload["period_totals"]["start"] = date.fromisoformat(payload["period_totals"]["start"])
    payload["allocation"] = [(label, Decimal(value), share) for label, value, share in payload["allocation"]]
    payload["overview"] = overview.as_decimals(payload.get("overview") or {"periods": [], "rows": []})
    return payload
