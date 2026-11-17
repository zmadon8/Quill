"""Reports > Charts: the moving average drawn beside each line (owner round 2026-12)."""
from datetime import date as d, timedelta
from decimal import Decimal as D

from django.urls import reverse

from investments.models import Instrument, Price
from investments.services import series
from investments.svgchart import line_chart
from investments.tests.base import InvTestCase


class MovingAverageTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.nifty = Instrument.objects.get(code="^NSEI")
        # 10 closes, 1 to 10, one a day from 1 Jan 2024.
        for n in range(10):
            Price.objects.create(instrument=self.nifty, date=d(2024, 1, 1) + timedelta(days=n), close=D(n + 1), source="api")

    def test_the_average_of_the_last_closes_rebased_like_its_line(self):
        days = [d(2024, 1, 3), d(2024, 1, 6), d(2024, 1, 10)]
        (_inst, line), = series.price_lines([self.nifty], days)
        avg = series.moving_average_line(self.nifty, days, 3)
        base = 3.0   # the line's first sample close
        self.assertAlmostEqual(float(line[0]), 100.0)
        self.assertAlmostEqual(avg[0], (1 + 2 + 3) / 3 / base * 100)
        self.assertAlmostEqual(avg[1], (4 + 5 + 6) / 3 / base * 100)
        self.assertAlmostEqual(avg[2], (8 + 9 + 10) / 3 / base * 100)

    def test_no_average_until_enough_closes(self):
        avg = series.moving_average_line(self.nifty, [d(2024, 1, 2), d(2024, 1, 10)], 5)
        self.assertIsNone(avg[0])
        self.assertIsNotNone(avg[1])

    def test_sampled_average_of_a_line_without_daily_closes(self):
        days = [d(2024, 1, 1) + timedelta(days=n) for n in range(10)]
        values = [None, None] + [float(n) for n in range(8)]
        out = series.sampled_moving_average(days, values, 2)   # 2 trading days is 3 calendar days
        self.assertIsNone(out[2])
        self.assertAlmostEqual(out[9], (5 + 6 + 7) / 3)

    def test_paired_lines_share_a_shade(self):
        days = [d(2024, 1, 1), d(2024, 1, 2)]
        chart = line_chart(days, [("A", [1, 2]), ("A, 50-day average", [1, 2]), ("B", [2, 3]), ("B, 50-day average", [2, 3])], paired=True)
        a, a_avg, b, b_avg = chart["paths"]
        self.assertEqual(a["stroke"], a_avg["stroke"])
        self.assertEqual(b["stroke"], b_avg["stroke"])
        self.assertNotEqual(a["stroke"], b["stroke"])
        self.assertEqual(a_avg["dash"], "2 2")

    def test_the_charts_page_offers_and_draws_the_average(self):
        self.client.force_login(self.user)
        page = self.client.get(reverse("investments_charts")).content.decode()
        self.assertIn('name="ma"', page)
        page = self.client.get(reverse("investments_charts") + f"?chart=b&period=1&ma=50&index={self.nifty.pk}").content.decode()
        self.assertIn("50-day average", page)
        self.assertEqual(self.client.get(reverse("investments_charts") + "?ma=7").status_code, 200)   # an unknown window is ignored
