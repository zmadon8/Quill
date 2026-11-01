from django import template

register = template.Library()


@register.filter
def dotted(label):
    """Contents panel only: 'A' -> 'A.', '1' -> '1.', 'Section 1' -> 'Section 1.'.

    Labels already closed by a bracket ('(a)'), a bullet or nothing are returned unchanged.
    """
    label = str(label or "")
    if label and label[-1].isalnum():
        return label + "."
    return label
