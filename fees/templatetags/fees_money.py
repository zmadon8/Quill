"""Template filters for money and dates (design section 3). They only format; they compute nothing."""
from django import template

from fees.services.money import format_date, format_money

register = template.Library()


@register.filter
def fees_money(value, unit="full"):
    """A figure in Indian grouping. ``unit`` is ``full`` (default) or ``truncated`` (lac and crore suffixes)."""
    if value is None or value == "":
        return ""
    return format_money(value, unit=unit or "full")


@register.filter
def fees_date(value):
    """A date as DD.MM.YYYY; blank for none."""
    if not value:
        return ""
    return format_date(value)
