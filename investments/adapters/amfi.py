"""AMFI's daily NAV file (a few MB). Read line by line, keeping only the scheme codes asked for (plan 15.3: under 12 MB)."""
from decimal import Decimal

from . import http
from .base import FetchError, clean_close, parse_day

DEFAULT_URL = "https://www.amfiindia.com/spages/NAVAll.txt"


def parse_lines(lines, wanted):
    """``{scheme code: (date, nav, name, isin)}`` for the codes in ``wanted``. ``lines`` yields decoded text lines."""
    found = {}
    wanted = {str(w).strip() for w in wanted}
    for line in lines:
        if ";" not in line:
            continue
        parts = line.rstrip("\r\n").split(";")
        if len(parts) < 6 or not parts[0].strip().isdigit():
            continue
        code = parts[0].strip()
        if code not in wanted:
            continue
        nav = clean_close(parts[4])
        day = parse_day(parts[5])
        if nav is None or day is None:
            continue
        found[code] = (day, nav.quantize(Decimal("0.0001")), parts[3].strip(), parts[1].strip())
    return found


def fetch(wanted, url=None):
    """One download for every fund asked for. The address is a setting (the final address was not yet confirmed, plan 30)."""
    from django.conf import settings

    url = url or getattr(settings, "INVESTMENTS_AMFI_URL", "") or DEFAULT_URL

    def run():
        with http.open_url(url, timeout=60) as response:
            return parse_lines((raw.decode("utf-8", "replace") for raw in response), wanted)

    found = http.with_retry(run)
    if not found and wanted:
        # An empty answer for a non-empty request is suspicious (a redirect page, a changed layout): say so, never guess.
        raise FetchError("AMFI's file had none of the schemes asked for (the file or its address may have changed).")
    return found


def iter_all(lines):
    """Yield ``(code, name, isin, date, nav)`` for every scheme line (NAV may be None for "N.A.")."""
    for line in lines:
        if ";" not in line:
            continue
        parts = line.rstrip("\r\n").split(";")
        if len(parts) < 6 or not parts[0].strip().isdigit():
            continue
        isin = parts[1].strip() if parts[1].strip() not in ("-", "") else parts[2].strip()
        yield parts[0].strip(), parts[3].strip(), "" if isin == "-" else isin, parse_day(parts[5]), clean_close(parts[4])


def fetch_scheme_list(store, url=None):
    """Stream the whole file once, handing each scheme to ``store`` (no list of all schemes is kept)."""
    from django.conf import settings

    url = url or getattr(settings, "INVESTMENTS_AMFI_URL", "") or DEFAULT_URL

    def run():
        with http.open_url(url, timeout=60) as response:
            return store(iter_all(raw.decode("utf-8", "replace") for raw in response))

    return http.with_retry(run)
