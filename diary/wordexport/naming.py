"""File names and dates for the Word export (docs/DESIGN.md section 12.2). Pure Python, no Django."""
import re
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None

    class ZoneInfoNotFoundError(Exception):
        pass

ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
MAX_NAME = 120  # the whole name without ".docx" or ".zip"
SEGMENT_CUT = 30
SEGMENT_SOFT = 15
IST = timezone(timedelta(hours=5, minutes=30), "IST")
DEFAULT_ZONE = "Asia/Kolkata"

DATE_FORMATS = ("YYYY-MM-DD", "DD-MM-YYYY", "D Month YYYY")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")


def clean_part(name):
    """``name`` safe as part of a file name: each illegal character becomes '-', spaces collapse, no edge dots or spaces."""
    return " ".join(ILLEGAL.sub("-", name or "").split()).strip(". ")


def replacements(name):
    """Plain sentences telling which characters ``clean_part`` replaced (empty list if none), for the preview."""
    found = []
    for ch in ILLEGAL.findall(name or ""):
        shown = repr(ch)[1:-1] if ord(ch) < 32 or ord(ch) == 127 else ch
        if shown not in found:
            found.append(shown)
    return [f"'{ch}' was replaced with '-'" for ch in found]


def zone_for(name):
    """The time zone called ``name``; Asia/Kolkata (fixed +05:30, no daylight saving) if it is unknown or unavailable."""
    if ZoneInfo is not None and name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            pass
    return IST


def today(now=None, zone_name=DEFAULT_ZONE):
    """The date now in the time zone (``now`` is a timezone-aware datetime, default the current time)."""
    now = now or datetime.now(timezone.utc)
    return now.astimezone(zone_for(zone_name)).date()


def format_date(day, fmt="YYYY-MM-DD"):
    if fmt == "DD-MM-YYYY":
        return f"{day.day:02d}-{day.month:02d}-{day.year:04d}"
    if fmt == "D Month YYYY":
        return f"{day.day} {MONTHS[day.month - 1]} {day.year}"
    return f"{day.year:04d}-{day.month:02d}-{day.day:02d}"


def _cut(segment):
    """One path segment cut to 30 characters: at a word boundary after the 15th character if there is one, else at the 30th."""
    if len(segment) <= SEGMENT_CUT:
        return segment
    window = segment[:SEGMENT_CUT]
    space = window.rfind(" ")
    if space > SEGMENT_SOFT:
        window = window[:space]
    return window.rstrip(" .") or segment[:SEGMENT_CUT]


def shorten(segments, export_name, date_text):
    """The segments of a name, shortened by the documented rule if the whole name would pass 120 characters.

    1. If it is too long, every segment is cut to 30 characters (see ``_cut``).
    2. If it is still too long, the middle segments are replaced by one '-' (first and last stay).
    """
    segments = [s for s in segments if s]

    def total(parts):
        return len(f"{export_name} {', '.join(parts)} {date_text}")

    if total(segments) <= MAX_NAME:
        return segments
    segments = [_cut(s) for s in segments]
    if total(segments) > MAX_NAME and len(segments) > 2:
        segments = [segments[0], "-", segments[-1]]
    return segments


def build_name(export_name, part_names, date_text, extension, taken=None):
    """``[export name] [part] [date].ext``. ``part_names`` is a list of already cleaned names, joined with ', '.

    ``taken`` (a set of lower-case names, updated here) makes names in one zip unique: a clash gets " (2)", " (3)" before the date.
    """
    export_name = clean_part(export_name) or "Export"
    parts = shorten([clean_part(p) for p in part_names], export_name, date_text)
    base = " ".join(x for x in (export_name, ", ".join(parts)) if x)
    name = f"{base} {date_text}.{extension}"
    if taken is not None:
        n = 1
        candidate = base
        while f"{candidate} {date_text}.{extension}".lower() in taken:
            n += 1
            candidate = f"{base} ({n})"
        name = f"{candidate} {date_text}.{extension}"
        taken.add(name.lower())
    return name
