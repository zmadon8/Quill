"""Editing the interest rate, type and maturity date of an existing alternative investment (Your details)."""
from datetime import date as d
from decimal import Decimal as D

from django.urls import reverse

from investments.errors import InvestmentsError
from investments.models import CatalogueHistory, InvestmentSettings
from investments.services import holdings, masters
from investments.tests.base import InvTestCase


class AltInterestEditTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.fd = masters.create_instrument(self.profile, self.user, kind="alternative", name="Bank FD", asset_class="debt")
        self.buy(d(2023, 1, 1), 1, 100000, instrument=self.fd)
        self.client.force_login(self.user)
        self.url = reverse("investments_investment_details", args=[self.fd.pk])

    def _post(self, **extra):
        data = {"action": "save", "notes": "", "links": "", **extra}
        return self.client.post(self.url, data)

    def test_fields_only_on_alternative_pages(self):
        page = self.client.get(reverse("investments_investment", args=[self.fd.pk]))
        for name in ("interest_rate", "interest_type", "maturity_date"):
            self.assertContains(page, f'name="{name}"')
        share = self.client.get(reverse("investments_investment", args=[self.reliance.pk]))
        self.assertNotContains(share, 'name="interest_rate"')

    def test_add_and_change_interest(self):
        before = InvestmentSettings.objects.get(profile=self.profile).data_version
        self._post(interest_rate="8", interest_type="simple", maturity_date="2025-01-01")
        self.fd.refresh_from_db()
        self.assertEqual(self.fd.interest_rate, D("8"))
        self.assertEqual(self.fd.interest_type, "simple")
        self.assertEqual(self.fd.maturity_date, d(2025, 1, 1))
        self.assertGreater(InvestmentSettings.objects.get(profile=self.profile).data_version, before)
        (h,), _ = holdings.compute(self.profile, as_of=d(2024, 1, 1))
        self.assertAlmostEqual(float(h.value), 100000 * (1 + 0.08 * 365 / 365), places=0)
        rows = CatalogueHistory.objects.filter(instrument_id_ref=self.fd.pk, field="interest_rate")
        self.assertEqual((rows.count(), rows[0].new), (1, "8"))
        self._post(interest_rate="8", interest_type="compound", maturity_date="2025-01-01")
        self.fd.refresh_from_db()
        self.assertEqual(self.fd.interest_type, "compound")
        self.assertEqual(CatalogueHistory.objects.filter(instrument_id_ref=self.fd.pk, field="interest_rate").count(), 1)
        self.assertEqual(CatalogueHistory.objects.filter(instrument_id_ref=self.fd.pk, field="interest_type").count(), 2)
        self._post(interest_rate="", interest_type="compound", maturity_date="")
        self.fd.refresh_from_db()
        self.assertIsNone(self.fd.interest_rate)
        self.assertIsNone(self.fd.maturity_date)

    def test_share_cannot_take_interest(self):
        self.client.post(reverse("investments_investment_details", args=[self.reliance.pk]),
                         {"action": "save", "notes": "", "links": "", "interest_rate": "9", "interest_type": "simple"})
        self.reliance.refresh_from_db()
        self.assertIsNone(self.reliance.interest_rate)
        with self.assertRaises(InvestmentsError):
            masters.update_alt_interest(self.profile, self.user, self.reliance, interest_rate=D(9), interest_type="simple", maturity_date=None)


class AltInterestFollowUpTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.fd = masters.create_instrument(self.profile, self.user, kind="alternative", name="Bank FD", asset_class="debt",
                                            interest_rate=D(8), interest_type="compound")
        self.client.force_login(self.user)
        self.url = reverse("investments_investment_details", args=[self.fd.pk])

    def test_invalid_form_shows_errors_and_keeps_values(self):
        self.buy(d(2023, 1, 1), 1, 100000, instrument=self.fd)
        resp = self.client.post(self.url, {"action": "save", "notes": "keep me", "links": "", "interest_rate": "-3", "interest_type": "simple"},
                                follow=True)
        self.assertContains(resp, "Interest rate")
        self.assertContains(resp, "keep me")
        self.fd.refresh_from_db()
        self.assertEqual(self.fd.interest_rate, D(8))

    def test_rate_above_limit_refused_by_form_and_saves_nothing(self):
        self.buy(d(2023, 1, 1), 1, 100000, instrument=self.fd)
        self.client.post(self.url, {"action": "save", "notes": "n1", "links": "", "interest_rate": "1500", "interest_type": "simple"})
        self.fd.refresh_from_db()
        self.assertEqual(self.fd.interest_rate, D(8))
        pi = masters.get_profile_investment(self.profile, self.fd)
        self.assertNotEqual(pi.notes, "n1")

    def test_form_limits_match_service(self):
        from investments import forms

        self.assertEqual(forms.DetailsForm(with_sector=False).fields["interest_rate"].max_value, 1000)
        self.assertEqual(forms.InstrumentForm().fields["interest_rate"].max_value, 1000)

    def test_chart_matches_holdings_after_partial_sale(self):
        from investments.services import series

        self.buy(d(2023, 1, 1), 10, 1000, instrument=self.fd)
        self.buy(d(2023, 7, 1), 10, 3000, instrument=self.fd)
        self.sell(d(2023, 9, 1), 5, 2000, instrument=self.fd)
        end = d(2024, 3, 1)
        (h,), _ = holdings.compute(self.profile, as_of=end)
        values, _flows = series.portfolio_value_series(self.profile, [end])
        # holdings value is the position; the series adds nothing else for an alternative, so the two must agree
        self.assertEqual(values[0], h.value)

    def test_remaining_lots_is_fifo(self):
        from investments import valuation

        left = valuation.remaining_lots([(d(2023, 7, 1), D(10), D(30000)), (d(2023, 1, 1), D(10), D(10000))], D(15))
        self.assertEqual(left, [(d(2023, 1, 1), D(5000)), (d(2023, 7, 1), D(30000))])
