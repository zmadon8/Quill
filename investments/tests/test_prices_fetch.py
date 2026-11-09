"""Price adapters, the fetch run and the price lookups, all against recorded fixtures (no live calls)."""
from datetime import date as d, datetime, timedelta, timezone
from decimal import Decimal as D
from unittest import mock

from django.test import SimpleTestCase

from investments.adapters import amfi, http, mfapi, yahoo
from investments.adapters.base import FetchError
from investments.models import ManualPrice, PinnedPrice, Price, SourceRun, SplitSignal
from investments.services import fetch, masters, prices
from investments.tests.base import InvTestCase
from investments.tests.fakehttp import FakeNet, fixture


class AdapterParsingTests(SimpleTestCase):
    def test_yahoo_chart_uses_exchange_dates_and_drops_missing_closes(self):
        out = yahoo.parse_chart(fixture("yahoo_chart_reliance.json"))
        self.assertEqual([r[0] for r in out.rows], [d(2026, 11, 2), d(2026, 11, 3), d(2026, 11, 5), d(2026, 11, 6)])
        self.assertEqual(out.rows[0][1], D("1301.5000"))
        self.assertEqual(out.rejected, 1)
        self.assertEqual((out.currency, out.exchange, out.name), ("INR", "NSI", "Reliance Industries Limited"))
        self.assertEqual(out.splits, [(d(2026, 11, 4), D(2), D(1))])
        self.assertEqual(out.dividends, [(d(2026, 11, 3), D(10))])

    def test_yahoo_since_filters_old_days(self):
        out = yahoo.parse_chart(fixture("yahoo_chart_reliance.json"), since=d(2026, 11, 5))
        self.assertEqual([r[0] for r in out.rows], [d(2026, 11, 5), d(2026, 11, 6)])

    def test_yahoo_error_and_garbage(self):
        with self.assertRaises(FetchError):
            yahoo.parse_chart(fixture("yahoo_chart_error.json"))
        with self.assertRaises(FetchError):
            yahoo.parse_chart(b"<html>429</html>")

    def test_zero_and_negative_prices_rejected(self):
        body = fixture("yahoo_chart_reliance.json").replace(b"1301.5", b"0").replace(b"1312.25", b"-4")
        out = yahoo.parse_chart(body)
        self.assertEqual([r[0] for r in out.rows], [d(2026, 11, 5), d(2026, 11, 6)])
        self.assertEqual(out.rejected, 3)

    def test_amfi_keeps_only_wanted_codes_and_skips_bad_navs(self):
        lines = fixture("amfi_navall.txt").decode().splitlines(True)
        found = amfi.parse_lines(iter(lines), ["122639", "119063", "118550", "125497", "999"])
        self.assertEqual(set(found), {"122639", "125497"})              # N.A. and 0 NAVs are dropped
        self.assertEqual(found["122639"][:2], (d(2026, 11, 5), D("81.4012")))

    def test_mfapi_history(self):
        out = mfapi.parse(fixture("mfapi_122639.json"))
        self.assertEqual(out.rows, [(d(2026, 11, 2), D("80.1")), (d(2026, 11, 4), D("80.9")), (d(2026, 11, 5), D("81.40120"))])
        self.assertEqual(out.rejected, 2)
        self.assertEqual(len(mfapi.parse(fixture("mfapi_122639.json"), since=d(2026, 11, 4)).rows), 2)


