"""The Overview's chosen figures (owner round 2026-11): the boxes at the top, and a table of figures for the whole history and the
last 5, 3 and 1 years. Chosen per profile in Overview > Customise (``InvestmentSettings.overview``); an empty choice is the standard one.

Every period figure uses the same portfolio, broker and as-at date as the rest of the Overview. A period's opening value counts as money
put in on its first day (as on the Performance page), so XIRR, the index comparison and the gain cover only that period. Figures from
the sampled value line (time-weighted return, largest fall) use the Overview's chart samples, so they are approximate for short periods
inside a long history. Only the periods and figures chosen are worked out; the result is cached with the rest of the Overview.
"""
from datetime import date, timedelta
from decimal import Decimal

ZERO = Decimal(0)

#: The boxes at the top: (id, label, help).
BOXES = (
    ("value", "Current value", ""),
    ("invested", "Invested", "cost of what is held now"),
    ("gain", "Gain", "current value less cost"),
    ("xirr", "Portfolio XIRR", "yearly return on money you put in"),
    ("index_xirr", "{index} XIRR", "same cash flows in the index"),
    ("alpha", "Alpha", "your XIRR less the index's"),
    ("dividends", "Dividends received", "not part of current value"),
    ("count", "Holdings", "investments held now"),
)
STANDARD_BOXES = ("invested", "value", "gain", "xirr", "index_xirr", "alpha")

#: The period figures: (id, label, format, help). Formats: pct, pct_signed, money, money_signed.
METRICS = (
    ("xirr", "Your XIRR", "pct", "Yearly return on the money you put in; the value at the start counts as money put in."),
    ("index_xirr", "{index} XIRR", "pct", "The same money on the same dates in the index."),
    ("alpha", "Alpha", "pct_signed", "Your XIRR less the index's."),
    ("twr", "Time-weighted return (yearly)", "pct", "The portfolio's growth whatever money was added or taken out; from sampled values."),
    ("index_return", "{index} change", "pct_signed", "The index's own rise or fall over the period."),
    ("start_value", "Value at the start", "money", ""),
    ("end_value", "Value at the end", "money", ""),
    ("put_in", "Money put in", "money", "Purchases, including charges."),
    ("taken_out", "Money taken out", "money", "Sales after charges (and dividends while they count in XIRR)."),
    ("fresh", "Fresh investments", "money_signed", "Money put in less money taken out."),
    ("gain", "Gain in the period", "money_signed", "Value at the end less value at the start less fresh investments."),
    ("dividends", "Dividends received", "money", ""),
    ("realised", "Gains booked on sales", "money_signed", "Gains on the units sold in the period, first in first out."),
    ("drawdown", "Largest fall", "pct", "The biggest fall from a high in the period; from sampled values."),
)
STANDARD_METRICS = ("xirr", "index_xirr", "alpha", "gain", "fresh")
PERIODS = (("all", "Since the start"), ("5", "5 years"), ("3", "3 years"), ("1", "1 year"))
STANDARD_PERIODS = ("all", "5", "3", "1")

_BOX_IDS = {b[0] for b in BOXES}
_METRIC_IDS = {m[0] for m in METRICS}
_PERIOD_IDS = {p[0] for p in PERIODS}


def choice(settings_row):
    """``{"boxes", "metrics", "periods"}`` in catalogue order: the profile's choice, or the standard one where it has none."""
    raw = (getattr(settings_row, "overview", None) or {}) if settings_row is not None else {}
    boxes = [b for b, _l, _h in BOXES if b in set(raw.get("boxes", STANDARD_BOXES))]
    metrics = [m for m, _l, _f, _h in METRICS if m in set(raw.get("metrics", STANDARD_METRICS))]
    periods = [p for p, _l in PERIODS if p in set(raw.get("periods", STANDARD_PERIODS))]
    return {"boxes": boxes, "metrics": metrics, "periods": periods}


def clean(boxes, metrics, periods):
    """The stored form of a choice (unknown ids dropped)."""
    return {"boxes": [b for b in boxes if b in _BOX_IDS], "metrics": [m for m in metrics if m in _METRIC_IDS],
            "periods": [p for p in periods if p in _PERIOD_IDS]}


