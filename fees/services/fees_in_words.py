"""Convert a non-negative INR amount to Indian-English words (brief 7.2, R-EX-2).

Faithful port of ``feesInWordsService.ts``. Pure Python: standard-library
``decimal`` and ``math`` only, no Django imports.

Uses the Indian numbering system (crore / lakh / thousand / hundred). The output
is always ``"Rupees <words> Only"``, or ``"Rupees <words> and <paise> Paise Only"``
when there are paise. ``Thousand`` never pluralises; ``Crore``/``Lakh`` pluralise
above one. A negative amount raises ``ValueError`` (the TS threw ``RangeError``).

Examples:
    120000       -> "Rupees One Lakh Twenty Thousand Only"
    200000       -> "Rupees Two Lakhs Only"
    10000000.50  -> "Rupees One Crore and Fifty Paise Only"
    0            -> "Rupees Zero Only"
"""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal

__all__ = ["fees_in_words"]

_ONES = (
    "",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
)

_TENS = (
    "",
    "",
    "Twenty",
    "Thirty",
    "Forty",
    "Fifty",
    "Sixty",
    "Seventy",
    "Eighty",
    "Ninety",
)

_CENT = Decimal("0.01")


def _convert_hundreds(n: int) -> str:
    """Converts an integer 1-999 to words. Returns "" for 0."""
    if n == 0:
        return ""
    parts = []
    if n >= 100:
        parts.append(f"{_ONES[n // 100]} Hundred")
        n = n % 100
    if n > 0:
        if n < 20:
            parts.append(_ONES[n])
        else:
            tens = _TENS[n // 10]
            unit = _ONES[n % 10]
            parts.append(f"{tens} {unit}" if unit else tens)
    return " ".join(parts)


def _integer_to_words(n: int) -> str:
    """Converts a non-negative integer (up to 99,99,99,99,999) to Indian words."""
    if n == 0:
        return "Zero"
    parts = []

    crores = n // 10_000_000
    if crores > 0:
        parts.append(f"{_convert_hundreds(crores)} {'Crore' if crores == 1 else 'Crores'}")
        n = n % 10_000_000

    lakhs = n // 100_000
    if lakhs > 0:
        parts.append(f"{_convert_hundreds(lakhs)} {'Lakh' if lakhs == 1 else 'Lakhs'}")
        n = n % 100_000

    thousands = n // 1_000
    if thousands > 0:
        parts.append(f"{_convert_hundreds(thousands)} Thousand")
        n = n % 1_000

    if n > 0:
        parts.append(_convert_hundreds(n))

    return " ".join(parts)


def fees_in_words(amount) -> str:
    """Converts a non-negative INR ``amount`` to Indian-English words.

    Accepts int / float / str / Decimal. Rounds to two decimals (half up) using
    ``Decimal`` to avoid float noise, splits into rupees (floor) and paise
    (0-99), then renders. Raises ``ValueError`` for a negative amount.
    """
    value = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    if value < 0:
        raise ValueError("fees_in_words: amount must be non-negative")

    rounded = value.quantize(_CENT, rounding=ROUND_HALF_UP)
    rupees = int(math.floor(rounded))
    paise = int(((rounded - rupees) * 100).to_integral_value(rounding=ROUND_HALF_UP))

    rupee_words = _integer_to_words(rupees)

    if paise == 0:
        return f"Rupees {rupee_words} Only"

    paise_words = _convert_hundreds(paise)

    if rupees == 0:
        return f"Rupees Zero and {paise_words} Paise Only"

    return f"Rupees {rupee_words} and {paise_words} Paise Only"
