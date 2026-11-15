"""The charts of one hand-priced investment plot every Manual Price History entry (docs/DESIGN.md D184): trade-derived and hand entries are
points of their own, weekly sampling does not skip them, a Lump Sum shows its "Before sale" drop, a new trade refreshes the cached chart,
and a page whose entries are all old opens on the whole history instead of a flat last year."""
import json
from datetime import date as d, timedelta
from decimal import Decimal as D

from django.urls import reverse

from investments.services import chartview, investment_page, masters, prices, series
from investments.services import transactions as tx
from investments.svgchart import line_chart
from investments.tests.base import InvTestCase
from investments.tests.test_trade_prices import ManualPricedBase


def hover(chart):
    """``(dates, values of the first line)`` from a drawn chart's hover JSON."""
    data = json.loads(chart["hover"])
    return data["d"], data["s"][0]["v"]


class EntryDaysTests(InvTestCase):
    def test_every_entry_and_the_day_before_it_join_the_sample_days(self):
        days = [d(2024, 1, 5), d(2024, 1, 12), d(2024, 1, 19)]
        out = series.with_entry_days(days, [d(2024, 1, 10), d(2024, 1, 11), d(2023, 12, 1), d(2024, 2, 1)])
        self.assertEqual(out, [d(2024, 1, 5), d(2024, 1, 9), d(2024, 1, 10), d(2024, 1, 11), d(2024, 1, 12), d(2024, 1, 19)])
        self.assertEqual(series.with_entry_days(days, []), days)

    def test_a_dated_line_places_points_by_date(self):
        chart = line_chart([d(2024, 1, 1), d(2024, 1, 2), d(2024, 1, 10)], [("Price", [1, 2, 3])], by_date=True)
        xs = json.loads(chart["hover"])["x"]
        self.assertEqual(xs[0], 56.0)
        self.assertAlmostEqual(xs[1], 56 + 828 / 9, places=1)
        self.assertEqual(xs[2], 884.0)
        even = json.loads(line_chart([d(2024, 1, 1), d(2024, 1, 2), d(2024, 1, 10)], [("Price", [1, 2, 3])])["hover"])["x"]
        self.assertEqual(even[1], 470.0)


class HandPricedShareChartTests(ManualPricedBase):
    def test_the_price_chart_has_each_trade_price_on_its_date(self):
        self.buy(d(2024, 1, 10), 10, 100)      # a Wednesday: the weekly (Friday) samples alone would skip it
        self.buy(d(2024, 3, 13), 10, 120)
        self.sell(d(2024, 5, 15), 5, 150)
        chart = investment_page.price_chart(self.profile, self.reliance, d(2024, 1, 1), d(2024, 12, 31))
        dates, values = hover(chart)
        by_date = dict(zip(dates, values))
        self.assertEqual(by_date["10 Jan 2024"], "100.00")
        self.assertEqual(by_date["13 Mar 2024"], "120.00")
        self.assertEqual(by_date["15 May 2024"], "150.00")
        self.assertEqual(by_date["9 Jan 2024"], "")          # before the first price there is none
        self.assertEqual(by_date["12 Mar 2024"], "100.00")   # the line steps at the entry
        self.assertEqual(by_date["14 May 2024"], "120.00")

    def test_a_hand_entry_is_plotted_too(self):
        self.buy(d(2024, 1, 10), 10, 100)
        prices.set_manual_price(self.profile, self.user, self.reliance, d(2024, 4, 3), D("135.5"), "valuer")
        chart = investment_page.price_chart(self.profile, self.reliance, d(2024, 1, 1), d(2024, 12, 31))
        dates, values = hover(chart)
        self.assertEqual(dict(zip(dates, values))["3 Apr 2024"], "135.50")

    def test_the_52_week_range_is_the_price_in_force_when_none_was_entered_in_the_window(self):
        self.buy(d(2023, 1, 10), 10, 100)
        self.assertEqual(investment_page.range_52w(self.reliance, d(2024, 6, 1)), (D("100"), D("100")))      # no entry in the window
        self.buy(d(2024, 3, 1), 10, 130)
        self.assertEqual(investment_page.range_52w(self.reliance, d(2024, 6, 1)), (D("130"), D("130")))      # entries in the window decide

    def test_a_page_with_old_entries_only_opens_on_all_and_a_chosen_range_wins(self):
        old = d.today() - timedelta(days=700)
        self.buy(old, 10, 100)
        prices.set_manual_price(self.profile, self.user, self.reliance, old + timedelta(days=90), D("140"), "hand")
        url = reverse("investments_investment", args=[self.reliance.pk])
        self.assertContains(self.client.get(url), 'class="on" aria-current="true">All</a>')
        self.assertContains(self.client.get(url + "?range=1y"), 'class="on" aria-current="true">1Y</a>')

    def test_a_page_with_recent_entries_keeps_the_year(self):
        self.buy(d.today() - timedelta(days=100), 10, 100)
        self.buy(d.today() - timedelta(days=50), 10, 110)
        url = reverse("investments_investment", args=[self.reliance.pk])
        self.assertContains(self.client.get(url), 'class="on" aria-current="true">1Y</a>')


class LumpSumValueChartTests(ManualPricedBase):
    END = d(2024, 12, 31)

    def setUp(self):
        super().setUp()
        self.chit = masters.create_instrument(self.profile, self.user, kind="alternative", name="Chit fund", asset_class="debt", lump_sum=True)

    def lump(self, side, day, amount, **kw):
        return tx.add_lump_sum_transaction(self.profile, self.user, side=side, instrument=self.chit, portfolio=self.portfolio, broker=self.zerodha,
                                           date=day, amount=D(amount), **kw)

    def chart(self):
        return chartview.value_chart(self.profile, None, self.END, portfolio=None, broker=None, instrument_ids=[self.chit.pk], entries_of=self.chit)

    def test_the_value_chart_shows_the_before_sale_drop_and_the_remaining_value(self):
        self.lump("buy", d(2024, 1, 3), 1000000, value_after=D(1000000))
        self.lump("sell", d(2024, 6, 12), 300000, remaining=D(800000))
        dates, values = hover(self.chart())
        by_date = dict(zip(dates, values))
        self.assertEqual(by_date["3 Jan 2024"], "10,00,000.00")
        self.assertEqual(by_date["11 Jun 2024"], "11,00,000.00")      # Before sale: amount sold plus remaining
        self.assertEqual(by_date["12 Jun 2024"], "8,00,000.00")

    def test_a_new_trade_refreshes_the_cached_chart(self):
        self.lump("buy", d(2024, 1, 3), 1000000, value_after=D(1000000))
        first = self.chart()
        self.assertNotIn("8,00,000.00", first["hover"])
        self.lump("sell", d(2024, 6, 12), 300000, remaining=D(800000))      # its service touches the profile's data version
        second = self.chart()
        self.assertIn("8,00,000.00", second["hover"])
        self.assertIn("11,00,000.00", second["hover"])

    def test_the_alternative_page_opens_on_all_when_its_entries_are_old(self):
        self.lump("buy", d(2022, 1, 3), 1000000, value_after=D(1000000))
        self.lump("sell", d(2022, 6, 12), 300000, remaining=D(800000))
        page = self.client.get(reverse("investments_investment", args=[self.chit.pk]))
        self.assertContains(page, 'class="on" aria-current="true">All</a>')
        self.assertIsNotNone(page.context["value_chart"])

