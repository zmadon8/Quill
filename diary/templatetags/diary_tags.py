from django import template
from django.utils.safestring import mark_safe

from diary import numbering
from diary.richtext import sanitise_html

register = template.Library()


@register.filter
def dotted(label):
    """Contents panel only: 'A' -> 'A.', '1' -> '1.', 'Section 1' -> 'Section 1.'.

    Labels already closed by a bracket ('(a)'), a bullet or nothing are returned unchanged.
    """
    return numbering.display_label(label)


@register.filter
def richhtml(value):
    """Stored rich text on the way out: cleaned again to p, br, b, i, u only, then marked safe."""
    return mark_safe(sanitise_html(value or ""))
