"""Return, CAGR and XIRR are always named, with their basis (D185)."""
from datetime import date as d
from decimal import Decimal as D

from django.test import SimpleTestCase
from django.urls import reverse

from investments import measures
from investments.models import Instrument, Price
from investments.services import holdings, investment_page, reports
from investments.tests.base import InvTestCase


class MeasureWordingTests(SimpleTestCase):
    def test_basis_names_cagr_or_the_days(self):
        self.assertEqual(measures.basis(516, True), "CAGR")
        self.assertEqual(measures.basis(180, False), "over 180 days")
        self.assertEqual(measures.basis(1, False), "over 1 day")

    def test_every_measure_has_a_tooltip(self):
        for key in ("return", "cagr", "xirr", "alpha", "legend"):
            self.assertTrue(measures.TIPS[key], key)
        self.assertNotIn("\u2014", "".join(measures.TIPS.values()))


class MeasureLabelPageTests(InvTestCase):
    def setUp(self):
        super().setUp()
        nifty = Instrument.objects.get(code="^NSEI")
        for day, n, r in ((d(2023, 1, 2), 100, 50), (d(2024, 1, 2), 110, 75), (d(2024, 6, 1), 115, 80)):
            Price.objects.create(instrument=nifty, date=day, close=D(n), source="api")
            Price.objects.create(instrument=self.reliance, date=day, close=D(r), source="api")
        self.buy(d(2023, 1, 2), 10, 50)
        self.buy(d(2024, 1, 2), 10, 75)

    def test_lot_rows_carry_their_basis(self):
        (h,), _ = holdings.compute(self.profile, as_of=d(2024, 6, 1))
        held, _sold = investment_page.purchase_rows(self.profile, self.reliance, h, d(2024, 6, 1))
        self.assertEqual([r["basis"] for r in held], ["CAGR", "over 151 days"])

    def test_investment_page_headings_and_cells_name_the_measure(self):
        self.client.force_login(self.user)
        html = self.client.get(reverse("investments_investment", args=[self.reliance.pk]) + "?on=2024-06-01").content.decode()
        self.assertIn("Return since bought</th>", html)
        self.assertIn("Index, same basis</th>", html)
        self.assertIn("XIRR (a year)</div>", html)
        self.assertIn(measures.LEGEND, html)

    def test_holdings_and_year_by_year_headings(self):
        self.client.force_login(self.user)
        html = self.client.get(reverse("investments_holdings")).content.decode()
        self.assertIn("XIRR (a year)</th>", html)
        self.assertIn(measures.LEGEND, html)
        names = [c[0] for c in reports.yearly(self.profile).columns]
        self.assertEqual(names[-3:], ["XIRR (a year)", "Index change over the year", "Difference"])
        self.assertEqual(reports.yearly(self.profile).has_measures, True)
