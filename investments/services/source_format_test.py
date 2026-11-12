"""The "Test this format" button of the Data source formats page: read a sample with a format that may not be saved yet, and show the
first parsed rows or the error. Nothing is stored: no price, no list, no SourceRun.

The sample is an uploaded file, or (for a source at an address) a download made through ``adapters/http.py`` with the date and symbol
placeholders filled in and a size cap."""
import csv
import io
import itertools
import zipfile
from datetime import date, timedelta

from investments.adapters import amfi, bhavcopy, http, mfapi, nse_list, twelvedata, yahoo
from investments.adapters.base import FetchError, FormatError
from investments.services import source_formats

SAMPLE_CAP = 8_000_000
ROWS = 10
SAMPLE_VALUES = {"mfapi": "122639", "yahoo": "RELIANCE.NS", "twelvedata": "RELIANCE.NS"}
HEADS = {
    "nse_eq": ["Symbol", "ISIN", "Series", "Close", "Date"], "bse_eq": ["Symbol", "ISIN", "Series", "Close", "Date"],
    "nse_idx": ["Index", "Date", "Close"], "amfi": ["Code", "Name", "ISIN", "Date", "NAV"], "nse_list": ["Symbol", "Name", "ISIN", "Series"],
    "mfapi": ["Date", "NAV"], "yahoo": ["Date", "Close"], "twelvedata": ["Date", "Close"],
    "price_import": ["Field", "Column found in the file"], "statement_import": ["Field", "Column found in the file"],
}


def latest_weekday(today=None):
    day = (today or date.today()) - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _lines(body):
    return io.StringIO(body.decode("utf-8-sig", "replace"), newline="")


def _download(key, fmt, day, sample):
    """``(body, address shown)``. Bhavcopy files are tried for the chosen day and up to four weekdays before it (holidays have no file)."""
    headers = {}
    if key in bhavcopy.KINDS:
        headers = bhavcopy.BSE_HEADERS if key == "bse_eq" else bhavcopy.NSE_HEADERS
    if key == "nse_list":
        headers = bhavcopy.NSE_HEADERS
    values = {}
    if key == "mfapi":
        values = {"code": sample}
    elif key == "yahoo":
        import urllib.parse

        end = day or date.today()
        values = {"symbol": urllib.parse.quote(sample, safe="^.-="), "p1": _epoch(end - timedelta(days=30)),
                  "p2": _epoch(end) + 2 * 86400, "q": urllib.parse.quote(sample)}
    elif key == "twelvedata":
        import os
        import urllib.parse

        symbol, exchange = twelvedata.split_symbol(sample)
        api_key = os.environ.get("TWELVEDATA_API_KEY", "")
        if not api_key:
            raise FetchError("Twelve Data needs TWELVEDATA_API_KEY on the server to download a sample; upload a sample answer (a .json file) instead.")
        values = {"symbol": urllib.parse.quote(symbol), "exchange": exchange, "start": (date.today() - timedelta(days=30)).isoformat(), "key": urllib.parse.quote(api_key)}
    tries = [day or latest_weekday()]
    if key in bhavcopy.KINDS and day is None:
        for _ in range(4):
            prev = tries[-1] - timedelta(days=1)
            while prev.weekday() >= 5:
                prev -= timedelta(days=1)
            tries.append(prev)
    last = None
    for when in tries:
        url = source_formats.expand(fmt["url"], when, **values)
        shown = url.replace(values.get("key", "\0"), "***") if "key" in values else url
        try:
            return http.get(url, timeout=60, headers=headers, max_bytes=SAMPLE_CAP), shown
        except FetchError as exc:
            last = exc
            if exc.status != 404:
                raise
    raise FetchError(f"{last} (tried {len(tries)} day{'s' if len(tries) > 1 else ''}; the address may be wrong, or the file is not published for that day).")


def _epoch(day):
    from datetime import datetime, timezone

    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())


