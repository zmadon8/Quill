"""Yahoo's chart endpoint, fetched directly (no `yfinance`, plan 15.6): daily closes, splits and dividends, and symbol search."""
import json
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from investments.services import source_formats

from . import http
from .base import FetchError, FormatError, Result, clean_close

CHART_URL = source_formats.DEFAULTS["yahoo"]["url"]
SEARCH_URL = source_formats.DEFAULTS["yahoo"]["search_url"]


def _dotted(path):
    return ".".join(str(s) for s in path)


def parse_chart(body, since=None, fmt=None):
    """Turn a chart answer into a :class:`Result`. Raises :class:`FetchError` for an answer that is not usable. Where the fields are in the
    answer is the format ``yahoo`` of ``services/source_formats.py`` (the paths of the prices; splits and dividends are read as before)."""
    fmt = fmt or source_formats.get("yahoo")
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise FetchError("Yahoo answered with something that is not price data.") from exc
    if not isinstance(data, dict) or (source_formats.dig(data, fmt["results_path"][:1]) is None and source_formats.dig(data, fmt["error_path"][:1]) is None):
        raise FormatError(f"Yahoo answered with something that is not price data (nothing at '{_dotted(fmt['results_path'])}').", key="yahoo")
    error = source_formats.dig(data, fmt["error_path"])
    if error:
        raise FetchError(f"Yahoo: {(error.get('description') or error.get('code')) if isinstance(error, dict) else error}")
    results = source_formats.dig(data, fmt["results_path"]) or []
    if not isinstance(results, list) or not results:
        raise FetchError("Yahoo has no data for this code.")
    item = results[0]
    offset = int(source_formats.dig(item, fmt["gmtoffset_path"]) or 0)
    stamps = source_formats.dig(item, fmt["timestamps_path"]) or []
    closes = source_formats.dig(item, fmt["closes_path"])
    if stamps and closes is None:
        raise FormatError(f"Yahoo: there are dates but no closes at '{_dotted(fmt['closes_path'])}'; Yahoo may have changed its answer.", key="yahoo")
    closes = closes or []
    get = source_formats.dig
    out = Result(name=get(item, fmt["name_path"]) or get(item, fmt["name_alt_path"]) or "", currency=get(item, fmt["currency_path"]) or "",
                 exchange=get(item, fmt["exchange_path"]) or get(item, fmt["exchange_alt_path"]) or "")
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
    fmt = source_formats.get("yahoo")
    today = today or date.today()
    start = (since - timedelta(days=5)) if since else today - timedelta(days=365 * years)
    p1 = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(today.year, today.month, today.day, tzinfo=timezone.utc).timestamp()) + 2 * 86400
    url = source_formats.expand(fmt["url"], symbol=urllib.parse.quote(symbol, safe="^.-="), p1=p1, p2=p2)
    body = http.with_retry(lambda: http.get(url))
    return parse_chart(body, since, fmt)


def search(query):
    """Symbol search: ``[{symbol, name, exchange, type}]``. A failure is an empty list plus the error text (the page then lets the person type the code)."""
    url = source_formats.expand(source_formats.get("yahoo")["search_url"], q=urllib.parse.quote(query))
    body = http.with_retry(lambda: http.get(url), tries=2)
    try:
        quotes = json.loads(body).get("quotes") or []
    except (ValueError, AttributeError) as exc:
        raise FetchError("Yahoo's search answer was not readable.") from exc
    return [{"symbol": q.get("symbol", ""), "name": q.get("longname") or q.get("shortname") or "", "exchange": q.get("exchDisp") or q.get("exchange") or "",
             "type": q.get("quoteType", "")} for q in quotes if q.get("symbol")]
