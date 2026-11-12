"""The index-equivalent Alpha, the Performance tab, charts, Total Portfolio Value and the cache (plan 9, 12, 26.4)."""
from datetime import date as d, timedelta
from decimal import Decimal as D

from django.test import SimpleTestCase
from django.urls import reverse

from investments import indexcmp, svgchart, xirr
from investments.models import Instrument, InvestmentsStatsCache, Price
from investments.services import dashboard, holdings, masters, performance, series, transactions as tx
from investments.tests.base import InvTestCase


class IndexReplayTests(SimpleTestCase):
    LEVELS = {d(2023, 1, 1): D(100), d(2023, 7, 1): D(110), d(2024, 1, 1): D(121)}

    def level(self, day):
        return self.LEVELS.get(day)

    def test_one_purchase_gives_the_index_growth(self):
        got = indexcmp.index_xirr([(d(2023, 1, 1), D(-1000))], self.level, d(2024, 1, 1))
        self.assertAlmostEqual(got, 0.21, places=6)

    def test_purchase_and_sale_replayed_at_the_same_dates(self):
        flows = [(d(2023, 1, 1), D(-1000)), (d(2023, 7, 1), D(550))]
        replayed = indexcmp.replay(flows, self.level, d(2024, 1, 1))
        _out, closing = replayed
        # 10 units bought at 100, 5 sold at 110, 5 left at 121
        self.assertEqual(closing, D("605"))
        self.assertIsNotNone(indexcmp.index_xirr(flows, self.level, d(2024, 1, 1)))

    def test_missing_level_is_none_never_a_guess(self):
        self.assertIsNone(indexcmp.index_xirr([(d(2023, 2, 1), D(-1000))], self.level, d(2024, 1, 1)))
        self.assertIsNone(indexcmp.alpha(0.1, None))
        self.assertAlmostEqual(indexcmp.alpha(0.25, 0.21), 0.04)


class SeriesTests(SimpleTestCase):
    def test_sampling_density_and_cap(self):
        self.assertEqual(len(series.sample_dates(d(2024, 1, 1), d(2024, 2, 1))), 32)
        weekly = series.sample_dates(d(2023, 1, 1), d(2024, 12, 31))
        self.assertTrue(80 < len(weekly) < 120)
        monthly = series.sample_dates(d(2010, 1, 1), d(2024, 12, 31))
        self.assertTrue(170 < len(monthly) < 190)
        self.assertEqual(monthly[-1], d(2024, 12, 31))
        self.assertLessEqual(len(series.sample_dates(d(1900, 1, 1), d(2024, 12, 31))), series.MAX_POINTS + 1)

    def test_time_weighted_line_does_not_jump_when_money_is_added(self):
        values = [D(100), D(110), D(1110), D(1221)]          # 10% growth, then 1,000 added and no growth, then 10% again
        flows = [D(100), D(0), D(1000), D(0)]
        line = series.performance_index(values, flows)
        self.assertEqual([round(float(x), 2) for x in line], [100.0, 110.0, 110.0, 121.0])

    def test_chart_geometry(self):
        days = [d(2024, 1, 1) + timedelta(days=i) for i in range(5)]
        chart = svgchart.line_chart(days, [("A", [1, 2, None, 4, 5]), ("B", [5, 4, 3, 2, 1])])
        self.assertEqual(len(chart["paths"][0]["points"]), 2)          # a gap splits the line
        self.assertNotEqual(chart["paths"][0]["dash"], chart["paths"][1]["dash"])
        self.assertIsNone(svgchart.line_chart(days[:1], [("A", [1])]))


class PerformanceTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.nifty = Instrument.objects.get(code="^NSEI")
        day = d(2022, 1, 1)
        while day <= d(2024, 6, 30):
            n = (day - d(2022, 1, 1)).days
            Price.objects.create(instrument=self.nifty, date=day, close=D(10000) * (D("1.0002") ** n), source="api")
            Price.objects.create(instrument=self.reliance, date=day, close=D(100) * (D("1.0004") ** n), source="api")
            day += timedelta(days=1)

    def test_dashboard_has_index_xirr_and_alpha(self):
        self.buy(d(2022, 1, 1), 10, 100)
        data = dashboard.compute(self.profile, as_of=d(2024, 1, 1))
        row = data["rows"][0]
        self.assertAlmostEqual(row["index_xirr"], 1.0002 ** 365 - 1, places=3)
        self.assertAlmostEqual(row["xirr"], 1.0004 ** 365 - 1, places=3)
        self.assertGreater(row["alpha"], 0)
        self.assertAlmostEqual(data["totals"]["alpha"], row["alpha"], places=6)
        self.assertIsNotNone(data["chart"])

    def test_dashboard_is_cached_and_recomputed_when_data_or_prices_change(self):
        self.buy(d(2022, 1, 1), 10, 100)
        first = dashboard.load(self.profile, as_of=d(2024, 1, 1))
        self.assertEqual(InvestmentsStatsCache.objects.count(), 1)
        calls = []
        orig = dashboard.compute
        dashboard.compute = lambda *a, **k: calls.append(1) or orig(*a, **k)
        try:
            dashboard.load(self.profile, as_of=d(2024, 1, 1))
            self.assertEqual(calls, [])
            self.buy(d(2023, 1, 2), 1, 100)                     # data_version moves
            dashboard.load(self.profile, as_of=d(2024, 1, 1))
            self.assertEqual(len(calls), 1)
            from investments.services import fetch
            fetch.bump_version()                                 # a price update moves the global version
            dashboard.load(self.profile, as_of=d(2024, 1, 1))
            self.assertEqual(len(calls), 2)
        finally:
            dashboard.compute = orig
        self.assertEqual(InvestmentsStatsCache.objects.count(), 1)
        self.assertIsInstance(first["totals"]["value"], D)

    def test_period_uses_the_start_value_as_the_opening_investment(self):
        self.buy(d(2022, 1, 1), 10, 100)
        rows, total, notes, sectoral = performance.table(self.profile, start=d(2023, 1, 1), end=d(2024, 1, 1))
        self.assertAlmostEqual(rows[0].xirr, 1.0004 ** 365 - 1, places=3)
        self.assertAlmostEqual(rows[0].index_xirr, 1.0002 ** 365 - 1, places=3)
        self.assertFalse(sectoral)

    def test_bought_after_the_start_is_noted_and_compared_over_the_same_dates(self):
        self.buy(d(2023, 7, 1), 10, 100)
        rows, _total, notes, _s = performance.table(self.profile, start=d(2023, 1, 1), end=d(2024, 1, 1))
        self.assertEqual(rows[0].starts, d(2023, 7, 1))
        self.assertIn("Held from", rows[0].note)
        self.assertTrue(any("first purchase" in n for n in notes))

    def test_cagr_measure(self):
        self.buy(d(2022, 1, 1), 10, 100)
        rows, _t, _n, _s = performance.table(self.profile, start=d(2023, 1, 1), end=d(2024, 1, 1), measure="cagr")
        self.assertAlmostEqual(rows[0].cagr, 1.0004 ** 365 - 1, places=3)
        # compared with the index's own CAGR over the same dates, not with an index XIRR of the cash flows
        self.assertAlmostEqual(rows[0].index_cagr, 1.0002 ** 365 - 1, places=3)
        self.assertIsNone(rows[0].index_xirr)
        self.assertAlmostEqual(rows[0].alpha, rows[0].cagr - rows[0].index_cagr, places=9)

    def test_cagr_page_and_export_say_index_cagr(self):
        self.buy(d(2022, 1, 1), 10, 100)
        self.client.force_login(self.user)
        html = self.client.get(reverse("investments_performance") + "?measure=cagr&period=custom&from=2023-01-01&to=2024-01-01").content.decode()
        self.assertIn("Nifty 50 CAGR", html)
        self.assertNotIn("Nifty 50 XIRR", html)

    def test_sectoral_columns_only_while_switched_on(self):
        bank = Instrument.objects.create(profile=None, kind="index", name="Nifty Bank", code="^NSEBANK", price_source="yahoo", price_basis="split_adjusted")
        for n in range(0, 800, 1):
            day = d(2022, 1, 1) + timedelta(days=n)
            Price.objects.create(instrument=bank, date=day, close=D(40000) * (D("1.0003") ** n), source="api")
        masters.update_profile_details(self.profile, self.user, self.reliance, sectoral_index=bank, sectoral_set=True)
        self.buy(d(2022, 1, 1), 10, 100)
        rows, _t, _n, sectoral = performance.table(self.profile, start=d(2023, 1, 1), end=d(2024, 1, 1))
        self.assertFalse(sectoral)
        self.assertIsNone(rows[0].sect_xirr)
        masters.update_settings(self.profile, self.user, sectoral_enabled=True)
        rows, _t, _n, sectoral = performance.table(self.profile, start=d(2023, 1, 1), end=d(2024, 1, 1))
        self.assertTrue(sectoral)
        self.assertAlmostEqual(rows[0].sect_xirr, 1.0003 ** 365 - 1, places=3)

    def test_pinned_index_values_answer_when_prices_are_gone(self):
        self.buy(d(2023, 1, 2), 10, 100)
        before = performance.table(self.profile, start=d(2023, 1, 1), end=d(2024, 1, 1))[0][0].index_xirr
        from investments.services import pins
        pins.pin_all(today=d(2024, 1, 1))
        from investments.models import PinnedPrice
        PinnedPrice.objects.get_or_create(instrument=self.nifty, asked_date=d(2024, 1, 1), reason="year_end",
                                          defaults={"trading_date": d(2024, 1, 1), "close": Price.objects.get(instrument=self.nifty, date=d(2024, 1, 1)).close})
        Price.objects.filter(instrument=self.nifty).delete()
        after = performance.table(self.profile, start=d(2023, 1, 1), end=d(2024, 1, 1))[0][0].index_xirr
        self.assertAlmostEqual(before, after, places=9)

    def test_value_series_and_total_value_exclude_nothing_but_dividends(self):
        self.buy(d(2022, 1, 1), 10, 100)
        tx.add_transaction(self.profile, self.user, side="buy", instrument=self.fund, portfolio=self.portfolio, broker=self.zerodha,
                           date=d(2023, 6, 1), awaiting=True, amount=D(5000))
        days = series.sample_dates(d(2022, 1, 1), d(2024, 1, 1))
        values, flows = series.portfolio_value_series(self.profile, days)
        rows, totals = holdings.compute(self.profile, as_of=d(2024, 1, 1))
        self.assertAlmostEqual(float(values[-1]), float(totals.value), places=2)
        self.assertEqual(sum(flows), D(1000) + D(5000))

    def test_pages_render_and_export_headers(self):
        self.client.force_login(self.user)
        self.buy(d(2022, 1, 1), 10, 100)
        for name, query in (("investments_performance", "?period=1"), ("investments_performance", "?measure=cagr&period=3"),
                            ("investments_charts", "?period=1"), ("investments_charts", "?chart=b&inv=%d&period=all" % self.reliance.pk),
                            ("investments_value", "?on=2024-01-01"), ("investments_dashboard", "")):
            r = self.client.get(reverse(name) + query)
            self.assertEqual(r.status_code, 200, (name, query))
        r = self.client.get(reverse("investments_charts") + "?period=1")
        self.assertContains(r, "<polyline")
        self.assertContains(r, "stroke-dasharray")
        r = self.client.get(reverse("investments_performance") + "?period=custom&from=2024-01-01&to=2023-01-01")
        self.assertContains(r, "start date must be before")

    def test_performance_period_options_match_chart_a(self):
        from investments import views_reports

        self.client.force_login(self.user)
        html = self.client.get(reverse("investments_performance")).content.decode()
        for key, label in views_reports.CHART_PERIODS:
            self.assertIn(f'<option value="{key}"', html)
            self.assertIn(f">{label}</option>", html)
        chart = self.client.get(reverse("investments_charts")).content.decode()
        self.assertIn('<option value="6m"', chart)

    def test_performance_new_periods_render_and_export(self):
        self.client.force_login(self.user)
        self.buy(d(2022, 1, 1), 10, 100)
        for period in ("1m", "6m", "all"):
            r = self.client.get(reverse("investments_performance") + f"?period={period}")
            self.assertEqual(r.status_code, 200, period)
            self.assertContains(r, f'<option value="{period}" selected', msg_prefix=period)
            r = self.client.get(reverse("investments_performance") + f"?period={period}&export=xlsx")
            self.assertEqual(r.status_code, 200, period)
            r = self.client.get(reverse("investments_performance") + f"?period={period}&held=1")
            self.assertEqual(r.status_code, 200, period)

    def test_all_period_starts_the_day_before_the_first_purchase(self):
        self.client.force_login(self.user)
        self.buy(d(2022, 1, 1), 10, 100)
        r = self.client.get(reverse("investments_performance") + "?period=all")
        self.assertEqual(r.context["start"], d(2021, 12, 31))

    def test_xirr_constant_used_consistently(self):
        self.assertEqual(xirr.MIN_DAYS, 30)

