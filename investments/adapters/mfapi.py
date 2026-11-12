"""mfapi.in: the full NAV history of one scheme in one call (about 130 KB), newest first. A third-party service with no guarantee.

The address, the path to the list of NAVs, the names of the date and NAV fields and the date formats are the format ``mfapi`` of
``services/source_formats.py``."""
import json

from investments.services import source_formats

from . import http
from .base import FetchError, FormatError, Result, clean_close

URL = source_formats.DEFAULTS["mfapi"]["url"]


def parse(body, since=None, fmt=None):
    fmt = fmt or source_formats.get("mfapi")
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise FetchError("mfapi.in answered with something that is not NAV data.") from exc
    rows_in = source_formats.dig(data, fmt["rows_path"])
    if not isinstance(rows_in, list):
        raise FormatError(f"mfapi.in: no list of NAVs at '{'.'.join(str(s) for s in fmt['rows_path'])}' in the answer; "
                          "mfapi.in may have changed its answer (Admin: Data source formats).", key="mfapi")
    first = next((r for r in rows_in if isinstance(r, dict)), None)
    if first is not None and (fmt["date_key"] not in first or fmt["nav_key"] not in first):
        seen = sorted(first)
        raise FormatError(f"mfapi.in: the NAV entries have no '{fmt['date_key']}' or '{fmt['nav_key']}' field (fields seen: {', '.join(seen)}).",
                          key="mfapi", missing=[k for k in (fmt["date_key"], fmt["nav_key"]) if k not in first], headers=seen)
    out = Result(name=str(source_formats.dig(data, fmt["name_path"], "") or ""), currency="INR")
    seen = {}
    for item in rows_in:
        if not isinstance(item, dict):
            out.rejected += 1
            continue
        day = source_formats.parse_day(str(item.get(fmt["date_key"], "")), fmt["date_formats"])
        nav = clean_close(item.get(fmt["nav_key"]))
        if day is None or nav is None:
            out.rejected += 1
            continue
        if since is not None and day < since:
            continue
        seen[day] = nav
    if rows_in and not seen and out.rejected == len(rows_in) and since is None:
        # every entry has the fields but none could be read: a changed date style, most likely
        sample = rows_in[0].get(fmt["date_key"]) if isinstance(rows_in[0], dict) else rows_in[0]
        if source_formats.parse_day(str(sample), fmt["date_formats"]) is None:
            raise FormatError(f"mfapi.in: none of the {len(rows_in)} dates could be read (first: {str(sample)[:30]!r}); check the date formats.", key="mfapi")
    out.rows = sorted(seen.items())
    return out


def fetch(code, since=None):
    fmt = source_formats.get("mfapi")
    url = source_formats.expand(source_formats.url_for("mfapi", fmt), code=str(code).strip())
    body = http.with_retry(lambda: http.get(url))
    return parse(body, since, fmt)
