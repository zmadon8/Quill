"""Twelve Data (plan 15.3, second stock source, used as a fallback). Needs an API key in the environment variable TWELVEDATA_API_KEY
(never in the database or a backup, plan 15.7). Whether Indian exchanges are on the free plan is still to be confirmed with one call
(plan 3.10). Symbols: ``RELIANCE.NS`` becomes ``RELIANCE`` on exchange ``NSE`` (``.BO`` is ``BSE``), unless a symbol is set for this source."""
import json
import os
import urllib.parse
from datetime import date, timedelta

from . import http
from .base import FetchError, Result, clean_close, parse_day

URL = "https://api.twelvedata.com/time_series?symbol={symbol}&exchange={exchange}&interval=1day&start_date={start}&outputsize=5000&apikey={key}"


def split_symbol(code):
    if code.endswith(".NS"):
        return code[:-3], "NSE"
    if code.endswith(".BO"):
        return code[:-3], "BSE"
    return code, ""


def parse(body, since=None):
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise FetchError("Twelve Data answered with something that is not price data.") from exc
    if data.get("status") != "ok":
        raise FetchError(f"Twelve Data: {data.get('message') or data.get('code') or 'refused'}", retryable=data.get("code") == 429)
    out = Result(currency=(data.get("meta") or {}).get("currency", ""), exchange=(data.get("meta") or {}).get("exchange", ""))
    seen = {}
    for item in data.get("values") or []:
        day, close = parse_day(str(item.get("datetime", ""))[:10]), clean_close(item.get("close"))
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
    url = URL.format(symbol=urllib.parse.quote(symbol), exchange=exchange, start=start.isoformat(), key=urllib.parse.quote(key))
    return parse(http.with_retry(lambda: http.get(url)), since)
