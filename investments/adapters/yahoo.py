"""Yahoo's chart endpoint, fetched directly (no `yfinance`, plan 15.6): daily closes, splits and dividends, and symbol search."""
import json
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from . import http
from .base import FetchError, Result, clean_close

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={p1}&period2={p2}&interval=1d&events=div%7Csplit"
SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search?q={q}&quotesCount=8&newsCount=0"


def parse_chart(body, since=None):
    """Turn a chart answer into a :class:`Result`. Raises :class:`FetchError` for an answer that is not usable."""
    try:
        data = json.loads(body)
        chart = data["chart"]
    except (ValueError, KeyError, TypeError) as exc:
        raise FetchError("Yahoo answered with something that is not price data.") from exc
    if chart.get("error"):
        raise FetchError(f"Yahoo: {chart['error'].get('description') or chart['error'].get('code')}")
    results = chart.get("result") or []
    if not results:
        raise FetchError("Yahoo has no data for this code.")
    item = results[0]
    meta = item.get("meta") or {}
    offset = int(meta.get("gmtoffset") or 0)
    stamps = item.get("timestamp") or []
    closes = ((item.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    out = Result(name=meta.get("longName") or meta.get("shortName") or "", currency=meta.get("currency") or "",
                 exchange=meta.get("exchangeName") or meta.get("fullExchangeName") or "")
    seen = {}
    for stamp, close in zip(stamps, closes):
        # The exchange's own date: UTC time plus the exchange's offset.
        day = (datetime.fromtimestamp(int(stamp), tz=timezone.utc) + timedelta(seconds=offset)).date()
        if since is not None and day < since:
            continue
        value = clean_close(close)
        if value is None:
            out.rejected += 1
            continue
        seen[day] = value.quantize(Decimal("0.0001"))
    out.rows = sorted(seen.items())
    events = item.get("events") or {}
    for ev in (events.get("splits") or {}).values():
        try:
            day = (datetime.fromtimestamp(int(ev["date"]), tz=timezone.utc) + timedelta(seconds=offset)).date()
            out.splits.append((day, Decimal(str(ev["numerator"])), Decimal(str(ev["denominator"]))))
        except (KeyError, ValueError, ArithmeticError):
            continue
    for ev in (events.get("dividends") or {}).values():
        try:
            day = (datetime.fromtimestamp(int(ev["date"]), tz=timezone.utc) + timedelta(seconds=offset)).date()
            out.dividends.append((day, Decimal(str(ev["amount"]))))
        except (KeyError, ValueError, ArithmeticError):
            continue
    out.splits.sort()
    out.dividends.sort()
    return out


def fetch(symbol, since=None, years=10, today=None):
    """Daily closes since ``since`` (default: ``years`` years back). Retries as in plan 15.2."""
    today = today or date.today()
    start = (since - timedelta(days=5)) if since else today - timedelta(days=365 * years)
    p1 = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(today.year, today.month, today.day, tzinfo=timezone.utc).timestamp()) + 2 * 86400
    url = CHART_URL.format(symbol=urllib.parse.quote(symbol, safe="^.-="), p1=p1, p2=p2)
    body = http.with_retry(lambda: http.get(url))
    return parse_chart(body, since)


def search(query):
    """Symbol search: ``[{symbol, name, exchange, type}]``. A failure is an empty list plus the error text (the page then lets the person type the code)."""
    url = SEARCH_URL.format(q=urllib.parse.quote(query))
    body = http.with_retry(lambda: http.get(url), tries=2)
    try:
        quotes = json.loads(body).get("quotes") or []
    except (ValueError, AttributeError) as exc:
        raise FetchError("Yahoo's search answer was not readable.") from exc
    return [{"symbol": q.get("symbol", ""), "name": q.get("longname") or q.get("shortname") or "", "exchange": q.get("exchDisp") or q.get("exchange") or "",
             "type": q.get("quoteType", "")} for q in quotes if q.get("symbol")]