class HttpRulesTests(SimpleTestCase):
    def setUp(self):
        self.net = FakeNet()
        patcher = mock.patch.object(http, "_urlopen", self.net)
        patcher.start()
        self.addCleanup(patcher.stop)
        sleeps = []
        self.sleeps = sleeps
        sp = mock.patch.object(http, "sleep", lambda s: sleeps.append(s))
        sp.start()
        self.addCleanup(sp.stop)

    def test_short_user_agent_is_sent(self):
        self.net.add("example", b"ok")
        http.get("https://example.test/x")
        self.assertEqual(self.net.agents, ["Mozilla/5.0"])

    def test_429_is_retried_with_growing_delay_then_succeeds(self):
        self.net.add("chart", 429, 429, fixture("yahoo_chart_reliance.json"))
        out = yahoo.fetch("RELIANCE.NS", today=d(2026, 11, 9))
        self.assertEqual(len(out.rows), 4)
        self.assertEqual(len(self.sleeps), 2)
        self.assertGreaterEqual(self.sleeps[0], 2.0)
        self.assertGreaterEqual(self.sleeps[1], 4.0)
        self.assertLess(self.sleeps[0], 3.1)

    def test_gives_up_after_three_tries(self):
        self.net.add("chart", 429)
        with self.assertRaises(FetchError) as cm:
            yahoo.fetch("RELIANCE.NS", today=d(2026, 11, 9))
        self.assertEqual(cm.exception.status, 429)
        self.assertEqual(len(self.net.calls), 3)

    def test_404_is_not_retried(self):
        self.net.add("chart", 404)
        with self.assertRaises(FetchError):
            yahoo.fetch("NOPE.NS", today=d(2026, 11, 9))
        self.assertEqual(len(self.net.calls), 1)

    def test_url_contains_the_since_window_and_the_symbol_is_quoted(self):
        self.net.add("chart", fixture("yahoo_chart_reliance.json"))
        yahoo.fetch("^NSEI", since=d(2026, 11, 2), today=d(2026, 11, 9))
        url = self.net.calls[0]
        self.assertIn("/chart/^NSEI?", url)
        p1 = int(url.split("period1=")[1].split("&")[0])
        self.assertEqual(datetime.fromtimestamp(p1, tz=timezone.utc).date(), d(2026, 10, 28))

    def test_search(self):
        self.net.add("search", fixture("yahoo_search.json"))
        hits = yahoo.search("reliance")
        self.assertEqual([h["symbol"] for h in hits], ["RELIANCE.NS", "RELIANCE.BO"])

    def test_amfi_empty_answer_is_an_error_not_silence(self):
        self.net.add("amfiindia", b"<html>moved</html>")
        with self.assertRaises(FetchError):
            amfi.fetch(["122639"], url="https://www.amfiindia.com/spages/NAVAll.txt")


class FetchRunTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.net = FakeNet()
        self.sleeps = []
        for target, value in ((http, "_urlopen"), ):
            p = mock.patch.object(target, value, self.net)
            p.start()
            self.addCleanup(p.stop)
        sp = mock.patch.object(http, "sleep", lambda s: self.sleeps.append(s))
        sp.start()
        self.addCleanup(sp.stop)

    def run_fetch(self, **kw):
        kw.setdefault("today", d(2026, 11, 9))
        return fetch.fetch_prices(rng=lambda: 0.0, **kw)

    def test_new_share_gets_its_history_and_the_version_moves(self):
        self.net.add("RELIANCE.NS", fixture("yahoo_chart_reliance.json"))
        self.net.add("%5ENSEI", 404)
        before = fetch.price_version()
        summary = self.run_fetch()
        self.assertEqual(Price.objects.filter(instrument=self.reliance).count(), 4)
        self.assertEqual(Price.objects.filter(instrument=self.reliance).first().basis, "split_adjusted")
        self.assertGreater(fetch.price_version(), before)
        run = SourceRun.objects.filter(source="yahoo").get()
        self.assertEqual((run.tried, run.updated), (2, 1))
        self.assertTrue(any("Nifty" in f["name"] for f in run.failures))      # the index failed, the share did not
        self.assertEqual(summary["tried"], 3)           # the share, the index and the fund (not fetched from Yahoo)

    def test_requests_are_spaced(self):
        from investments.models import Instrument
        nifty = Instrument.objects.get(code="^NSEI")
        self.net.add("RELIANCE.NS", fixture("yahoo_chart_reliance.json"))
        self.net.add("NSEI", fixture("yahoo_chart_reliance.json"))
        self.run_fetch(spacing=1.5, ids=[self.reliance.pk, nifty.pk])
        self.assertEqual(len(self.sleeps), 1)
        self.assertEqual(self.sleeps[0], 1.5)

    def test_only_new_days_are_requested_and_a_failed_symbol_keeps_its_last_price(self):
        Price.objects.create(instrument=self.reliance, date=d(2026, 11, 3), close=D("1000"), source="api", basis="split_adjusted")
        self.net.add("RELIANCE.NS", 500)
        self.net.add("NSEI", 404)
        summary = self.run_fetch(ids=[self.reliance.pk])
        self.assertEqual(Price.objects.get(instrument=self.reliance).close, D("1000"))
        self.assertEqual(summary["failures"][0]["name"], "Reliance Industries")
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(fetch.price_version(), 0)

    def test_upload_rows_and_manual_prices_are_never_overwritten(self):
        Price.objects.create(instrument=self.reliance, date=d(2026, 11, 5), close=D("9999"), source="upload", basis="split_adjusted")
        ManualPrice.objects.create(instrument=self.reliance, date=d(2026, 11, 6), close=D("5555"))
        self.net.add("RELIANCE.NS", fixture("yahoo_chart_reliance.json"))
        self.run_fetch(ids=[self.reliance.pk])
        self.assertEqual(Price.objects.get(instrument=self.reliance, date=d(2026, 11, 5)).close, D("9999"))
        self.assertEqual(ManualPrice.objects.get(instrument=self.reliance, date=d(2026, 11, 6)).close, D("5555"))
        self.assertEqual(prices.latest_prices([self.reliance.pk], d(2026, 11, 9))[self.reliance.pk], (d(2026, 11, 6), D("5555")))

    def test_basis_mismatch_is_refused(self):
        from investments.errors import InvestmentsError
        with self.assertRaises(InvestmentsError):
            fetch.upsert_prices(self.reliance, [(d(2026, 11, 1), D(5))], "api", "raw")

    def test_a_new_split_refetches_the_whole_history_and_keeps_uploads(self):
        Price.objects.create(instrument=self.reliance, date=d(2026, 10, 1), close=D("2600"), source="api", basis="split_adjusted")
        Price.objects.create(instrument=self.reliance, date=d(2026, 9, 1), close=D("2500"), source="upload", basis="split_adjusted")
        self.net.add("RELIANCE.NS", fixture("yahoo_chart_reliance.json"))
        self.run_fetch(ids=[self.reliance.pk])
        self.assertTrue(SplitSignal.objects.filter(instrument=self.reliance, ex_date=d(2026, 11, 4), refetched=True).exists())
        self.assertFalse(Price.objects.filter(instrument=self.reliance, date=d(2026, 10, 1)).exists())       # old fetched row replaced
        self.assertTrue(Price.objects.filter(instrument=self.reliance, date=d(2026, 9, 1), source="upload").exists())
        n = len(self.net.calls)
        self.run_fetch(ids=[self.reliance.pk])                                                         # the same split is not acted on twice
        self.assertEqual(SplitSignal.objects.count(), 1)
        self.assertEqual(len([c for c in self.net.calls[n:] if "RELIANCE" in c]), 1)

    def test_funds_use_mfapi_history_once_then_the_amfi_file(self):
        self.net.add("mfapi.in", fixture("mfapi_122639.json"))
        self.net.add("NAVAll", fixture("amfi_navall.txt"))
        self.run_fetch(ids=[self.fund.pk])
        self.assertEqual(Price.objects.filter(instrument=self.fund).count(), 3)
        self.assertEqual(Price.objects.get(instrument=self.fund, date=d(2026, 11, 5)).close, D("81.4012"))   # the AMFI value replaces mfapi's
        mf_calls = len([c for c in self.net.calls if "mfapi" in c])
        self.run_fetch(ids=[self.fund.pk])
        self.assertEqual(len([c for c in self.net.calls if "mfapi" in c]), mf_calls)                  # history only the first time
        self.assertEqual(SourceRun.objects.filter(source="amfi").count(), 2)

    def test_amfi_failure_is_recorded_and_other_symbols_still_run(self):
        self.net.add("NAVAll", 503)
        self.net.add("RELIANCE.NS", fixture("yahoo_chart_reliance.json"))
        self.net.add("NSEI", 404)
        summary = self.run_fetch(ids=[self.fund.pk, self.reliance.pk])
        self.assertTrue(any("AMFI" in f["name"] for f in summary["failures"]))
        self.assertTrue(Price.objects.filter(instrument=self.reliance).exists())

    def test_run_time_cap_stops_a_run(self):
        self.net.add("RELIANCE.NS", fixture("yahoo_chart_reliance.json"))
        ticks = iter(range(0, 10000, 1000))
        summary = fetch.fetch_prices(rng=lambda: 0.0, today=d(2026, 11, 9), max_seconds=600, clock=lambda: next(ticks))
        self.assertEqual(summary["stopped"], "run-time cap reached")

    def test_manual_and_alternative_instruments_are_not_fetched(self):
        alt = masters.create_instrument(self.profile, self.user, kind="alternative", name="Gold coins")
        self.assertNotIn(alt, fetch.tracked_instruments())
        masters.update_shared_details(self.profile, self.user, self.reliance, price_source="manual")
        self.assertNotIn(self.reliance, fetch.tracked_instruments())


