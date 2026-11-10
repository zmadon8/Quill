"""The Auto / Full number display for the Investments program (plan section 24.3).

Pure Python, no Django imports. ``static/js/investments/money_auto.js`` mirrors it, and both are tested against the
one golden table ``investments/tests/golden/money_auto.json``.

Rules (owner decisions, plan 24.3 and the owner round of November 2026):

* Full: the complete amount, Indian grouping for rupees (``₹24,12,600``). Whole rupees show no decimals; an amount
  with paise shows two (``₹950.50``).
* Short (stored as ``auto``), rupees: exactly the Fee Register's short figures (``fees.services.money.format_money``
  with the standard suffixes): below 10 the whole rupees; below 1 lakh thousands (``k``); below 1 crore lacs (``lac``);
  otherwise crores (``cr``), with up to 2 decimals and trailing zeros dropped (``₹2.41 cr``, ``₹24.13 lac``,
  ``₹85.4k``, ``₹0.95k``). A suffix longer than one letter is set off by a space.
* Foreign amounts in Short: ``k`` and ``m`` (millions) with 2 decimals, below 1,000 the full amount; a figure that
  rounds up to the next unit is shown in that unit.
* Rounding is half away from zero on the exact amount. Negative amounts use a true minus sign before the symbol
  (``−₹60.30 k``); ``signed=True`` also puts ``+`` before a positive amount (gains).
* Foreign amounts: Auto uses ``k`` and ``m`` (millions), Full shows the whole amount with Western grouping.

Assumptions I made where the plan is silent are recorded in docs/DESIGN.md (D101 onwards).
"""
from decimal import ROUND_HALF_UP, Decimal

__all__ = ["format_amount", "format_rupees", "group_indian", "group_western", "AUTO", "FULL"]

AUTO = "auto"
FULL = "full"

MINUS = "\u2212"
RUPEE = "\u20b9"

_CENT = Decimal("0.01")
_ZERO = Decimal(0)

#: (divisor, suffix) from small to large, per currency family.
_INR_UNITS = ((Decimal(1), ""), (Decimal(1000), "k"), (Decimal(100000), "lac"), (Decimal(10000000), "cr"))
_FOREIGN_UNITS = ((Decimal(1), ""), (Decimal(1000), "k"), (Decimal(1000000), "m"))

_SYMBOLS = {"INR": RUPEE, "USD": "$", "EUR": "\u20ac", "GBP": "\u00a3", "JPY": "\u00a5"}


def _dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(str(value).strip())


def _round2(value):
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def group_indian(digits):
    """``"1234567"`` to ``"12,34,567"``: the last three digits, then pairs."""
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


def group_western(digits):
    """``"1234567"`` to ``"1,234,567"``."""
    out = []
    while len(digits) > 3:
        out.insert(0, digits[-3:])
        digits = digits[:-3]
    out.insert(0, digits)
    return ",".join(out)


def _plain(amount, grouper):
    """``amount`` (already rounded to 2 places, non-negative) as grouped text; paise only when there are some."""
    whole, frac = divmod(int(amount * 100), 100)
    text = grouper(str(whole))
    return text if frac == 0 else f"{text}.{frac:02d}"


def _sign(negative, signed, is_zero):
    if negative and not is_zero:
        return MINUS
    return "+" if signed and not negative and not is_zero else ""


def _fee_register_short(exact):
    """``(text, is zero)`` for a non-negative rupee amount, as the Fee Register's short figures show it: up to 2 decimals, trailing
    zeros dropped (the decimals setting is for full figures only)."""
    places = 2
    if exact < 10:
        whole = int(exact.quantize(Decimal(1), rounding=ROUND_HALF_UP))
        return group_indian(str(whole)), whole == 0
    for limit, divisor, suffix in ((Decimal(100000), Decimal(1000), "k"), (Decimal(10000000), Decimal(100000), "lac"), (None, Decimal(10000000), "cr")):
        if limit is None or exact < limit:
            step = Decimal(1).scaleb(-places)
            scaled = (exact / divisor).quantize(step, rounding=ROUND_HALF_UP)
            whole, _dot, frac = f"{scaled:f}".partition(".")
            frac = frac.rstrip("0")
            text = group_indian(whole) + ("." + frac if frac else "")
            return text + (" " if len(suffix) > 1 else "") + suffix, False
    raise AssertionError("unreachable")


def _fixed(amount, places, grouper):
    """A non-negative amount with exactly ``places`` decimals."""
    q = amount.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    whole, _dot, frac = f"{q:f}".partition(".")
    return grouper(whole) + ("." + frac if places else "")


def format_amount(value, *, currency="INR", mode=AUTO, signed=False, symbol=None, decimals=None):
    """Format ``value`` (Decimal, int, float or numeric string) for display.

    ``currency`` is ``"INR"`` (rupees: Indian grouping, k / lac / cr) or any other code (k / m, Western grouping).
    ``mode`` is ``"auto"`` or ``"full"``. ``signed`` adds ``+`` to positive amounts. ``symbol`` overrides the
    currency's symbol (an unknown code with no symbol is shown as ``"CODE "``). ``decimals`` (Settings > Display, 0 to 2) fixes the
    decimals of a full amount; short figures always show up to 2. None keeps the standard rule.
    """
    amount = _dec(value)
    negative = amount < _ZERO
    rupees = currency == "INR"
    grouper = group_indian if rupees else group_western
    sym = symbol if symbol is not None else _SYMBOLS.get(currency, f"{currency} ")
    magnitude = _round2(abs(amount))
    if rupees and mode != FULL:
        body, is_zero = _fee_register_short(abs(amount))
        return f"{_sign(negative, signed, is_zero)}{sym}{body}"
    if mode == FULL and decimals is not None:
        places = max(0, min(int(decimals), 2))
        body = _fixed(abs(amount), places, grouper)
        return f"{_sign(negative, signed, set(body) <= set('0,.'))}{sym}{body}"
    sign = _sign(negative, signed, magnitude == _ZERO)
    if mode == FULL or magnitude < Decimal(1000):
        return f"{sign}{sym}{_plain(magnitude, grouper)}"
    units = _INR_UNITS if rupees else _FOREIGN_UNITS
    exact = abs(amount)
    index = 0
    for i, (divisor, _suffix) in enumerate(units):
        if exact >= divisor:
            index = i
    scaled = _round2(exact / units[index][0])
    # A figure that rounds up to the next unit moves into it (99.999 lac is 1.00 cr, 999.996 is 1.00 k).
    while index + 1 < len(units) and scaled * units[index][0] >= units[index + 1][0]:
        index += 1
        scaled = _round2(exact / units[index][0])
    suffix = units[index][1]
    if not suffix:
        return f"{sign}{sym}{_plain(scaled, grouper)}"
    return f"{sign}{sym}{scaled:.2f} {suffix}"


def format_rupees(value, *, mode=AUTO, signed=False):
    """Rupee amount in the chosen mode (see :func:`format_amount`)."""
    return format_amount(value, currency="INR", mode=mode, signed=signed)
