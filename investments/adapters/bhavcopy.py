"""NSE and BSE daily bhavcopy files: the exchanges' own end-of-day closes (one file per trading day, published in the evening).

Three files are read, each once per run and line by line, keeping only the rows asked for:

* NSE equities (the "UDiFF" common bhavcopy NSE has published since 8 July 2024): a zip holding one CSV with, among others, ``TckrSymb``
  (symbol), ``SctySrs`` (series, EQ for ordinary shares and ETFs), ``ISIN``, ``ClsPric`` (official close) and ``TradDt`` (YYYY-MM-DD).
* NSE indices (``ind_close_all``): ``Index Name``, ``Index Date`` (DD-MM-YYYY) and ``Closing Index Value``.
* BSE equities (UDiFF, the same columns as NSE's; ``FinInstrmId`` is the BSE scrip code).

The closes are as traded (raw). For the newest day this is the same figure as a split-adjusted close, so the program uses bhavcopy only
to fill recent days (see ``services/bhav.py``). The addresses are settings because the exchanges change them from time to time.
A missing file (404: a holiday, a weekend, or not yet published) is ``None``, not an error.
"""
import csv
import io
import itertools
import time
import zipfile
from datetime import datetime
from decimal import Decimal

from investments.services import source_formats

from . import http
from .base import FetchError, FormatError, clean_close

NSE_EQUITY_URL = source_formats.DEFAULTS["nse_eq"]["url"]
NSE_INDEX_URL = source_formats.DEFAULTS["nse_idx"]["url"]
BSE_EQUITY_URL = source_formats.DEFAULTS["bse_eq"]["url"]

NSE_HEADERS = {"Referer": "https://www.nseindia.com/", "Accept-Language": "en-IN,en;q=0.9"}
BSE_HEADERS = {"Referer": "https://www.bseindia.com/", "Accept-Language": "en-IN,en;q=0.9"}

#: NSE series kept, best first: ordinary shares and ETFs (EQ), trade-for-trade (BE, BZ), SME (SM, ST), REITs (RR) and InvITs (IV).
#: Other NSE series on the same symbol or ISIN (bonds, rights, warrants) are left out. BSE's column holds the scrip group, so it is not filtered.
#: These are the built-in ones; an Admin can change the list (``series_keep`` of the format), and a blank series is always kept, last.
SERIES_ORDER = tuple(source_formats.SERIES_KEEP) + ("",)

KINDS = ("nse_eq", "nse_idx", "bse_eq")
_SETTING = {"nse_eq": "INVESTMENTS_BHAV_NSE_URL", "nse_idx": "INVESTMENTS_BHAV_NSE_INDEX_URL", "bse_eq": "INVESTMENTS_BHAV_BSE_URL"}

# The downloads of this process, for half an hour: the Update Prices button walks its batches in several requests.
CACHE_SECONDS = 1800
CACHE_ENTRIES = 8
_cache = {}


def series_order(fmt):
    return tuple(fmt["series_keep"]) + ("",)


def url_for(kind, day, fmt=None):
    if kind not in _SETTING:
        raise ValueError(kind)
    fmt = fmt or source_formats.default(kind)
    return source_formats.expand(source_formats.url_for(kind, fmt, _SETTING[kind]), day)


def label(kind):
    return {"nse_eq": "NSE bhavcopy", "nse_idx": "NSE index closes", "bse_eq": "BSE bhavcopy"}[kind]


def _day(text, formats=None):
    for fmt in formats or source_formats.DEFAULTS["nse_eq"]["date_formats"]:
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _reader(lines, fmt):
    """``(header names, remaining rows)``; the names are stripped (the files can carry a BOM and stray spaces)."""
    reader = csv.reader(lines, delimiter=fmt["delimiter"])
    header = next(itertools.islice(reader, fmt["header_row"], None), None)
    if not header:
        return [], []
    return [h.strip().lstrip("\ufeff").strip() for h in header], reader


