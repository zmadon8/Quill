"""Template filters for the Auto / Full number display (plan 24.3).

``{{ value|inr }}`` renders a ``<span class="m">`` carrying both texts in ``data-auto`` and ``data-full``; the page's
toggle (static/js/investments/shell.js) swaps the visible text, and the exact amount is the tooltip. The initial text is
Auto, which is also what a printed page or a browser without JavaScript shows.
"""
import contextvars

from django import template
from django.utils.html import format_html

from investments.money_auto import AUTO, FULL, format_amount, format_units

register = template.Library()

#: The profile's decimals for this page ({"units": n or None, "rupees": n or None}), set by ``viewutil.page`` while it renders
#: (owner round 2026-11, Settings > Display). Elsewhere (exports, e-mails, tests) the standard rule applies.
DISPLAY = contextvars.ContextVar("investments_display", default={})


def _span(value, currency, signed):
    if value is None or value == "":
        return format_html('<span class="m na">&ndash;</span>')
    dec = DISPLAY.get().get("rupees") if currency == "INR" else None
    auto = format_amount(value, currency=currency, mode=AUTO, signed=signed)   # short figures: always up to 2 decimals
    full = format_amount(value, currency=currency, mode=FULL, signed=signed, decimals=dec)
    gain = ""
    if signed:
        gain = " g" if full.startswith("+") else (" l" if full.startswith("\u2212") else "")
    return format_html('<span class="m{}" data-auto="{}" data-full="{}" title="{}">{}</span>', gain, auto, full, full, auto)


@register.filter
def inr(value):
    """An amount in rupees, Auto or Full as the page toggle says."""
    return _span(value, "INR", False)


@register.filter
def inr_signed(value):
    """A gain or loss in rupees: ``+`` or a true minus first, then colour (plan 25.3)."""
    return _span(value, "INR", True)


@register.simple_tag
def money(value, currency="INR", signed=False):
    """``{% money value "USD" %}``: an amount in any currency."""
    return _span(value, currency, bool(signed))


def _pct(value, signed):
    if value is None or value == "":
        return format_html('<span class="na">n/a</span>')
    text = f"{abs(float(value)) * 100:.2f}"
    if signed:
        sign = "+" if float(value) > 0 else ("\u2212" if float(value) < 0 else "")
        cls = "g" if sign == "+" else ("l" if sign else "")
        return format_html('<span class="{}">{}{}%</span>', cls, sign, text)
    return format_html("{}{}%", "\u2212" if float(value) < 0 else "", text)


@register.filter
def pct(value):
    """A fraction as a percentage with two decimals (0.1234 is 12.34%); n/a for None."""
    return _pct(value, False)


@register.filter
def pct_signed(value):
    """A gain or loss as a signed percentage: + or a true minus first, then colour."""
    return _pct(value, True)


@register.filter
def units(value):
    """Units as a toggling ``<span class="m">``: Full is exact (no trailing zeros, or the decimals chosen in Settings > Display), Short is k / lac / cr from 1,000."""
    if value is None:
        return ""
    places = DISPLAY.get().get("units")
    auto = format_units(value, mode=AUTO, decimals=places)
    full = format_units(value, mode=FULL, decimals=places)
    return format_html('<span class="m" data-auto="{}" data-full="{}" title="{}">{}</span>', auto, full, full, auto)


@register.filter
def price(value):
    """A price per unit with at least two and at most four decimals, Indian grouping."""
    if value is None:
        return ""
    from decimal import Decimal

    from investments.money_auto import group_indian

    from decimal import ROUND_HALF_UP

    value = Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)   # an average cost can have many decimals
    text = f"{abs(value):f}"
    whole, _dot, frac = text.partition(".")
    frac = frac.rstrip("0")
    frac = (frac + "00")[:max(2, len(frac))]
    return ("\u2212" if value < 0 else "") + group_indian(whole) + "." + frac
