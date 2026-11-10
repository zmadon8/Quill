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
import time
import zipfile
from datetime import datetime
from decimal import Decimal

from . import http
from .base import FetchError, clean_close

NSE_EQUITY_URL = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip"
NSE_INDEX_URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{dmy}.csv"
BSE_EQUITY_URL = "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{ymd}_F_0000.CSV"

NSE_HEADERS = {"Referer": "https://www.nseindia.com/", "Accept-Language": "en-IN,en;q=0.9"}
BSE_HEADERS = {"Referer": "https://www.bseindia.com/", "Accept-Language": "en-IN,en;q=0.9"}

#: NSE series kept, best first: ordinary shares and ETFs (EQ), trade-for-trade (BE, BZ), SME (SM, ST), REITs (RR) and InvITs (IV).
#: Other NSE series on the same symbol or ISIN (bonds, rights, warrants) are left out. BSE's column holds the scrip group, so it is not filtered.
SERIES_ORDER = ("EQ", "BE", "BZ", "SM", "ST", "RR", "IV", "")

KINDS = ("nse_eq", "nse_idx", "bse_eq")

# The downloads of this process, for half an hour: the Update Prices button walks its batches in several requests.
CACHE_SECONDS = 1800
CACHE_ENTRIES = 8
_cache = {}


def _setting(name, default):
    from django.conf import settings

    return getattr(settings, name, "") or default


def url_for(kind, day):
    ymd, dmy = day.strftime("%Y%m%d"), day.strftime("%d%m%Y")
    if kind == "nse_eq":
        return _setting("INVESTMENTS_BHAV_NSE_URL", NSE_EQUITY_URL).format(ymd=ymd, dmy=dmy)
    if kind == "nse_idx":
        return _setting("INVESTMENTS_BHAV_NSE_INDEX_URL", NSE_INDEX_URL).format(ymd=ymd, dmy=dmy)
    if kind == "bse_eq":
        return _setting("INVESTMENTS_BHAV_BSE_URL", BSE_EQUITY_URL).format(ymd=ymd, dmy=dmy)
    raise ValueError(kind)


def label(kind):
    return {"nse_eq": "NSE bhavcopy", "nse_idx": "NSE index closes", "bse_eq": "BSE bhavcopy"}[kind]


def _day(text):
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _reader(lines):
    """``(header names, remaining rows)``; the names are stripped (the files can carry a BOM and stray spaces)."""
    reader = csv.reader(lines)
    header = next(reader, None)
    if not header:
        return [], []
    return [h.strip().lstrip("\ufeff").strip() for h in header], reader


def read_equity(lines, symbols=(), isins=(), codes=(), nse=True):
    """``{("sym"|"isin"|"code", key): (date, close)}`` for the wanted keys of an NSE or BSE equity file (new layout, or the old NSE one).
    Where a key appears in several series, the best series (``SERIES_ORDER``) wins."""
    header, rows = _reader(lines)
    if not header:
        raise FetchError("The bhavcopy file was empty.")
    col = {name: i for i, name in enumerate(header)}

    def pick(*names):
        for name in names:
            if name in col:
                return col[name]
        return None

    i_sym, i_isin, i_code = pick("TckrSymb", "SYMBOL", "SC_NAME"), pick("ISIN", "ISIN_CODE"), pick("FinInstrmId", "SC_CODE")
    i_series, i_close, i_date = pick("SctySrs", "SERIES", "SC_GROUP"), pick("ClsPric", "CLOSE"), pick("TradDt", "TIMESTAMP", "TRADING_DATE")
    if i_close is None or (i_sym is None and i_isin is None):
        raise FetchError(f"The bhavcopy file has columns this program does not know ({', '.join(header[:8])}); the exchange may have changed it.")
    symbols = {s.upper() for s in symbols}
    isins = {s.upper() for s in isins}
    codes = {str(s) for s in codes}
    found, rank = {}, {}
    for cells in rows:
        if len(cells) <= i_close:
            continue
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
        day = _day(cells[i_date]) if i_date is not None and len(cells) > i_date else None
        if close is None or day is None:
            continue
        series = cells[i_series].strip().upper() if nse and i_series is not None and len(cells) > i_series else ""
        if series not in SERIES_ORDER:
            continue                         # bonds, rights, warrants and the like on the same ISIN or symbol
        order = SERIES_ORDER.index(series)
        for key in keys:
            if key not in found or order < rank[key]:
                found[key], rank[key] = (day, close.quantize(Decimal("0.0001"))), order
    return found


def read_indices(lines, names=()):
    """``{lower-case index name: (date, close)}`` for the wanted names (all names if none are given)."""
    header, rows = _reader(lines)
    col = {name.lower(): i for i, name in enumerate(header)}
    i_name, i_date, i_close = col.get("index name"), col.get("index date"), col.get("closing index value")
    if None in (i_name, i_date, i_close):
        raise FetchError(f"NSE's index file has columns this program does not know ({', '.join(header[:6])}); NSE may have changed it.")
    names = {n.strip().lower() for n in names}
    found = {}
    for cells in rows:
        if len(cells) <= max(i_name, i_date, i_close):
            continue
        name = cells[i_name].strip().lower()
        if names and name not in names:
            continue
        close, day = clean_close(cells[i_close]), _day(cells[i_date])
        if close is not None and day is not None:
            found[name] = (day, close.quantize(Decimal("0.0001")))
    return found


def download(kind, day, clock=time.monotonic):
    """The file of ``kind`` for ``day`` as bytes, or ``None`` when the exchange has no file for that day. Raises :class:`FetchError`."""
    url = url_for(kind, day)
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
        return io.TextIOWrapper(archive.open(names[0]), encoding="utf-8-sig", errors="replace", newline="")
    return io.StringIO(body.decode("utf-8-sig", "replace"), newline="")


def clear_cache():
    _cache.clear()
