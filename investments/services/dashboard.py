"""The Dashboard figures (plan 5), computed once and cached (plan 26.4): valid while the profile's data and the prices are unchanged.

The payload is plain JSON (money as text so no float ever touches a rupee amount); `load` turns it back into Decimals."""
from datetime import date
from decimal import Decimal

from investments.services import chartview, core, holdings, overview, performance, series, statscache

#: Bump when the cached payload gains or changes a part, so older cached payloads are not read (2: the Type/Portfolio/Broker breakdown; 3: its XIRR column; 4: the buy and sell markers of the chart).
PAYLOAD_VERSION = 4
MONEY_FIELDS = ("units", "avg_cost", "price", "value", "gain", "awaiting", "cost", "dividends")


def _row(h):
    return {"id": h.instrument.pk, "name": h.instrument.name, "kind": h.instrument.get_kind_display(), "kind_key": h.instrument.kind,
            "price_source": h.instrument.price_source, "units": str(h.units), "avg_cost": None if h.avg_cost is None else str(h.avg_cost),
            "price": None if h.price is None else str(h.price), "price_date": h.price_date.isoformat() if h.price_date else None,
            "value": str(h.value), "gain": str(h.gain), "gain_pct": h.gain_pct, "cost": str(h.cost), "awaiting": str(h.awaiting),
            "unpriced": h.unpriced, "xirr": h.xirr, "index_xirr": h.index_xirr, "alpha": h.alpha, "sect_xirr": h.sect_xirr,
            "sect_alpha": h.sect_alpha, "asset_class": h.instrument.get_asset_class_display(), "provisional": h.provisional, "blocked": h.blocked,
            "dividends": str(h.dividends)}


BREAKDOWNS = (("type", "by Type"), ("portfolio", "by Portfolio"), ("broker", "by Broker"))
_CENT = Decimal("0.01")
AWAITING_LABEL = "Awaiting allotment"


def _group_xirrs(profile, rows, totals, ctx):
    """``{key: {label: xirr}}`` for each way of grouping, from the cash flows of the group (dividends as the holdings count them) and the
    group's value today as the last flow. By Type it uses the flows already on the holdings; by Portfolio and Broker each group is worked
    out once with the same holdings calculation, so the figure follows the include-dividends switch exactly as the cards do. Worked out when
    the payload is made, never when it is shown."""
    from investments import xirr
    from investments.models import Broker, Portfolio

    out = {"type": {}, "portfolio": {}, "broker": {}}
    by_kind = {}
    for h in rows:
        if h.blocked:
            continue
        cell = by_kind.setdefault(h.instrument.get_kind_display(), [[], Decimal(0)])
        cell[0].extend(h.flows)
        cell[1] += h.value
    for label, (flows, value) in by_kind.items():
        out["type"][label] = xirr.xirr([(d, float(a)) for d, a in flows] + [(ctx["as_of"], float(value))]) if flows else None
    for key, model in (("portfolio", Portfolio), ("broker", Broker)):
        for pk, name in model.objects.filter(profile=profile).values_list("pk", "name"):
            if ctx.get(key) not in (None, pk):
                continue
            kw = {"portfolio": ctx.get("portfolio"), "broker": ctx.get("broker")}
            kw[key] = pk
            _rows, t = holdings.compute(profile, as_of=ctx["as_of"], settings=ctx["settings"], include_dividends=ctx["include_dividends"],
                                        history=ctx["history"], **kw)
            out[key][name] = t.xirr
    return out