def _header_check(key, body, fmt):
    """For the two imports: which column each field was found in. A missing required one is an error."""
    reader = csv.reader(_lines(body))
    headers = [c.strip() for c in next((r for r in reader if any(c.strip() for c in r)), [])]
    if not headers:
        raise FormatError("The sample has no header row.", key="")
    if key == "price_import":
        from investments.services import price_import

        found = price_import.header_columns(headers, fmt["columns"])
        required = ("symbol", "date", "close")
    else:
        from investments.services import statement_import

        found = statement_import.guess_columns(headers, fmt["columns"])
        found = {f: found.get(f) for f in fmt["columns"]}
        required = ("date", "investment", "units")
    rows = [[field, headers[i] if i is not None else "not found" + (" (required)" if field in required else "")] for field, i in found.items()]
    missing = [f for f in required if found.get(f) is None]
    if missing:
        raise FormatError(f"No column found for {', '.join(missing)}. Headers seen: {', '.join(headers[:15])}.", key=key, missing=missing, headers=headers[:15])
    return rows, f"{len(headers)} columns in the header row"


def _parse(key, fmt, body):
    if key in ("nse_eq", "bse_eq"):
        rows = bhavcopy.sample_equity(bhavcopy.lines_of(key, body), nse=key == "nse_eq", fmt=fmt, limit=ROWS)
        return [list(r) for r in rows], ""
    if key == "nse_idx":
        found = bhavcopy.read_indices(bhavcopy.lines_of(key, body), fmt=fmt)
        return [[name, day.isoformat(), str(close)] for name, (day, close) in itertools.islice(found.items(), ROWS)], f"{len(found)} indices in the file"
    if key in ("amfi", "nse_list"):
        lines = (raw for raw in body.decode("utf-8", "replace").splitlines())
        it = amfi.iter_all(lines, fmt) if key == "amfi" else nse_list.iter_all(lines, fmt)
        rows, total = [], 0
        for item in it:
            total += 1
            if len(rows) < ROWS:
                rows.append([("" if v is None else v.isoformat() if hasattr(v, "isoformat") else str(v)) for v in item])
        if not total:
            raise FormatError("No row could be read from the sample.", key=key)
        return rows, f"{total} rows read"
    if key == "mfapi":
        out = mfapi.parse(body, fmt=fmt)
    elif key == "yahoo":
        out = yahoo.parse_chart(body, fmt=fmt)
    elif key == "twelvedata":
        out = twelvedata.parse(body, fmt=fmt)
    else:
        return _header_check(key, body, fmt)
    if not out.rows:
        raise FormatError("The answer was understood but holds no prices.", key=key)
    note = f"{len(out.rows)} prices; {out.name or 'no name'}" + (f"; {out.rejected} rejected" if out.rejected else "")
    return [[day.isoformat(), str(close)] for day, close in out.rows[-ROWS:]], note


def run(key, fmt, *, upload=None, day=None, sample=""):
    """``{"heads", "rows", "note", "error", "url"}``. ``upload`` is the sample file's bytes (already size-capped by the caller)."""
    result = {"heads": HEADS[key], "rows": [], "note": "", "error": "", "url": ""}
    try:
        if upload:
            body = upload
        elif key in source_formats.UPLOAD_ONLY:
            raise FetchError("Choose a sample file (a CSV with a header row) to test these columns.")
        else:
            body, result["url"] = _download(key, fmt, day, (sample or "").strip() or SAMPLE_VALUES.get(key, ""))
        if not body.strip():
            raise FormatError("The sample is empty.", key=key)
        result["rows"], result["note"] = _parse(key, fmt, body)
    except FetchError as exc:
        result["error"] = str(exc)
    except (ValueError, KeyError, IndexError, TypeError, OSError, csv.Error, EOFError, zipfile.BadZipFile) as exc:     # a sample that is not what its format says (a bad zip, text in a JSON slot)
        result["error"] = f"The sample could not be read: {exc}"
    return result
