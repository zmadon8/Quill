"""Memo export file names (design 8.3, requirements R-FN-1 to R-FN-6).

``memo_export_filename(memo, settings)`` builds the ``.docx`` name from the profile's pattern
(``FeesSettings.memo_filename_pattern``). A small hand-written scanner parses the pattern into literal
text, ``{placeholder}`` and optional ``[ ... ]`` segments; there is no ``eval`` and no ``str.format``.
``validate_pattern`` returns a list of error messages (empty when the pattern is valid).

The default pattern gives exactly the names the original app produced
(``Memo 5 of 2026-27 Ziyad Madon (Matter).docx``).

``content_disposition`` builds the ``Content-Disposition`` header value (RFC 5987 ``filename*`` plus an
ASCII fallback ``filename``).
"""

import datetime
import re
from urllib.parse import quote

DEFAULT_PATTERN = "Memo {memo_no}[ of {fy}] {owner} ({matter})"
EXTENSION = ".docx"
MAX_PATTERN_LENGTH = 200
MAX_STEM_LENGTH = 150

#: Every placeholder a pattern may use (R-FN-3), in the order the settings page lists them.
PLACEHOLDERS = (
    "memo_no",
    "fy",
    "number_raw",
    "owner",
    "matter",
    "matter_name",
    "short_name",
    "firm",
    "group",
    "date",
    "date_iso",
    "today",
    "client",
)

_ILLEGAL = re.compile(r'[/\\:*?"<>|]')
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_text(text):
    """Replace path-illegal characters with ``-`` and drop control characters (no trimming)."""
    return _CONTROL.sub("", _ILLEGAL.sub("-", text or ""))


def sanitize_value(text):
    """The original rule (R-FN-6.1): replace illegal characters, drop control characters, trim."""
    return sanitize_text(text).strip()


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------
# A parsed pattern is a list of nodes: ("lit", text), ("ph", name) or ("opt", [inner nodes]) where the
# inner nodes are only "lit" and "ph".


def _parse(pattern):
    """Return ``(nodes, errors)`` for ``pattern``."""
    errors = []
    root = []
    current = root
    in_group = False
    literal = []

    def flush():
        if literal:
            current.append(("lit", "".join(literal)))
            literal.clear()

    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "{":
            end = pattern.find("}", i + 1)
            inner_open = pattern.find("{", i + 1)
            if end == -1 or (inner_open != -1 and inner_open < end):
                errors.append("Unbalanced brace: a { has no matching }")
                return [], errors
            name = pattern[i + 1 : end]
            if name not in PLACEHOLDERS:
                errors.append("Unknown placeholder {%s}" % name)
                return [], errors
            flush()
            current.append(("ph", name))
            i = end + 1
        elif ch == "}":
            errors.append("Unbalanced brace: a } has no matching {")
            return [], errors
        elif ch == "[":
            if in_group:
                errors.append("Square brackets cannot be nested")
                return [], errors
            flush()
            group = []
            root.append(("opt", group))
            current = group
            in_group = True
            i += 1
        elif ch == "]":
            if not in_group:
                errors.append("Unbalanced bracket: a ] has no matching [")
                return [], errors
            flush()
            current = root
            in_group = False
            i += 1
        else:
            literal.append(ch)
            i += 1
    if in_group:
        errors.append("Unbalanced bracket: a [ has no matching ]")
        return [], errors
    flush()
    return root, errors


def validate_pattern(pattern):
    """Error messages for ``pattern`` (R-FN-6.5); an empty list means it is valid or blank."""
    text = "" if pattern is None else str(pattern)
    if len(text) > MAX_PATTERN_LENGTH:
        return ["File-name pattern must be at most %d characters" % MAX_PATTERN_LENGTH]
    if not text.strip():
        return []
    return _parse(text)[1]


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------


