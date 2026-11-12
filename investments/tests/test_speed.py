"""The speed round (docs/INVESTMENTS_SPEED.md): the faster paths give the same answers as the plain ones, and the work they save stays saved."""
from datetime import date as d, timedelta
from decimal import Decimal as D

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from investments.models import Instrument, InvestmentsStatsCache, ManualPrice, Price
from investments.services import alerts, dashboard, holdings, holdings_page, insights, masters, prices, reports, series, statscache, warm
from investments.tests.base import InvTestCase


class PriceLookupTests(InvTestCase):
    def test_latest_prices_gives_the_newest_row_on_or_before_the_day_and_a_hand_entered_price_wins_a_tie(self):
        Price.objects.create(instrument=self.reliance, date=d(2024, 1, 1), close=D(100), source="api")
        Price.objects.create(instrument=self.reliance, date=d(2024, 1, 5), close=D(110), source="api")
        Price.objects.create(instrument=self.reliance, date=d(2024, 1, 9), close=D(120), source="api")
        ManualPrice.objects.create(instrument=self.reliance, date=d(2024, 1, 5), close=D(111))
        Price.objects.create(instrument=self.fund, date=d(2024, 2, 1), close=D(50), source="api")
        found = prices.latest_prices([self.reliance.pk, self.fund.pk], d(2024, 1, 7))
        self.assertEqual(found, {self.reliance.pk: (d(2024, 1, 5), D(111))})
        self.assertEqual(prices.latest_prices([self.reliance.pk], d(2023, 12, 31)), {})
        self.assertEqual(prices.latest_prices([self.reliance.pk, self.fund.pk], d(2024, 3, 1)),
                         {self.reliance.pk: (d(2024, 1, 9), D(120)), self.fund.pk: (d(2024, 2, 1), D(50))})
        self.assertEqual(prices.latest_prices([], d(2024, 3, 1)), {})

    def test_last_price_date_looks_at_both_price_tables(self):
        Price.objects.create(instrument=self.reliance, date=d(2024, 1, 5), close=D(110), source="api")
        ManualPrice.objects.create(instrument=self.reliance, date=d(2024, 1, 9), close=D(111))
        Price.objects.create(instrument=self.fund, date=d(2024, 2, 1), close=D(50), source="api")
        ManualPrice.objects.create(instrument=self.fund, date=d(2024, 1, 1), close=D(49))
        self.assertEqual(prices.last_price_date([self.reliance.pk, self.fund.pk]), {self.reliance.pk: d(2024, 1, 9), self.fund.pk: d(2024, 2, 1)})
        self.assertEqual(prices.last_price_date([]), {})


class SeriesTests(InvTestCase):
    def test_sampled_prices_many_matches_one_at_a_time(self):
        start = d(2024, 1, 1)
        for n in range(40):
            Price.objects.create(instrument=self.reliance, date=start + timedelta(days=n), close=D(100 + n), source="api")
            if n % 3 == 0:
                Price.objects.create(instrument=self.fund, date=start + timedelta(days=n), close=D(50 + n), source="api")
        ManualPrice.objects.create(instrument=self.reliance, date=start + timedelta(days=10), close=D(999))
        Price.objects.create(instrument=self.fund, date=start - timedelta(days=5), close=D(7), source="api")
        days = series.sample_dates(start + timedelta(days=2), start + timedelta(days=45))
        many = series.sampled_prices_many([self.reliance, self.fund], days)
        self.assertEqual(many[self.reliance.pk], series.sampled_prices(self.reliance, days))
        self.assertEqual(many[self.fund.pk], series.sampled_prices(self.fund, days))
        self.assertIn(D(999), many[self.reliance.pk])

    def test_value_series_is_the_same_whatever_the_chunk_size(self):
        start = d(2024, 1, 1)
        extra = [masters.create_instrument(self.profile, self.user, kind="share", name=f"Extra {n}", code=f"X{n}.NS") for n in range(5)]
        for n in range(60):
            for inst in [self.reliance, self.fund] + extra:
                Price.objects.create(instrument=inst, date=start + timedelta(days=n), close=D(100 + n), source="api")
        for inst in [self.reliance, self.fund] + extra:
            self.buy(start, 3, 100, instrument=inst)
        days = series.sample_dates(start, start + timedelta(days=59))
        whole = series.portfolio_value_series(self.profile, days)
        original = series.PRICE_CHUNK
        series.PRICE_CHUNK = 2
        try:
            chunked = series.portfolio_value_series(self.profile, days)
        finally:
            series.PRICE_CHUNK = original
        self.assertEqual(whole, chunked)
        self.assertGreater(whole[0][-1], 0)


class HoldingsComputeTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.buy(d(2023, 1, 2), 10, 100)
        self.buy(d(2023, 6, 1), 5, 120)
        self.sell(d(2023, 9, 1), 4, 150)
        self.buy(d(2023, 3, 1), 7, 50, instrument=self.fund)
        for inst in (self.reliance, self.fund):
            Price.objects.create(instrument=inst, date=d(2024, 1, 2), close=D(200), source="api")

    def test_without_xirr_only_the_xirr_differs(self):
        full, ft = holdings.compute(self.profile, as_of=d(2024, 1, 2))
        lean, lt = holdings.compute(self.profile, as_of=d(2024, 1, 2), with_xirr=False)
        self.assertIsNotNone(ft.xirr)
        self.assertIsNone(lt.xirr)
        self.assertTrue(all(h.xirr is None for h in lean))
        self.assertEqual((ft.value, ft.invested, ft.count, ft.flows), (lt.value, lt.invested, lt.count, lt.flows))
        self.assertEqual([(h.instrument.pk, h.units, h.cost, h.value) for h in full], [(h.instrument.pk, h.units, h.cost, h.value) for h in lean])

    def test_a_shared_history_gives_the_same_answer_for_an_earlier_date(self):
        history = holdings.load_history(self.profile, d(2024, 1, 2))
        for day in (d(2023, 2, 1), d(2023, 7, 1), d(2023, 12, 31), d(2024, 1, 2)):
            plain, pt = holdings.compute(self.profile, as_of=day)
            shared, st = holdings.compute(self.profile, as_of=day, history=history)
            self.assertEqual([(h.instrument.pk, h.units, h.cost, h.value, h.xirr, h.first_date) for h in plain],
                             [(h.instrument.pk, h.units, h.cost, h.value, h.xirr, h.first_date) for h in shared], day)
            self.assertEqual((pt.value, pt.invested, pt.xirr, pt.count), (st.value, st.invested, st.xirr, st.count), day)

    def test_a_history_for_an_earlier_date_is_refused(self):
        history = holdings.load_history(self.profile, d(2023, 6, 1))
        with self.assertRaises(ValueError):
            holdings.compute(self.profile, as_of=d(2024, 1, 2), history=history)

    def test_queries_do_not_grow_with_the_number_of_transactions(self):
        def count():
            with CaptureQueriesContext(connection) as ctx:
                holdings.compute(self.profile, as_of=d(2024, 1, 2))
            return len(ctx)

        few = count()
        for n in range(15):
            self.buy(d(2023, 10, 1) + timedelta(days=n), 1, 100)
            self.buy(d(2023, 10, 1) + timedelta(days=n), 1, 50, instrument=self.fund)
        self.assertEqual(count(), few)       # a column read from a deferred field would add a query per row


class OverviewTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        nifty = Instrument.objects.get(code="^NSEI")
        start = d.today() - timedelta(days=500)
        for n in range(501):
            day = start + timedelta(days=n)
            Price.objects.create(instrument=nifty, date=day, close=D(10000) + n, source="api")
            Price.objects.create(instrument=self.reliance, date=day, close=D(100) + D(n) / 10, source="api")
        self.buy(start + timedelta(days=5), 10, 100)
        self.buy(start + timedelta(days=200), 4, 130)

    def test_the_cached_figures_leave_out_the_whole_history_chart_but_a_direct_compute_has_it(self):
        self.assertIsNone(dashboard.load(self.profile)["chart"])
        self.assertIsNotNone(dashboard.compute(self.profile)["chart"])

    def test_every_chart_period_including_all_is_drawn(self):
        for key in ("1m", "1y", "all"):
            page = self.client.get(reverse("investments_dashboard") + f"?range={key}").content.decode()
            self.assertIn("Same money in", page, key)
        self.assertIn('class="on" aria-current="true">All</a>', self.client.get(reverse("investments_dashboard") + "?range=all").content.decode())

    def test_a_chosen_time_weighted_return_still_gets_the_sampled_line(self):
        masters.update_settings(self.profile, self.user, overview={"boxes": ["value"], "metrics": ["twr"], "periods": ["all"]})
        data = dashboard.load(self.profile)
        self.assertIsNotNone(data["chart"])
        self.assertIsNotNone(data["overview"]["rows"][0]["values"][0])

    def test_the_opening_values_do_not_change_with_a_shared_history(self):
        a = dashboard.compute(self.profile)["overview"]
        self.assertEqual(len(a["periods"]), 4)
        values = {r["id"]: r["values"] for r in a["rows"]}
        self.assertTrue(all(v is not None for v in values["gain"]))

    def test_insights_take_the_turning_long_term_lots_from_the_figures(self):
        today = d.today()
        self.buy(today - timedelta(days=self.profile_long_term_days() - 20), 3, 100)
        data = dashboard.compute(self.profile)
        reference = reports.turning_long(self.profile, days=60).rows
        self.assertEqual([(n, t, left) for n, t, left in data["turning"]], [(r[0], r[4].isoformat(), r[5]) for r in reference])
        found = {i["kind"]: i for i in insights.compute(self.profile)}
        self.assertIn("turning_long", found)

    def test_a_selection_has_no_turning_long_list_and_insights_fall_back(self):
        data = dashboard.compute(self.profile, portfolio=self.portfolio.pk)
        self.assertIsNone(data["turning"])

    def profile_long_term_days(self):
        from investments.services import core

        return core.get_settings(self.profile, create=False).long_term_days

    def test_insights_do_not_work_out_a_second_set_of_figures(self):
        dashboard.load(self.profile, include_dividends=holdings.core.get_settings(self.profile, create=False).include_dividends)
        calls = []
        original = dashboard.compute
        dashboard.compute = lambda *a, **k: calls.append(1) or original(*a, **k)
        try:
            insights.compute(self.profile)
        finally:
            dashboard.compute = original
        self.assertEqual(calls, [])


class HoldingsPageTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        for n in range(30):
            Price.objects.create(instrument=self.reliance, date=d.today() - timedelta(days=n), close=D(100 + n), source="api")
        self.buy(d.today() - timedelta(days=200), 10, 100)

    def test_the_rows_are_kept_and_follow_a_change_of_data(self):
        url = reverse("investments_holdings")
        first = self.client.get(url).content.decode()
        self.assertIn("Reliance Industries", first)
        self.assertEqual(InvestmentsStatsCache.objects.filter(profile=self.profile, kind="holdings").count(), 1)
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(url).content.decode().count("Reliance Industries"), first.count("Reliance Industries"))
        self.assertFalse([q for q in ctx.captured_queries if "investments_transaction" in q["sql"]])    # the transactions are not read again
        self.sell(d.today() - timedelta(days=10), 10, 120)
        self.assertNotIn("Reliance Industries", self.client.get(url).content.decode())      # sold out: no longer under Held
        self.assertIn("Sold out", self.client.get(url + "?status=sold_out").content.decode())

    def test_the_rows_of_a_selection_are_kept_apart(self):
        rows, held, sold = holdings_page.load(self.profile)
        self.assertEqual((len(rows), held, sold), (2, 1, 0))      # the share held and the fund not bought yet
        by_name = {r.instrument.name: r for r in rows}
        self.assertTrue(by_name["Reliance Industries"].is_held)
        self.assertTrue(by_name[self.fund.name].empty)
        self.assertIsNotNone(by_name["Reliance Industries"].spark)
        other, _h, _s = holdings_page.load(self.profile, portfolio=self.portfolio.pk + 999)
        self.assertEqual([r.is_held for r in other], [False, False])


class AlertBadgeTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        masters.create_instrument(self.profile, self.user, kind="alternative", name="FD", maturity_date=d.today() + timedelta(days=10))

    def test_a_page_does_not_work_the_alerts_out_but_asks_for_the_count_afterwards(self):
        InvestmentsStatsCache.objects.filter(profile=self.profile).delete()
        page = self.client.get(reverse("investments_holdings")).content.decode()
        self.assertIn('data-alert-url="/investments/prefs/alert-count/"', page)
        self.assertIn("js/investments/alert-badge", page)
        self.assertFalse(InvestmentsStatsCache.objects.filter(profile=self.profile, kind="alerts").exists())
        count = self.client.get(reverse("investments_alert_count")).json()["count"]
        self.assertGreaterEqual(count, 1)
        self.assertEqual(count, len(alerts.visible(self.profile)))
        page = self.client.get(reverse("investments_holdings")).content.decode()
        self.assertNotIn("data-alert-url", page)           # now kept: the badge is in the page itself
        self.assertIn('aria-label="Alerts need attention"', page)      # a dot, no number

    def test_the_count_is_for_readers_only(self):
        self.client.logout()
        self.assertNotEqual(self.client.get(reverse("investments_alert_count")).status_code, 200)


class WarmTests(InvTestCase):
    def test_warming_keeps_what_the_pages_ask_for(self):
        Price.objects.create(instrument=self.reliance, date=d.today(), close=D(150), source="api")
        self.buy(d.today() - timedelta(days=400), 10, 100)
        summary = warm.warm_all()
        self.assertEqual((summary["profiles"], summary["failed"]), (1, 0))
        kinds = set(InvestmentsStatsCache.objects.filter(profile=self.profile).values_list("kind", flat=True))
        self.assertTrue({"dashboard", "value_chart", "holdings", "alerts"} <= kinds, kinds)
        # the Overview page now finds all of it: it works nothing out
        self.client.force_login(self.user)
        calls = []
        original, original_series = dashboard.compute, series.portfolio_value_series
        dashboard.compute = lambda *a, **k: calls.append("figures") or original(*a, **k)
        series.portfolio_value_series = lambda *a, **k: calls.append("series") or original_series(*a, **k)
        try:
            self.assertEqual(self.client.get(reverse("investments_dashboard")).status_code, 200)
            self.assertEqual(self.client.get(reverse("investments_holdings")).status_code, 200)
        finally:
            dashboard.compute, series.portfolio_value_series = original, original_series
        self.assertEqual(calls, [])
        self.assertEqual(statscache.peek(self.profile, "alerts", {}) is not None, True)
        self.assertEqual(alerts.peek_count(self.profile), len(alerts.visible(self.profile)))

    def test_a_profile_that_fails_does_not_stop_the_run(self):
        original = warm.warm_profile
        warm.warm_profile = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            with self.assertLogs("investments.services.warm", level="ERROR"):
                summary = warm.warm_all()
        finally:
            warm.warm_profile = original
        self.assertEqual((summary["profiles"], summary["failed"]), (0, 1))


class RequestTimingTests(InvTestCase):
    def test_off_by_default_and_logs_a_line_when_switched_on(self):
        from django.test import override_settings

        self.client.force_login(self.user)
        self.assertNotIn("Server-Timing", self.client.get(reverse("investments_holdings")))
        with override_settings(PERF_LOG=True):
            with self.assertLogs("quill.perf", level="INFO") as logs:
                response = self.client.get(reverse("investments_holdings"))
        self.assertIn("queries;desc=", response["Server-Timing"])
        self.assertIn("PERF GET /investments/holdings/ 200", logs.output[0])
