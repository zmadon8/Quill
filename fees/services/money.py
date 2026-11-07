"""Money and date formatting for the Fee Register (design section 3).

Pure Python: standard-library ``decimal`` and ``datetime`` only, no Django
imports, so the module imports cheaply and can be unit-tested as plain logic.

Public functions:

* ``round2(x)`` rounds any numeric input to two decimals, half away from zero.
* ``format_currency(n)`` renders an integer with Indian digit grouping and no
  symbol, e.g. ``1234567 -> "12,34,567"``.
* ``format_date(d)`` renders a date (or ISO ``YYYY-MM-DD`` string) as
  ``DD.MM.YYYY``.
* ``format_money(value, unit=..., ...)`` ports the renderer's ``formatMoney`` /
  ``formatMoneyUnit``: ``"full"`` is the grouped integer; any other unit is the
  truncated magnitude form with k / lac / cr suffixes. The caller adds the
  rupee symbol.

The same grouping algorithm is mirrored, deliberately tiny, in
``static/js/fees/money.js``; this module is the source of truth and the golden
table in ``fees/tests/fixtures/money_cases.json`` runs against it.
"""
from __future__ import annotations

import datetime
from decimal import ROUND_HALF_UP, Decimal

__all__ = [
    "round2",
    "format_currency",
    "format_date",
    "format_money",
    "DEFAULT_SUFFIX_THOUSANDS",
    "DEFAULT_SUFFIX_LAC",
    "DEFAULT_SUFFIX_CRORE",
]

DEFAULT_SUFFIX_THOUSANDS = "k"
DEFAULT_SUFFIX_LAC = "lac"
DEFAULT_SUFFIX_CRORE = "cr"

_CENT = Decimal("0.01")


def _to_decimal(x) -> Decimal:
    """Coerces an int/str/Decimal/float to Decimal without binary float noise.

    Floats are converted through ``str`` so that, e.g., ``0.1`` reads as
    ``Decimal("0.1")`` rather than its binary expansion (design 3: money never
    travels as a float, and the Excel reader converts via ``Decimal(repr(...))``).
    """
    if isinstance(x, Decimal):
        return x
    if isinstance(x, float):
        return Decimal(str(x))
    return Decimal(x)


def round2(x) -> Decimal:
    """Rounds ``x`` to two decimal places, half away from zero (ROUND_HALF_UP).

    ``ROUND_HALF_UP`` in Python rounds a tie away from zero, matching the brief's
    "round half away from zero" and the original ``Math.round((x)*100)/100`` for
    non-negative amounts.
    """
    return _to_decimal(x).quantize(_CENT, rounding=ROUND_HALF_UP)


def _group_indian(digits: str) -> str:
    """Groups a string of digits in the Indian style: last 3, then pairs."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


def format_currency(n) -> str:
    """Rounds to an integer and renders with Indian grouping, no symbol.

    Negatives keep a single leading minus, e.g. ``-1234567 -> "-12,34,567"``.
    """
    value = int(round2(n).to_integral_value(rounding=ROUND_HALF_UP))
    sign = "-" if value < 0 else ""
    return sign + _group_indian(str(abs(value)))


def format_date(d) -> str:
    """Formats a ``date``/``datetime`` or ISO ``YYYY-MM-DD`` string as DD.MM.YYYY."""
    if isinstance(d, datetime.datetime):
        d = d.date()
    if isinstance(d, datetime.date):
        return f"{d.day:02d}.{d.month:02d}.{d.year:04d}"
    text = str(d)
    year, month, day = text[:10].split("-")
    return f"{int(day):02d}.{int(month):02d}.{int(year):04d}"


def _trim_decimals(value: Decimal) -> str:
    """Renders ``value`` with up to 2 decimals (trailing zeros trimmed), Indian grouping.

    Mirrors ``toLocaleString('en-IN', { maximumFractionDigits: 2 })`` on the
    scaled magnitude: round half-up to 2 dp, drop trailing zeros, then group the
    integer part Indian-style. The sign is preserved.
    """
    sign = "-" if value < 0 else ""
    quantized = abs(value).quantize(_CENT, rounding=ROUND_HALF_UP)
    whole = int(quantized)
    frac = (quantized - whole) * 100
    frac_int = int(frac.to_integral_value(rounding=ROUND_HALF_UP))
    grouped = _group_indian(str(whole))
    if frac_int == 0:
        return sign + grouped
    frac_text = f"{frac_int:02d}".rstrip("0")
    return f"{sign}{grouped}.{frac_text}"


def _scaled(value: Decimal, divisor: Decimal, suffix: str) -> str:
    text = _trim_decimals(value / divisor)
    stripped = suffix.strip()
    joiner = " " if len(stripped) > 1 else ""
    return f"{text}{joiner}{stripped}"


def format_money(
    value,
    *,
    unit: str = "full",
    suffix_thousands: str = DEFAULT_SUFFIX_THOUSANDS,
    suffix_lac: str = DEFAULT_SUFFIX_LAC,
    suffix_crore: str = DEFAULT_SUFFIX_CRORE,
) -> str:
    """Formats a figure for the chosen display mode (ports formatMoneyUnit).

    ``unit="full"`` renders the grouped integer (``format_currency``). Any other
    unit value reads as truncated: ``|v| < 10`` shows the rounded integer;
    ``< 1,00,000`` scales by 1e3 with the thousands suffix; ``< 1,00,00,000`` by
    1e5 with the lac suffix; otherwise by 1e7 with the crore suffix. Negatives
    scale by magnitude. The rupee symbol is added by the caller, never here.
    """
    if value is None:
        value = 0
    v = _to_decimal(value)
    if unit == "full":
        return format_currency(v)
    abs_v = abs(v)
    if abs_v < 10:
        return format_currency(v)
    if abs_v < 100_000:
        return _scaled(v, Decimal(1_000), suffix_thousands)
    if abs_v < 10_000_000:
        return _scaled(v, Decimal(100_000), suffix_lac)
    return _scaled(v, Decimal(10_000_000), suffix_crore)