def _equity_index(kind, header, fmt):
    """The column index of each field, or a :class:`FormatError` naming what is missing and the headers seen."""
    index = source_formats.match_columns(header, fmt["columns"])
    missing = [f for f in ("close", "date") if index[f] is None]
    if index["symbol"] is None and index["isin"] is None:
        missing.append("symbol or isin")
    if missing:
        seen = header[:15]
        raise FormatError(f"{label(kind)}: no column found for {', '.join(missing)}. Headers seen: {', '.join(seen)}. "
                          "The exchange may have changed the file (Admin: Catalogue > Price sources > Data source formats).",
                          key=kind, missing=missing, headers=seen)
    return index


def read_equity(lines, symbols=(), isins=(), codes=(), nse=True, fmt=None):
    """``{("sym"|"isin"|"code", key): (date, close)}`` for the wanted keys of an NSE or BSE equity file (new layout, or the old NSE one).
    Where a key appears in several series, the best series (``SERIES_ORDER``) wins. Raises :class:`FormatError` when columns are missing
    or no row of a non-empty file has a readable close and date."""
    kind = "nse_eq" if nse else "bse_eq"
    fmt = fmt or source_formats.default(kind)
    header, rows = _reader(lines, fmt)
    if not header:
        raise FormatError(f"{label(kind)}: the file was empty.", key=kind)
    col = _equity_index(kind, header, fmt)
    i_sym, i_isin, i_code, i_series, i_close, i_date = (col[f] for f in ("symbol", "isin", "code", "series", "close", "date"))
    order_list = series_order(fmt)
    symbols = {s.upper() for s in symbols}
    isins = {s.upper() for s in isins}
    codes = {str(s) for s in codes}
    found, rank = {}, {}
    readable, unreadable = False, 0
    for cells in rows:
        if len(cells) <= i_close:
            continue
        if not readable:
            if clean_close(cells[i_close]) is not None and len(cells) > i_date and _day(cells[i_date], fmt["date_formats"]) is not None:
                readable = True
            else:
                unreadable += 1
        keys = []
        if i_sym is not None and cells[i_sym].strip().upper() in symbols:
            keys.append(("sym", cells[i_sym].strip().upper()))
        if i_isin is not None and len(cells) > i_isin and cells[i_isin].strip().upper() in isins:
            keys.append(("isin", cells[i_isin].strip().upper()))
        if i_code is not None and len(cells) > i_code and cells[i_code].strip() in codes:
            keys.append(("code", cells[i_code].strip()))
        if not keys:
            continue
        close = clean_close(cells[i_close])
        day = _day(cells[i_date], fmt["date_formats"]) if len(cells) > i_date else None
        if close is None or day is None:
            continue
        series = cells[i_series].strip().upper() if nse and i_series is not None and len(cells) > i_series else ""
        if series not in order_list:
            continue                         # bonds, rights, warrants and the like on the same ISIN or symbol
        order = order_list.index(series)
        for key in keys:
            if key not in found or order < rank[key]:
                found[key], rank[key] = (day, close.quantize(Decimal("0.0001"))), order
    if unreadable and not readable:
        raise FormatError(f"{label(kind)}: {unreadable} rows were read but none had a readable close and date "
                          "(check the date formats and columns under Data source formats).", key=kind, headers=header[:15])
    return found


def sample_equity(lines, nse=True, fmt=None, limit=10):
    """The first ``limit`` readable rows ``(symbol, isin, series, close, date)``, for the Test button. Same column rules as ``read_equity``."""
    kind = "nse_eq" if nse else "bse_eq"
    fmt = fmt or source_formats.default(kind)
    header, rows = _reader(lines, fmt)
    if not header:
        raise FormatError(f"{label(kind)}: the file was empty.", key=kind)
    col = _equity_index(kind, header, fmt)
    out = []
    for cells in rows:
        if len(cells) <= col["close"] or len(cells) <= col["date"]:
            continue
        close, day = clean_close(cells[col["close"]]), _day(cells[col["date"]], fmt["date_formats"])
        if close is None or day is None:
            continue
        pick = lambda f: cells[col[f]].strip() if col[f] is not None and len(cells) > col[f] else ""   # noqa: E731
        out.append((pick("symbol"), pick("isin"), pick("series"), str(close), day.isoformat()))
        if len(out) >= limit:
            break
    if not out:
        raise FormatError(f"{label(kind)}: no row had a readable close and date.", key=kind, headers=header[:15])
    return out


