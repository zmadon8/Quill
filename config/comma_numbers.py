"""Number boxes that accept Indian or Western grouping ("1,23,456.50", "12 34 567", "\u20b9 5") so nothing breaks whether or not
static/js/number-commas.js is on. The widgets are text boxes with an ``inputmode`` so the commas can show."""
import re

from django import forms

_NOISE = re.compile(r"[,\s\u00a0\u20b9]")


def plain_number(value):
    """``value`` without commas, spaces and the rupee sign; anything that is not text is returned as it is."""
    return _NOISE.sub("", value) if isinstance(value, str) else value


class _CommaMixin:
    inputmode = "decimal"

    def to_python(self, value):
        return super().to_python(plain_number(value))

    def widget_attrs(self, widget):
        attrs = super().widget_attrs(widget)
        attrs["inputmode"] = self.inputmode
        return attrs


class CommaDecimalField(_CommaMixin, forms.DecimalField):
    widget = forms.TextInput


class CommaIntegerField(_CommaMixin, forms.IntegerField):
    widget = forms.TextInput
    inputmode = "numeric"
