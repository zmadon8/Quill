"""NSE's list of listed equities (``EQUITY_L.csv``: SYMBOL, NAME OF COMPANY, SERIES, ISIN NUMBER ...), read line by line for the
searchable list used when adding an investment. The address is the setting ``INVESTMENTS_NSE_LIST_URL``."""
import csv

from . import bhavcopy, http

DEFAULT_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"


def iter_all(lines):
    """Yield ``(symbol, name, isin, series)`` for each row whose series is one the program keeps (``bhavcopy.SERIES_ORDER``)."""
    reader = csv.reader(lines)
    columns = None
    for row in reader:
        if columns is None:
            names = [c.strip().upper().lstrip("\ufeff") for c in row]
            if "SYMBOL" in names:
                columns = {n: i for i, n in enumerate(names)}
            continue
        try:
            symbol = row[columns["SYMBOL"]].strip().upper()
            name = row[columns["NAME OF COMPANY"]].strip()
            series = row[columns["SERIES"]].strip().upper() if "SERIES" in columns else ""
            isin = row[columns["ISIN NUMBER"]].strip().upper() if "ISIN NUMBER" in columns else ""
        except (IndexError, KeyError):
            continue
        if not symbol or not name or series not in bhavcopy.SERIES_ORDER:
            continue
        yield symbol, name, isin, series


def fetch_list(store, url=None):
    """Stream the whole file once, handing each security to ``store`` (no list of all of them is kept)."""
    from django.conf import settings

    url = url or getattr(settings, "INVESTMENTS_NSE_LIST_URL", "") or DEFAULT_URL

    def run():
        with http.open_url(url, timeout=60, headers=bhavcopy.NSE_HEADERS) as response:
            return store(iter_all(raw.decode("utf-8", "replace") for raw in response))

    return http.with_retry(run)