def read_indices(lines, names=(), fmt=None):
    """``{lower-case index name: (date, close)}`` for the wanted names (all names if none are given)."""
    fmt = fmt or source_formats.default("nse_idx")
    header, rows = _reader(lines, fmt)
    if not header:
        raise FormatError(f"{label('nse_idx')}: the file was empty.", key="nse_idx")
    index = source_formats.match_columns(header, fmt["columns"])
    source_formats.require("nse_idx", label("nse_idx"), index, ("name", "date", "close"), header, fmt["columns"])
    i_name, i_date, i_close = index["name"], index["date"], index["close"]
    names = {n.strip().lower() for n in names}
    found = {}
    seen_rows = 0
    for cells in rows:
        if len(cells) <= max(i_name, i_date, i_close):
            continue
        name = cells[i_name].strip().lower()
        close, day = clean_close(cells[i_close]), _day(cells[i_date], fmt["date_formats"])
        if close is not None and day is not None:
            seen_rows += 1
            if not names or name in names:
                found[name] = (day, close.quantize(Decimal("0.0001")))
    if not seen_rows:
        raise FormatError(f"{label('nse_idx')}: no row had a readable close and date (check the date formats and columns under Data source formats).",
                          key="nse_idx", headers=header[:15])
    return found


def download(kind, day, clock=time.monotonic):
    """The file of ``kind`` for ``day`` as bytes, or ``None`` when the exchange has no file for that day. Raises :class:`FetchError`."""
    url = url_for(kind, day, source_formats.get(kind))
    now = clock()
    hit = _cache.get(url)
    if hit and now - hit[0] < CACHE_SECONDS:
        return hit[1]
    headers = BSE_HEADERS if kind == "bse_eq" else NSE_HEADERS
    try:
        body = http.with_retry(lambda: http.get(url, timeout=60, headers=headers, max_bytes=40_000_000), tries=2)
    except FetchError as exc:
        if exc.status == 404:
            body = None
        else:
            raise
    if body is not None and body.lstrip()[:1] == b"<":
        # An HTML page with a 200 status: a block page or a "file not found" page, never the data.
        if b"404" in body[:3000] or b"not found" in body[:3000].lower():
            body = None
        else:
            raise FetchError(f"{label(kind)}: the exchange sent a web page instead of the file (it may be refusing downloads from this server).")
    if len(_cache) >= CACHE_ENTRIES:
        _cache.pop(min(_cache, key=lambda k: _cache[k][0]))
    _cache[url] = (now, body)
    return body


MAX_UNZIPPED = 300_000_000


def lines_of(kind, body):
    """Decoded text lines of a downloaded file (NSE's equity file is a zip holding one CSV)."""
    if body[:2] == b"PK":
        try:
            archive = zipfile.ZipFile(io.BytesIO(body))
        except zipfile.BadZipFile as exc:
            raise FetchError(f"{label(kind)}: the zip could not be opened.") from exc
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise FetchError(f"{label(kind)}: the zip has no CSV file in it.")
        if archive.getinfo(names[0]).file_size > MAX_UNZIPPED:      # the reader never gives more than the size declared here
            raise FetchError(f"{label(kind)}: the zip unpacks to more than {MAX_UNZIPPED // 1_000_000} MB, so it was not read.")
        return io.TextIOWrapper(archive.open(names[0]), encoding="utf-8-sig", errors="replace", newline="")
    return io.StringIO(body.decode("utf-8-sig", "replace"), newline="")


def clear_cache():
    _cache.clear()
