"""mfapi.in: the full NAV history of one scheme in one call (about 130 KB), newest first. A third-party service with no guarantee."""
import json

from . import http
from .base import FetchError, Result, clean_close, parse_day

URL = "https://api.mfapi.in/mf/{code}"


def parse(body, since=None):
    try:
        data = json.loads(body)
        rows_in = data["data"]
    except (ValueError, KeyError, TypeError) as exc:
        raise FetchError("mfapi.in answered with something that is not NAV data.") from exc
    meta = data.get("meta") or {}
    out = Result(name=meta.get("scheme_name", ""), currency="INR")
    seen = {}
    for item in rows_in:
        day = parse_day(str(item.get("date", "")))
        nav = clean_close(item.get("nav"))
        if day is None or nav is None:
            out.rejected += 1
            continue
        if since is not None and day < since:
            continue
        seen[day] = nav
    out.rows = sorted(seen.items())
    return out


def fetch(code, since=None):
    body = http.with_retry(lambda: http.get(URL.format(code=str(code).strip())))
    return parse(body, since)
