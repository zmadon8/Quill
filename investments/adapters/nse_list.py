"""NSE's list of listed equities (``EQUITY_L.csv``: SYMBOL, NAME OF COMPANY, SERIES, ISIN NUMBER ...), read line by line for the
searchable list used when adding an investment. The address is the setting ``INVESTMENTS_NSE_LIST_URL``; the delimiter, the column
aliases and the series kept are the format ``nse_list`` of ``services/source_formats.py``."""
import csv

from investments.services import source_formats

from . import bhavcopy, http
from .base import FormatError

DEFAULT_URL = source_formats.DEFAULTS["nse_list"]["url"]
LABEL = "NSE's equity list"


def iter_all(lines, fmt=None):
    """Yield ``(symbol, name, isin, series)`` for each row whose series is one the program keeps (the format's ``series_keep``).
    The header row is the first one that has a symbol column. Raises :class:`FormatError` when it lacks a required column, or when rows
    were read and none was usable."""
    fmt = fmt or source_formats.default("nse_list")
    keep = bhavcopy.series_order(fmt)
    columns = fmt["columns"]
    reader = csv.reader(lines, delimiter=fmt["delimiter"])
    index = None
    rows = used = 0
    first_headers = []
    for row in reader:
        if index is None:
            found = source_formats.match_columns(row, columns)
            if found["symbol"] is not None:
                index = found
                source_formats.require("nse_list", LABEL, index, ("symbol", "name"), row, columns)
            elif not first_headers and any(c.strip() for c in row):
                first_headers = row
            continue
        rows += 1
        try:
            symbol = row[index["symbol"]].strip().upper()
            name = row[index["name"]].strip()
            series = row[index["series"]].strip().upper() if index["series"] is not None else ""
            isin = row[index["isin"]].strip().upper() if index["isin"] is not None else ""
        except IndexError:
            continue
        if not symbol or not name:
            continue
        used += 1
        if series not in keep:
            continue
        yield symbol, name, isin, series
    if index is None and len(first_headers) >= 3:          # a real header row that has no symbol column (not stray text)
        source_formats.require("nse_list", LABEL, {"symbol": None}, ("symbol",), first_headers, columns)
    if rows and not used:
        raise FormatError(f"{LABEL}: {rows} rows were read and none had a symbol and a name.", key="nse_list")


def fetch_list(store, url=None):
    """Stream the whole file once, handing each security to ``store`` (no list of all of them is kept)."""
    fmt = source_formats.get("nse_list")
    url = url or source_formats.url_for("nse_list", fmt, "INVESTMENTS_NSE_LIST_URL")

    def run():
        with http.open_url(url, timeout=60, headers=bhavcopy.NSE_HEADERS) as response:
            return store(iter_all((raw.decode("utf-8", "replace") for raw in response), fmt))

    return http.with_retry(run)
