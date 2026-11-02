"""Small parsers for query-string values."""


def safe_int(raw):
    """Return int(raw) for plain ASCII digits, else None. Unicode digits such as a superscript two are refused."""
    if not isinstance(raw, str) or not raw.isascii() or not raw.isdigit():
        return None
    try:
        return int(raw)
    except ValueError:
        return None