def _breakdowns(profile, held, rows=None, totals=None, ctx=None):
    """Invested, value, gain, gain % and share of the total for each group, three ways (by Type, Portfolio and Broker), as JSON-ready data:
    ``{key: {"rows": [...], "total": {...}}}``. Money is text quantized to 0.01. Units held are shared out by lot: a holding's value is split
    over its lots by units (a purchase awaiting allotment has no lot and is a group of its own), so every way adds up to the Overview's value.
    A holding blocked by a pending corporate action is left out, as it is from the totals."""
    from investments.models import Broker, Portfolio

    names = {"portfolio": dict(Portfolio.objects.filter(profile=profile).values_list("pk", "name")),
             "broker": dict(Broker.objects.filter(profile=profile).values_list("pk", "name"))}
    groups = {key: {} for key, _l in BREAKDOWNS}

    def add(key, label, invested, value):
        cell = groups[key].setdefault(label, [Decimal(0), Decimal(0)])
        cell[0] += invested
        cell[1] += value

    for h in held:
        if h.blocked:
            continue
        add("type", h.instrument.get_kind_display(), h.cost, h.value)
        units = sum((lot.units for lot in h.lots), Decimal(0))
        shared = h.value - h.awaiting
        for lot in h.lots:
            part = shared * lot.units / units if units else Decimal(0)
            add("portfolio", names["portfolio"].get(lot.bucket.portfolio, "Unknown"), lot.cost, part)
            add("broker", names["broker"].get(lot.bucket.broker, "Unknown"), lot.cost, part)
        if h.awaiting:
            add("portfolio", AWAITING_LABEL, h.awaiting, h.awaiting)
            add("broker", AWAITING_LABEL, h.awaiting, h.awaiting)

    xirrs = _group_xirrs(profile, rows, totals, ctx) if ctx is not None else {}

    def figures(label, invested, value, total_value, own=None):
        invested, value = invested.quantize(_CENT), value.quantize(_CENT)
        gain = value - invested
        return {"name": label, "xirr": own, "invested": str(invested), "value": str(value), "gain": str(gain),
                "gain_pct": float(gain / invested) if invested else None, "share": float(value / total_value) if total_value else 0.0}

    out = {}
    for key, _l in BREAKDOWNS:
        total_value = sum((v for _i, v in groups[key].values()), Decimal(0))
        ordered = sorted(groups[key].items(), key=lambda kv: (-kv[1][1], kv[0]))
        rows_out = [figures(label, i, v, total_value, xirrs.get(key, {}).get(label)) for label, (i, v) in ordered]
        # The Total is the sum of the rows as shown, so the rows always add up to it to the paisa.
        total = figures("Total", sum((i.quantize(_CENT) for i, _v in groups[key].values()), Decimal(0)),
                        sum((v.quantize(_CENT) for _i, v in groups[key].values()), Decimal(0)), total_value,
                        totals.xirr if totals is not None else None)
        out[key] = {"rows": rows_out, "total": total}
    return out


def _decode_breakdowns(payload):
    """The cached breakdowns with money back as Decimals (payloads kept before the breakdowns existed have none)."""
    data = payload.get("breakdown") or {}
    for table in data.values():
        for row in table["rows"] + [table["total"]]:
            for k in ("invested", "value", "gain"):
                if isinstance(row[k], str):
                    row[k] = Decimal(row[k])
    payload["breakdown"] = data


