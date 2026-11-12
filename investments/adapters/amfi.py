"""AMFI's daily NAV file (a few MB). Read line by line, keeping only the scheme codes asked for (plan 15.3: under 12 MB).

Where each field sits in a line (counted from the front, or from the back with a negative number), the delimiter and the date formats are
the format ``amfi`` of ``services/source_formats.py``, which an Admin can change. A body with lines that none can be read with is a
:class:`FormatError`, so a changed layout is seen instead of silently pricing nothing."""
from decimal import Decimal

from investments.services import source_formats

from . import http
from .base import FetchError, FormatError, clean_close

DEFAULT_URL = source_formats.DEFAULTS["amfi"]["url"]
LABEL = "AMFI's file"


def _parts(line, fmt):
    """The fields of a scheme line, or None for a line that is not one (a heading, a blank, a category line)."""
    if fmt["delimiter"] not in line:
        return None
    parts = line.rstrip("\r\n").split(fmt["delimiter"])
    if len(parts) < fmt["min_fields"]:
        return None
    try:
        if not parts[fmt["code_col"]].strip().isdigit():
            return None
    except IndexError:
        return None
    return parts


def _name(parts, fmt):
    """The scheme name. AMFI's newer lines have the plan and option as separate columns after the name; they are joined on
    with " - " so the result reads like the older single-column names ("Fund - Regular Plan - IDCW Option")."""
    return " - ".join(p.strip() for p in parts[fmt["name_from_col"]:fmt["nav_col"]] if p.strip())


def _unreadable(seen, fmt, first):
    return FormatError(f"{LABEL}: {seen} lines were read but none could be read as a scheme with a NAV and a date (first line: {first[:80]!r}). "
                       "The layout may have changed (Admin: Catalogue > Price sources > Data source formats).", key="amfi")


def parse_lines(lines, wanted, fmt=None):
    """``{scheme code: (date, nav, name, isin)}`` for the codes in ``wanted``. ``lines`` yields decoded text lines."""
    fmt = fmt or source_formats.get("amfi")
    found = {}
    wanted = {str(w).strip() for w in wanted}
    readable, seen, first = False, 0, ""
    for line in lines:
        if not line.strip():
            continue
        seen += 1
        first = first or line
        parts = _parts(line, fmt)
        if parts is None:
            continue
        # NAV and date are the LAST two fields; the name is everything between the ISINs and them (AMFI now has extra columns
        # such as "Regular Plan" and "IDCW Option" after the name, so counting from the front is not safe).
        try:
            nav = clean_close(parts[fmt["nav_col"]])
            day = source_formats.parse_day(parts[fmt["date_col"]], fmt["date_formats"])
            code, isin = parts[fmt["code_col"]].strip(), parts[fmt["isin_col"]].strip()
        except IndexError:
            continue
        if nav is not None and day is not None:
            readable = True
        if code not in wanted or nav is None or day is None:
            continue
        found[code] = (day, nav.quantize(Decimal("0.0001")), _name(parts, fmt), isin)
    if seen and not readable:
        raise _unreadable(seen, fmt, first)
    return found


def fetch(wanted, url=None):
    """One download for every fund asked for. The address is a setting (the final address was not yet confirmed, plan 30)."""
    fmt = source_formats.get("amfi")
    url = url or source_formats.url_for("amfi", fmt, "INVESTMENTS_AMFI_URL")

    def run():
        with http.open_url(url, timeout=60) as response:
            return parse_lines((raw.decode("utf-8", "replace") for raw in response), wanted, fmt)

    found = http.with_retry(run)
    if not found and wanted:
        # An empty answer for a non-empty request is suspicious (a redirect page, a changed layout): say so, never guess.
        raise FetchError("AMFI's file had none of the schemes asked for (the file or its address may have changed).")
    return found


def iter_all(lines, fmt=None):
    """Yield ``(code, name, isin, date, nav)`` for every scheme line (NAV may be None for "N.A."). Raises :class:`FormatError` at the end
    when lines were read and none was a scheme with a readable date."""
    fmt = fmt or source_formats.get("amfi")
    readable, seen, first = False, 0, ""
    for line in lines:
        if not line.strip():
            continue
        seen += 1
        first = first or line
        parts = _parts(line, fmt)
        if parts is None:
            continue
        try:
            isin = parts[fmt["isin_col"]].strip() if parts[fmt["isin_col"]].strip() not in ("-", "") else parts[fmt["isin_alt_col"]].strip()
            day = source_formats.parse_day(parts[fmt["date_col"]], fmt["date_formats"])
            nav = clean_close(parts[fmt["nav_col"]])
            code = parts[fmt["code_col"]].strip()
        except IndexError:
            continue
        if day is not None:
            readable = True
        yield code, _name(parts, fmt), "" if isin == "-" else isin, day, nav
    if seen and not readable:
        raise _unreadable(seen, fmt, first)


def fetch_scheme_list(store, url=None):
    """Stream the whole file once, handing each scheme to ``store`` (no list of all schemes is kept)."""
    fmt = source_formats.get("amfi")
    url = url or source_formats.url_for("amfi", fmt, "INVESTMENTS_AMFI_URL")

    def run():
        with http.open_url(url, timeout=60) as response:
            return store(iter_all((raw.decode("utf-8", "replace") for raw in response), fmt))

    return http.with_retry(run)
