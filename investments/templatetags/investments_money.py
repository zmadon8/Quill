"""Template filters for the Auto / Full number display (plan 24.3).

``{{ value|inr }}`` renders a ``<span class="m">`` carrying both texts in ``data-auto`` and ``data-full``; the page's
toggle (static/js/investments/shell.js) swaps the visible text, and the exact amount is the tooltip. The initial text is
Auto, which is also what a printed page or a browser without JavaScript shows.
"""

from django import template
from django.utils.html import format_html

from investments import measures
from investments.money_auto import AUTO, FULL, format_amount, format_units

register = template.Library()

def _span(value, currency, signed):
    if value is None or value == "":
        return format_html('<span class="m na">&ndash;</span>')
    auto = format_amount(value, currency=currency, mode=AUTO, signed=signed)
    full = format_amount(value, currency=currency, mode=FULL, signed=signed)   # rupees: up to 2 decimals, trailing zeros dropped
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


def _trim(number, places):
    """``number`` (non-negative) to at most ``places`` decimals, half up, trailing zeros and a bare point dropped, Indian grouping."""
    from decimal import ROUND_HALF_UP, Decimal

    from investments.money_auto import group_indian

    q = Decimal(str(number)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    whole, _dot, frac = f"{q:f}".partition(".")
    frac = frac.rstrip("0")
    return group_indian(whole) + ("." + frac if frac else "")


def _pct_parts(value):
    """``(sign, shown, exact)`` of a fraction as a percentage: shown with at most 2 decimals and no trailing zeros, exact to 6."""
    v = float(value)
    sign = "\u2212" if v < 0 and _trim(abs(v) * 100, 2) != "0" else ""
    return sign, _trim(abs(v) * 100, 2), _trim(abs(v) * 100, 6)


def _pct(value, signed):
    if value is None or value == "":
        return format_html('<span class="na">n/a</span>')
    sign, text, exact = _pct_parts(value)
    if signed:
        sign = "+" if float(value) > 0 and text != "0" else sign
        cls = "g" if sign == "+" else ("l" if sign else "")
        return format_html('<span class="{}" title="{}{}%">{}{}%</span>', cls, sign, exact, sign, text)
    return format_html('<span title="{}{}%">{}{}%</span>', sign, exact, sign, text)


@register.filter
def pct_text(value):
    """The same percentage as plain text, for inside an attribute (an aria-label or a title)."""
    if value is None or value == "":
        return "n/a"
    sign, text, _exact = _pct_parts(value)
    return f"{sign}{text}%"


@register.filter
def inr_text(value):
    """A rupee amount as plain Full text, for inside an attribute (a title)."""
    if value is None or value == "":
        return ""
    return format_amount(value, currency="INR", mode=FULL)


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
    """Units as a toggling ``<span class="m">``: Full is up to 2 decimals with trailing zeros dropped (as the Fee Register), Short is k / lac / cr
    from 1,000."""
    if value is None:
        return ""
    auto = format_units(value, mode=AUTO)
    full = format_units(value, mode=FULL)
    from decimal import Decimal

    exact = Decimal(str(value))
    exact_text = ("-" if exact < 0 and _trim(abs(exact), 6) != "0" else "") + _trim(abs(exact), 6)   # pointing at it: every decimal stored
    return format_html('<span class="m" data-auto="{}" data-full="{}" title="{}">{}</span>', auto, full, exact_text, auto)


@register.filter
def price(value):
    """A price per unit: at most two decimals, trailing zeros dropped, Indian grouping (owner round 2026-12). Pointing at it shows the
    exact figure (up to six decimals, as an average cost can have many)."""
    if value is None:
        return ""
    from decimal import Decimal

    value = Decimal(value)
    shown, exact = _trim(abs(value), 2), _trim(abs(value), 6)
    sign = "\u2212" if value < 0 and shown != "0" else ""
    return format_html('<span class="m" title="{}{}">{}{}</span>', sign, exact, sign, shown)


@register.filter
def measure_tip(key):
    """The tooltip for a measure heading: ``"return"``, ``"cagr"``, ``"xirr"`` or ``"alpha"`` (wording in ``investments.measures``)."""
    return measures.TIPS.get(key, "")


@register.filter
def heading_tip(heading):
    """The tooltip for a column heading that names XIRR, CAGR or Alpha ("" for any other heading)."""
    for key in ("XIRR", "CAGR", "Alpha"):
        if key in heading:
            return measures.TIPS[key.lower()]
    return ""