def compute(profile, portfolio=None, broker=None, as_of=None, include_dividends=None, period="all", with_chart=True):
    """The Overview figures as JSON-ready data. ``with_chart=False`` leaves out the whole-history chart (``chart`` is None) unless a chosen
    figure (time-weighted return, largest fall) needs the sampled value line anyway: the chart for "All" is then drawn on demand and kept in
    its own cache entry (``chartview.value_chart``), so a cold Overview does not walk the whole history twice."""
    as_of = as_of or date.today()
    settings_row = core.get_settings(profile, create=False)
    # The transactions are read once and shared by the holdings today and by each period's opening value (they used to be read, and every
    # row turned into a model object, once for each of up to five calculations).
    history = holdings.load_history(profile, as_of)
    memo = {}
    rows, totals = holdings.compute(profile, portfolio=portfolio, broker=broker, as_of=as_of, settings=settings_row, include_dividends=include_dividends,
                                    history=history)
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
                                                                    [f"Same money in {index.name if index else 'the index'}", [None if v is None else float(v) for v in equivalent]]],
                     "markers": chartview.portfolio_markers(profile, days, portfolio=portfolio, broker=broker)}
    payload = {
        "rows": [_row(h) for h in held], "has_any": bool(rows),
        "totals": {"invested": str(totals.invested), "value": str(totals.value), "gain": str(totals.gain), "gain_pct": totals.gain_pct,
                   "xirr": totals.xirr, "index_xirr": totals.index_xirr, "alpha": totals.alpha, "count": totals.count,
                   "dividends": str(totals.dividends), "provisional": totals.provisional, "blocked": totals.blocked},
        "allocation": [[label, str(value), share] for label, value, share in holdings.allocation(held)], "notes": notes, "chart": chart,
        "breakdown": _breakdowns(profile, held, rows, totals, {
            "as_of": as_of, "settings": settings_row, "include_dividends": include_dividends, "history": history,
            "portfolio": portfolio, "broker": broker}),
    }
    figures = overview.period_figures(profile, portfolio=portfolio, broker=broker, as_of=as_of, include_dividends=include_dividends,
                                      settings_row=settings_row, totals=totals, period_key=period, index=index, history=history, memo=memo)
    if figures is not None:
        payload["period_totals"] = {"gain": str(figures["gain"]), "gain_pct": figures["gain_pct"], "xirr": figures["xirr"],
                                    "index_xirr": figures["index_xirr"], "alpha": figures["alpha"], "start": figures["start"].isoformat()}
    # Purchases turning long-term soon, for the insights: only for the plain view (all portfolios and brokers, today), which is what they use.
    payload["turning"] = _turning_long(rows, settings_row, as_of) if portfolio is None and broker is None and as_of == date.today() else None
    del rows, held   # the period figures replay the holdings again at each period's start: do not keep two sets at once (memory)
    payload["overview"] = overview.compute(profile, portfolio=portfolio, broker=broker, as_of=as_of, include_dividends=include_dividends,
                                           settings_row=settings_row, totals=totals, chosen=chosen, sample=sample,
                                           index=index, history=history, memo=memo)
    return payload


def _turning_long(rows, settings_row, today, days=60):
    """``[[investment name, date it turns long-term, days left]]`` for the lots that turn long-term within ``days`` days, soonest first (the same
    lots and order as ``reports.turning_long``)."""
    from datetime import timedelta

    out = []
    for h in rows:
        for lot in h.lots:
            turns = lot.bought_on + timedelta(days=settings_row.long_term_days + 1)
            left = (turns - today).days
            if 0 < left <= days:
                out.append([h.instrument.name, turns.isoformat(), left])
    out.sort(key=lambda r: r[2])
    return out


def _params(profile, portfolio, broker, as_of, include_dividends, period="all"):
    chosen = overview.choice(core.get_settings(profile, create=False))
    params = {"p": portfolio, "b": broker, "a": as_of, "d": include_dividends, "o": [chosen["metrics"], chosen["periods"]],
              "v": PAYLOAD_VERSION}
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


def peek_payload(profile, today=None, period="all"):
    """The Overview's whole cached payload for all portfolios today, decoded like :func:`load` does, if it is already worked out (else None).
    The suite Home page uses this so that it never starts the calculation."""
    today = today or date.today()
    settings_row = core.get_settings(profile, create=False)
    payload = statscache.peek(profile, "dashboard", _params(profile, None, None, today, settings_row.include_dividends, period), today=today)
    if not payload:
        return None
    for key in ("invested", "value", "gain", "dividends"):
        payload["totals"][key] = Decimal(payload["totals"][key])
    if payload.get("period_totals"):
        payload["totals"].update({k: payload["period_totals"][k] for k in ("gain_pct", "xirr", "index_xirr", "alpha")})
        payload["totals"]["gain"] = Decimal(payload["period_totals"]["gain"])
    payload["allocation"] = [(label, Decimal(value), share) for label, value, share in payload["allocation"]]
    payload["overview"] = overview.as_decimals(payload.get("overview") or {"periods": [], "rows": []})
    _decode_breakdowns(payload)
    return payload


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
    _decode_breakdowns(payload)
    return payload