def _years_back(day, years):
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def compute(profile, *, portfolio, broker, as_of, include_dividends, settings_row, totals, chosen, sample=None, index=None):
    """The period table as JSON-ready data: ``{"periods": [...], "rows": [...]}``; empty when nothing is chosen or nothing is held."""
    from investments import indexcmp, lots, xirr
    from investments.models import Dividend
    from investments.services import core, holdings, performance

    metrics, wanted = chosen["metrics"], chosen["periods"]
    if not metrics or not wanted or not totals.flows:
        return {"periods": [], "rows": []}
    first = min(d for d, _a in totals.flows)
    flows_all = sorted(totals.flows)
    series = performance.IndexSeries(index, first - timedelta(days=1), as_of) if index is not None else None
    realised = None
    if "realised" in metrics:
        realised = []
        for iid, events in core.events_by_instrument(profile).items():
            for m in lots.replay(events, as_of=as_of).matches:
                if m.bucket and ((portfolio and m.bucket.portfolio != portfolio) or (broker and m.bucket.broker != broker)):
                    continue
                realised.append((m.sold_on, m.gain))
    divs = Dividend.objects.filter(profile=profile, date__lte=as_of)
    if portfolio:
        divs = divs.filter(portfolio_id=portfolio)
    if broker:
        divs = divs.filter(broker_id=broker)
    divs = list(divs.values_list("date", "amount"))

    periods, columns = [], []
    for pid, label in PERIODS:
        if pid not in wanted:
            continue
        start = None if pid == "all" else _years_back(as_of, int(pid))
        short = start is not None and start <= first   # the history is shorter than the period: it is the whole history
        if short:
            start = None
        if start is None:
            opening, in_window = ZERO, flows_all
            day0 = first
        else:
            opening = holdings.compute(profile, portfolio=portfolio, broker=broker, as_of=start, settings=settings_row,
                                       include_dividends=include_dividends, with_xirr=False)[1].value
            in_window = [(d, a) for d, a in flows_all if d > start]
            day0 = start
        cash = ([(day0, -opening)] if opening else []) + in_window
        closing = totals.value
        put_in = -sum((a for _d, a in in_window if a < 0), ZERO)
        taken_out = sum((a for _d, a in in_window if a > 0), ZERO)
        fresh = put_in - taken_out
        col = {
            "start_value": opening, "end_value": closing, "put_in": put_in, "taken_out": taken_out, "fresh": fresh,
            "gain": closing - opening - fresh,
            "xirr": xirr.xirr([(d, float(a)) for d, a in cash] + [(as_of, float(closing))]) if cash else None,
            "dividends": sum((a for d, a in divs if start is None or d > start), ZERO),
        }
        if series is not None and cash:
            col["index_xirr"] = indexcmp.index_xirr(cash, series.level, as_of)
            a, b = series.level(day0), series.level(as_of)
            col["index_return"] = float(b / a) - 1.0 if a and b else None
        else:
            col["index_xirr"] = col["index_return"] = None
        col["alpha"] = indexcmp.alpha(col["xirr"], col["index_xirr"])
        if realised is not None:
            col["realised"] = sum((g for d, g in realised if start is None or d > start), ZERO)
        col["twr"], col["drawdown"] = _from_samples(sample, day0)
        periods.append({"id": pid, "label": label, "start": day0.isoformat(), "short": short})
        columns.append(col)

    names = {m[0]: m for m in METRICS}
    rows = []
    for mid in metrics:
        _id, label, fmt, help_text = names[mid]
        values = []
        for col in columns:
            v = col.get(mid)
            values.append(str(v) if isinstance(v, Decimal) else v)
        rows.append({"id": mid, "label": label.replace("{index}", index.name if index else "Index"), "fmt": fmt, "help": help_text, "values": values})
    return {"periods": periods, "rows": rows}


def _from_samples(sample, day0):
    """``(yearly time-weighted return, largest fall)`` from the Overview's sampled value line, from ``day0`` on."""
    from investments.services import performance, series

    if not sample:
        return None, None
    days, values, flows = sample
    i0 = next((i for i, d in enumerate(days) if d >= day0), None)
    if i0 is None or len(days) - i0 < 2:
        return None, None
    levels = [lv for lv in series.performance_index(values[i0:], [ZERO] + list(flows[i0 + 1:])) if lv is not None]
    if len(levels) < 2:
        return None, None
    first_day = next(d for d, v in zip(days[i0:], values[i0:]) if v > 0)
    twr = performance.growth_rate(levels[0], levels[-1], first_day, days[-1])
    peak, fall = levels[0], 0.0
    for lv in levels:
        peak = max(peak, lv)
        if peak > 0:
            fall = max(fall, float((peak - lv) / peak))
    return twr, fall


#: Days back from the as-at date for each period key (the same as the chart periods; None = from the first purchase).
PERIOD_DAYS = {"1m": 30, "3m": 92, "6m": 183, "1y": 365, "3y": 1096, "5y": 1825}


def period_figures(profile, *, portfolio, broker, as_of, include_dividends, settings_row, totals, period_key, index):
    """Gain, gain %, XIRR, index XIRR and Alpha over one chart-style period, or None for "all" (the totals already are that).

    Worked as in ``compute``: the value at the period's start counts as money put in on that day. If the history is shorter than the
    period, the whole history is used (the figures then equal the totals)."""
    from investments import indexcmp, xirr
    from investments.services import holdings, performance

    days = PERIOD_DAYS.get(period_key)
    if days is None or not totals.flows:
        return None
    flows_all = sorted(totals.flows)
    first = flows_all[0][0]
    start = as_of - timedelta(days=days)
    if start <= first:
        start = None
    if start is None:
        opening, day0, in_window = ZERO, first, flows_all
    else:
        opening = holdings.compute(profile, portfolio=portfolio, broker=broker, as_of=start, settings=settings_row,
                                   include_dividends=include_dividends, with_xirr=False)[1].value
        day0, in_window = start, [(d, a) for d, a in flows_all if d > start]
    cash = ([(day0, -opening)] if opening else []) + in_window
    closing = totals.value
    put_in = -sum((a for _d, a in in_window if a < 0), ZERO)
    taken_out = sum((a for _d, a in in_window if a > 0), ZERO)
    gain = closing - opening - (put_in - taken_out)
    base = opening + put_in
    own = xirr.xirr([(d, float(a)) for d, a in cash] + [(as_of, float(closing))]) if cash else None
    index_own = None
    if index is not None and cash:
        series = performance.IndexSeries(index, day0 - timedelta(days=1), as_of)
        index_own = indexcmp.index_xirr(cash, series.level, as_of)
    return {"gain": gain, "gain_pct": float(gain / base) if base > 0 else None, "xirr": own, "index_xirr": index_own,
            "alpha": indexcmp.alpha(own, index_own), "start": day0}


def as_decimals(table):
    """Turn the cached money values back into Decimals (formats money and money_signed)."""
    for row in table.get("rows", []):
        if row["fmt"].startswith("money"):
            row["values"] = [None if v is None else Decimal(v) for v in row["values"]]
    for p in table.get("periods", []):
        p["start"] = date.fromisoformat(p["start"])
    return table
