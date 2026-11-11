"""The one value-against-the-index chart shared by the Overview and each investment's page, and its period choice.

Both pages show the same two lines (the value, and the same money put into the index) and the same period buttons
(``?range=1m|3m|6m|1y|3y|5y|all``, plain links, no page script). The value at the start of a period counts as money put in on that
day, as the Overview's period figures do."""
from datetime import timedelta

from investments.models import Transaction
from investments.services import series
from investments.svgchart import line_chart

#: (key, label, days back from the as-of date; None = from the first purchase).
PERIODS = (("1m", "1M", 30), ("3m", "3M", 92), ("6m", "6M", 183), ("1y", "1Y", 365), ("3y", "3Y", 1096), ("5y", "5Y", 1825), ("all", "All", None))


def choose(request, default="1y"):
    """The chosen period key and its length in days (None = all). ``?range=`` wins; the older ``?days=N`` still works."""
    key = request.GET.get("range", "")
    for k, _label, days in PERIODS:
        if k == key:
            return k, days
    raw = request.GET.get("days", "")
    if raw.isdigit() and int(raw) > 0:
        days = int(raw)
        return next((k for k, _l, d in PERIODS if d == days), ""), days
    return next((k, d) for k, _l, d in PERIODS if k == default)


def query_with(request, key):
    """The page's query string with ``range`` set to ``key`` (other choices such as ``?on=`` and ``?div=`` are kept)."""
    query = request.GET.copy()
    query.pop("days", None)
    query["range"] = key
    return query.urlencode()


def links(request, chosen, anchor=""):
    """The period buttons for the template: ``[{"key", "label", "on", "href"}]``."""
    return [{"key": k, "label": label, "on": k == chosen, "href": "?" + query_with(request, k) + anchor} for k, label, _d in PERIODS]


def markers_for(profile, instrument, start, end):
    """Purchases and sales as chart markers: ``[(date, label, "buy" or "sell")]``."""
    out = []
    for t in Transaction.objects.filter(profile=profile, instrument=instrument, status="final", date__range=(start, end)):
        out.append((t.date, f"{t.get_side_display()} {t.units.normalize():f} at {t.price.normalize():f} on {t.date:%-d %b %Y}",
                    "buy" if t.side == "buy" else "sell"))
    return out


def first_date(profile, *, portfolio=None, broker=None, instrument_ids=None):
    from django.db.models import Min

    qs = Transaction.objects.filter(profile=profile)
    if portfolio:
        qs = qs.filter(portfolio_id=portfolio)
    if broker:
        qs = qs.filter(broker_id=broker)
    if instrument_ids is not None:
        qs = qs.filter(instrument_id__in=list(instrument_ids))
    return qs.aggregate(m=Min("date"))["m"]


def value_chart(profile, days_back, end, *, index=None, portfolio=None, broker=None, instrument_ids=None, settings_row=None, markers=None, height=240):
    """The drawn chart (``svgchart.line_chart``) of the value and the same money in ``index`` over the last ``days_back`` days up to
    ``end`` (None = from the first purchase), or None when there is too little to draw."""
    first = first_date(profile, portfolio=portfolio, broker=broker, instrument_ids=instrument_ids)
    if first is None or first >= end:
        return None
    start = first if days_back is None else max(first, end - timedelta(days=days_back))
    days = series.sample_dates(start, end)
    values, flows = series.portfolio_value_series(profile, days, portfolio=portfolio, broker=broker, instrument_ids=instrument_ids,
                                                  settings_row=settings_row)
    if start > first:
        flows = list(flows)
        flows[0] = values[0]
    levels = series.sampled_prices(index, days) if index else [None] * len(days)
    equivalent = series.index_equivalent_values(days, flows, levels)
    name = index.name if index else "the index"
    return line_chart(days, [("Value", [float(v) for v in values]), (f"Same money in {name}", [None if v is None else float(v) for v in equivalent])],
                      height=height, markers=markers)
