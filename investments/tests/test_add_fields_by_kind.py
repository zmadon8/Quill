from django.test import SimpleTestCase
from django.urls import reverse

from investments import forms
from investments.models import Instrument
from investments.tests.base import InvTestCase

SHOWN = {
    "share": {"isin", "sector"},
    "fund": {"isin", "asset_class"},
    "foreign": {"currency"},
    "alternative": {"asset_class", "interest_rate", "interest_type", "maturity_date", "taxed_as_interest", "lump_sum"},
}
OPTIONAL = set(forms.InstrumentForm.FIELD_KINDS)


class AddFieldsByKindForm(SimpleTestCase):
    def test_each_kind_has_only_its_own_fields(self):
        for kind, shown in SHOWN.items():
            fields = set(forms.InstrumentForm(initial={"kind": kind}, kind=kind).fields)
            self.assertEqual(fields & OPTIONAL, shown, kind)
            self.assertTrue({"kind", "name", "code"} <= fields, kind)

    def test_kind_read_from_post_data(self):
        form = forms.InstrumentForm({"kind": "share", "name": "Infosys"})
        self.assertNotIn("lump_sum", form.fields)
        self.assertIn("sector", form.fields)

    def test_post_valid_without_removed_fields(self):
        for kind in SHOWN:
            form = forms.InstrumentForm({"kind": kind, "name": "X", "code": "", "asset_class": "equity", "interest_type": "compound"}, kind=kind)
            self.assertTrue(form.is_valid(), (kind, form.errors))

    def test_removed_fields_in_post_are_ignored(self):
        form = forms.InstrumentForm({"kind": "share", "name": "X", "lump_sum": "on", "interest_rate": "9", "currency": "USD"}, kind="share")
        self.assertTrue(form.is_valid())
        self.assertNotIn("lump_sum", form.cleaned_data)
        self.assertNotIn("currency", form.cleaned_data)

    def test_own_instrument_form_is_alternative_fields(self):
        fields = set(forms.OwnInstrumentForm().fields)
        self.assertEqual(fields & OPTIONAL, SHOWN["alternative"])
        self.assertNotIn("kind", fields)


class AddFieldsByKindPages(InvTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def get_names(self, kind):
        html = self.client.get(reverse("investments_add_2"), {"kind": kind}).content.decode()
        return {f for f in OPTIONAL if f'name="{f}"' in html}

    def test_pages_show_only_relevant_fields(self):
        for kind, shown in SHOWN.items():
            self.assertEqual(self.get_names(kind), shown, kind)

    def test_confirmed_post_uses_defaults_for_removed_fields(self):
        r = self.client.post(reverse("investments_add_2"), {"kind": "share", "name": "Infosys", "code": "INFY.NS", "confirmed": "1"})
        self.assertEqual(r.status_code, 302)
        inst = Instrument.objects.get(name="Infosys")
        self.assertEqual((inst.currency, inst.asset_class, inst.isin, inst.sector, inst.lump_sum), ("INR", "equity", "", "", False))
