"""Owner round 2026-11: 90-day trend lines in the holdings tables and the price chart's range buttons."""
from datetime import date as d, timedelta
from decimal import Decimal as D

from django.urls import reverse

from investments.models import Price
from investments.services import prices
from investments.svgchart import sparkline
from investments.tests.base import InvTestCase


class SparklineTests(InvTestCase):
    def test_sparkline_shape_and_direction(self):
        self.assertIsNone(sparkline([]))
        self.assertIsNone(sparkline([5]))
        up = sparkline([1, 2, 3])
        self.assertTrue(up["up"])
        self.assertEqual(len(up["points"].split()), 3)
        self.assertAlmostEqual(up["change"], 2.0)
        self.assertFalse(sparkline([3, 2, 1])["up"])
        self.assertTrue(sparkline([2, 2])["up"])          # a flat line does not divide by zero

    def test_recent_closes_is_oldest_first_and_thinned(self):
        today = d(2026, 11, 9)
        for n in range(80):
            Price.objects.create(instrument=self.reliance, date=today - timedelta(days=n), close=D(100 + n), source="api")
        closes = prices.recent_closes([self.reliance.pk, self.fund.pk], today, days=90, points=30)
        self.assertEqual(list(closes), [self.reliance.pk])
        self.assertEqual(len(closes[self.reliance.pk]), 30)
        self.assertEqual(closes[self.reliance.pk][0], D(179))   # the oldest close first
        self.assertEqual(closes[self.reliance.pk][-1], D(100))


class PageTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.buy(d(2024, 1, 1), 10, 100)
        today = d.today()
        for n in range(10):
            Price.objects.create(instrument=self.reliance, date=today - timedelta(days=n), close=D(100 + n), source="api")

    def test_holdings_have_the_90_day_column_and_the_overview_no_longer_does(self):
        page = self.client.get(reverse("investments_holdings")).content.decode()
        self.assertIn('data-col="spark">90 days</th>', page)
        self.assertIn('<svg class="spark down"', page)       # the closes fall towards today
        self.assertNotIn("90 days</th>", self.client.get(reverse("investments_dashboard")).content.decode())

    def test_price_chart_range_buttons(self):
        url = reverse("investments_investment", args=[self.reliance.pk])
        page = self.client.get(url).content.decode()
        self.assertIn('aria-label="Price range"', page)
        for label in ("1M", "3M", "6M", "1Y", "3Y", "5Y", "All"):
            self.assertIn(f">{label}</a>", page)
        self.assertIn('class="on" aria-current="true">1Y</a>', page)
        page = self.client.get(url + "?range=6m").content.decode()
        self.assertIn('class="on" aria-current="true">6M</a>', page)
        page = self.client.get(url + "?range=all").content.decode()
        self.assertIn('class="on" aria-current="true">All</a>', page)
        page = self.client.get(url + "?days=30").content.decode()      # the older links still work
        self.assertIn('class="on" aria-current="true">1M</a>', page)