def _split_number(memo):
    """``(memo_no, fy, raw)`` per R-FN-3, matching the original ``deriveExportFilename``."""
    num = memo.memo_number or ""
    slash = num.rfind("/")
    if slash >= 0:
        return num[slash + 1 :], num[:slash], num
    return (num or str(memo.seq)), "", num


def _date_text(value, fmt):
    return value.strftime(fmt) if value else ""


def placeholder_values(memo, settings, today=None):
    """The sanitised value of every placeholder for ``memo`` (R-FN-3, R-FN-6.1)."""
    today = today or datetime.date.today()
    memo_no, fy, raw = _split_number(memo)
    matter = memo.matter
    short = matter.short_name or ""
    values = {
        "memo_no": memo_no,
        "fy": fy,
        "number_raw": raw,
        "owner": getattr(settings, "export_owner_name", "") or "",
        "matter": short or matter.name or "",
        "matter_name": matter.name or "",
        "short_name": short,
        "firm": memo.firm.name or "",
        "group": memo.group.name or "",
        "date": _date_text(memo.date, "%d.%m.%Y"),
        "date_iso": _date_text(memo.date, "%Y-%m-%d"),
        "today": today.strftime("%Y-%m-%d"),
        "client": memo.client or "",
    }
    return {key: sanitize_value(value) for key, value in values.items()}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render(nodes, values):
    out = ""
    skip_space = False
    for kind, payload in nodes:
        if kind == "lit":
            text = sanitize_text(payload)
            if skip_space and text.startswith(" "):
                text = text[1:]
            skip_space = False
            out += text
        elif kind == "ph":
            value = values[payload]
            if value:
                out += value
                skip_space = False
            elif out.endswith(" "):
                out = out[:-1]
                skip_space = False
            else:
                skip_space = True
        else:
            names = [p for k, p in payload if k == "ph"]
            if all(values[name] for name in names):
                text = ""
                for sub_kind, sub in payload:
                    text += sanitize_text(sub) if sub_kind == "lit" else values[sub]
                if skip_space and text.startswith(" "):
                    text = text[1:]
                skip_space = False
                out += text
    return out


def _clean_stem(stem):
    """Trim, strip a typed ``.docx`` and trailing/leading dots and spaces, then cut (R-FN-6.3, 6.4)."""
    previous = None
    while previous != stem:
        previous = stem
        stem = stem.strip()
        if stem.lower().endswith(EXTENSION):
            stem = stem[: -len(EXTENSION)]
        stem = stem.strip(". ")
    stem = stem[:MAX_STEM_LENGTH].strip(". ")
    return stem


def _stem_for(pattern, values):
    nodes, errors = _parse(pattern)
    if errors:
        return ""
    return _clean_stem(_render(nodes, values))


def memo_export_filename(memo, settings, pattern=None, today=None):
    """The ``.docx`` file name for ``memo`` (design 8.3).

    ``pattern`` overrides ``settings.memo_filename_pattern`` (used by the live preview). A blank or
    invalid pattern, or one that renders to an empty stem, falls back to the default pattern.
    """
    if pattern is None:
        pattern = getattr(settings, "memo_filename_pattern", "") or ""
    values = placeholder_values(memo, settings, today)
    stem = ""
    if pattern.strip() and not validate_pattern(pattern):
        stem = _stem_for(pattern, values)
    if not stem:
        stem = _stem_for(DEFAULT_PATTERN, values)
    return stem + EXTENSION


# ---------------------------------------------------------------------------
# Content-Disposition (R-FN-6.8, R-EX-5)
# ---------------------------------------------------------------------------


def content_disposition(filename):
    """``attachment; filename="<ascii>"; filename*=UTF-8''<percent-encoded>`` for ``filename``."""
    fallback = "".join(
        "_" if (ord(c) > 126 or ord(c) < 32 or c in '"\\%') else c for c in filename
    )
    encoded = quote(filename, safe="", encoding="utf-8")
    return "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (fallback, encoded)
