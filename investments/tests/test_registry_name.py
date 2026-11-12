"""The official NSE / AMFI name shown after the code on the investment page."""
from django.urls import reverse

from investments.models import AmfiScheme, NseSecurity
from investments.services import instrument_search, investment_page
from investments.tests.base import InvTestCase


class RegistryNameTests(InvTestCase):
    def page(self, inst):
        self.client.force_login(self.user)
        return self.client.get(reverse("investments_investment", args=[inst.pk])).content.decode()

    def test_share_shows_nse_name_without_suffix(self):
        NseSecurity.objects.create(symbol="RELIANCE", name="Reliance Industries Limited", isin="INE002A01018", series="EQ")
        html = self.page(self.reliance)
        self.assertIn("Reliance Industries Limited", html)
        self.assertIn("data-registry-name", html)

    def test_bse_suffix_is_ignored(self):
        NseSecurity.objects.create(symbol="RELIANCE", name="Reliance Industries Limited")
        self.reliance.code = "RELIANCE.BO"
        self.assertEqual(investment_page.registry_record(self.reliance)["name"], "Reliance Industries Limited")

    def test_fund_shows_amfi_name(self):
        AmfiScheme.objects.create(code="122639", name="Parag Parikh Flexi Cap Fund - Direct Plan - Growth")
        self.assertIn("Parag Parikh Flexi Cap Fund - Direct Plan - Growth", self.page(self.fund))

    def test_no_match_is_graceful(self):
        html = self.page(self.reliance)
        self.assertNotIn("data-registry-name", html)
        self.assertIsNone(investment_page.registry_record(self.reliance))

    def test_lookup_off_hides_it(self):
        NseSecurity.objects.create(symbol="RELIANCE", name="Reliance Industries Limited")
        instrument_search.set_lookup_enabled(False)
        self.assertIsNone(investment_page.registry_record(self.reliance))

    def test_isin_mismatch_flagged(self):
        NseSecurity.objects.create(symbol="RELIANCE", name="Reliance Industries Limited", isin="INE002A01018")
        self.reliance.isin = "INE000000000"
        self.assertTrue(investment_page.registry_record(self.reliance)["mismatch"])
