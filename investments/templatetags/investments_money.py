"""Template filters for the Auto / Full number display (plan 24.3).

``{{ value|inr }}`` renders a ``<span class="m">`` carrying both texts in ``data-auto`` and ``data-full``; the page's
toggle (static/js/investments/shell.js) swaps the visible text, and the exact amount is the tooltip. The initial text is
Auto, which is also what a printed page or a browser without JavaScript shows.
"""
from django import template
from django.utils.html import format_html

from investments.money_auto import AUTO, FULL, format_amount

register = template.Library()


def _span(value, currency, signed):
    if value is None or value == "":
        return format_html('<span class="m na">&ndash;</span>')
    auto = format_amount(value, currency=currency, mode=AUTO, signed=signed)
    full = format_amount(value, currency=currency, mode=FULL, signed=signed)
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