class LookupTests(InvTestCase):
    def test_manual_wins_a_tie_and_later_day_wins_otherwise(self):
        Price.objects.create(instrument=self.reliance, date=d(2026, 11, 5), close=D(100), source="api")
        ManualPrice.objects.create(instrument=self.reliance, date=d(2026, 11, 5), close=D(111))
        self.assertEqual(prices.latest_prices([self.reliance.pk], d(2026, 11, 9))[self.reliance.pk], (d(2026, 11, 5), D(111)))
        Price.objects.create(instrument=self.reliance, date=d(2026, 11, 6), close=D(120), source="api")
        self.assertEqual(prices.latest_prices([self.reliance.pk], d(2026, 11, 9))[self.reliance.pk], (d(2026, 11, 6), D(120)))
        self.assertEqual(prices.latest_prices([self.reliance.pk], d(2026, 11, 5))[self.reliance.pk], (d(2026, 11, 5), D(111)))

    def test_price_on_checks_the_pin_first_then_prices_then_older_pins(self):
        Price.objects.create(instrument=self.reliance, date=d(2026, 3, 30), close=D(100), source="api")
        PinnedPrice.objects.create(instrument=self.reliance, asked_date=d(2026, 3, 31), trading_date=d(2026, 3, 30), close=D(99), reason="year_end")
        self.assertEqual(prices.price_on(self.reliance, d(2026, 3, 31)), (d(2026, 3, 30), D(99), "api", False))
        self.assertEqual(prices.price_on(self.reliance, d(2026, 4, 2))[:2], (d(2026, 3, 30), D(100)))
        Price.objects.all().delete()
        got = prices.price_on(self.reliance, d(2026, 4, 5))
        self.assertEqual((got[1], got[3]), (D(99), True))
        self.assertIsNone(prices.price_on(self.fund, d(2026, 4, 5)))

    def test_a_fixed_number_of_queries_for_many_instruments(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        ids = [self.reliance.pk, self.fund.pk]
        with CaptureQueriesContext(connection) as ctx:
            prices.latest_prices(ids, d(2026, 11, 9))
        self.assertEqual(len(ctx), 3)          # hand-entered, fetched, and the pins for that exact date

    def test_stale_and_move_detection(self):
        Price.objects.create(instrument=self.reliance, date=d(2026, 10, 1), close=D(100), source="api")
        Price.objects.create(instrument=self.reliance, date=d(2026, 10, 2), close=D(40), source="api")
        self.assertIn(self.reliance.pk, fetch.stale_ids([self.reliance], today=d(2026, 11, 9)))
        self.assertEqual(fetch.one_day_moves(self.reliance)[0][0], d(2026, 10, 2))
        self.assertEqual(fetch.stale_days(self.reliance, today=d(2026, 10, 10)), 8)

    def test_update_plan_groups_funds_then_tens(self):
        for i in range(23):
            masters.create_instrument(self.profile, self.user, kind="share", name=f"Co {i}", code=f"C{i}.NS")
        plan = fetch.update_plan(self.profile)
        self.assertEqual(plan[0], [self.fund.pk])
        self.assertEqual([len(b) for b in plan[1:]], [10, 10, 5])         # 24 shares including Reliance, and the Nifty 50 index
        self.assertTrue(fetch.start_allowed())
        fetch.mark_button_used()
        self.assertFalse(fetch.start_allowed())
        self.assertTrue(fetch.start_allowed(now=datetime.now(timezone.utc) + timedelta(seconds=61)))


class TwelveDataTests(InvTestCase):
    BODY = b'{"meta":{"symbol":"RELIANCE","exchange":"NSE","currency":"INR"},"values":[{"datetime":"2026-11-06","close":"1327.80"},{"datetime":"2026-11-05","close":"0"}],"status":"ok"}'

    def test_parse_and_fallback_when_yahoo_refuses(self):
        import os
        from investments.adapters import twelvedata
        self.assertEqual(twelvedata.split_symbol("RELIANCE.NS"), ("RELIANCE", "NSE"))
        out = twelvedata.parse(self.BODY)
        self.assertEqual((out.rows, out.rejected), ([(d(2026, 11, 6), D("1327.80"))], 1))
        with self.assertRaises(FetchError):
            twelvedata.parse(b'{"status":"error","code":401,"message":"bad key"}')
        masters.update_shared_details(self.profile, self.user, self.reliance, fallback_source="twelvedata")
        net = FakeNet()
        net.add("yahoo.com", 429)
        net.add("twelvedata.com", self.BODY)
        with mock.patch.dict(os.environ, {"TWELVEDATA_API_KEY": "test-key"}), mock.patch.object(http, "_urlopen", net), mock.patch.object(http, "sleep", lambda s: None):
            summary = fetch.fetch_prices(ids=[self.reliance.pk], today=d(2026, 11, 9), rng=lambda: 0.0)
        self.assertEqual(summary["updated"], 1)
        self.assertTrue(Price.objects.filter(instrument=self.reliance, date=d(2026, 11, 6)).exists())
        self.assertTrue(any("apikey=test-key" in c for c in net.calls))
