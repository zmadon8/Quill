"""Twelve Data (plan 15.3, second stock source, used as a fallback). Needs an API key in the environment variable TWELVEDATA_API_KEY
(never in the database or a backup, plan 15.7). Whether Indian exchanges are on the free plan is still to be confirmed with one call
(plan 3.10). Symbols: ``RELIANCE.NS`` becomes ``RELIANCE`` on exchange ``NSE`` (``.BO`` is ``BSE``), unless a symbol is set for this source."""
import json
import os
import urllib.parse
from datetime import date, timedelta

from investments.services import source_formats

from . import http
from .base import FetchError, FormatError, Result, clean_close

URL = source_formats.DEFAULTS["twelvedata"]["url"]


def split_symbol(code):
    if code.endswith(".NS"):
        return code[:-3], "NSE"
    if code.endswith(".BO"):
        return code[:-3], "BSE"
    return code, ""


def parse(body, since=None, fmt=None):
    """Where the fields are in the answer is the format ``twelvedata`` of ``services/source_formats.py``."""
    fmt = fmt or source_formats.get("twelvedata")
    get = source_formats.dig
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise FetchError("Twelve Data answered with something that is not price data.") from exc
    if not isinstance(data, dict):
        raise FormatError("Twelve Data answered with something that is not price data.", key="twelvedata")
    if get(data, fmt["status_path"]) != fmt["ok_value"]:
        code = get(data, fmt["code_path"])
        raise FetchError(f"Twelve Data: {get(data, fmt['message_path']) or code or 'refused'}", retryable=code == 429)
    out = Result(currency=get(data, fmt["currency_path"]) or "", exchange=get(data, fmt["exchange_path"]) or "")
    values = get(data, fmt["values_path"]) or []
    if not isinstance(values, list):
        raise FormatError(f"Twelve Data: nothing readable at '{'.'.join(str(s) for s in fmt['values_path'])}'.", key="twelvedata")
    first = next((v for v in values if isinstance(v, dict)), None)
    if first is not None and (fmt["date_key"] not in first or fmt["close_key"] not in first):
        seen = sorted(first)
        raise FormatError(f"Twelve Data: the entries have no '{fmt['date_key']}' or '{fmt['close_key']}' field (fields seen: {', '.join(seen)}).",
                          key="twelvedata", missing=[k for k in (fmt["date_key"], fmt["close_key"]) if k not in first], headers=seen)
    seen = {}
    for item in values:
        item = item if isinstance(item, dict) else {}
        day = source_formats.parse_day(str(item.get(fmt["date_key"], ""))[:10], fmt["date_formats"])
        close = clean_close(item.get(fmt["close_key"]))
        if day is None or close is None:
            out.rejected += 1
            continue
        if since is None or day >= since:
            seen[day] = close
    out.rows = sorted(seen.items())
    return out


def configured():
    return bool(os.environ.get("TWELVEDATA_API_KEY"))


def fetch(code, since=None, years=10, today=None):
    key = os.environ.get("TWELVEDATA_API_KEY", "")
    if not key:
        raise FetchError("Twelve Data is not set up (TWELVEDATA_API_KEY is missing).")
    today = today or date.today()
    start = (since - timedelta(days=5)) if since else today - timedelta(days=365 * years)
    symbol, exchange = split_symbol(code)
    fmt = source_formats.get("twelvedata")
    url = source_formats.expand(fmt["url"], symbol=urllib.parse.quote(symbol), exchange=exchange, start=start.isoformat(), key=urllib.parse.quote(key))
    return parse(http.with_retry(lambda: http.get(url)), since, fmt)
