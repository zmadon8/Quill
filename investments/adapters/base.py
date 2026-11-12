"""What every price adapter returns (plan 15.2): `(date, close)` pairs and, where the source offers them, split and dividend events."""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


class FetchError(Exception):
    """A source refused or could not answer. ``retryable`` is true for 429, 5xx and network errors."""

    def __init__(self, message, status=None, retryable=False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class FormatError(FetchError):
    """The answer arrived but could not be read with the format on file: columns missing, or nothing parsed from a body that was not empty.
    ``key`` is the source format (``services/source_formats.py``) an Admin can correct; it makes the failure show on the alerts page."""

    def __init__(self, message, key="", missing=(), headers=()):
        super().__init__(message)
        self.key = key
        self.missing = list(missing)
        self.headers = list(headers)


@dataclass
class Result:
    rows: list = field(default_factory=list)          # [(date, Decimal close)] oldest first, positive closes only
    splits: list = field(default_factory=list)        # [(date, numerator, denominator)]
    dividends: list = field(default_factory=list)     # [(date, Decimal per unit)]
    name: str = ""
    currency: str = ""
    exchange: str = ""
    rejected: int = 0                                  # rows dropped (zero, negative or missing price)


def clean_close(value):
    """A positive Decimal close, or None (zero, negative, missing and non-numeric prices are rejected; plan 15.2)."""
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except Exception:
        return None
    return number if number.is_finite() and number > 0 else None


DAY_FORMATS = ("%d-%m-%Y", "%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y")


def parse_day(text, formats=DAY_FORMATS):
    """A date from ``DD-MM-YYYY``, ``DD-Mon-YYYY`` or ``YYYY-MM-DD`` (or the given ``formats``); None when unreadable."""
    from datetime import datetime

    for fmt in formats:
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def too_old(day: date, since):
    return since is not None and day < since
