"""The NSE list, the unified instrument search and its endpoint, against a fake network (no live calls)."""
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from investments.adapters import http, nse_list as nse_adapter
from investments.models import AmfiScheme, Instrument, NseSecurity
from investments.services import instrument_search, nse_list
from investments.tests.base import InvTestCase, make_user
from investments.tests.fakehttp import FakeNet

NSE_CSV = (
    b"SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n"
    b"RELIANCE,Reliance Industries Limited,EQ,29-NOV-1995,10,1,INE002A01018,10\n"
    b"TCS,Tata Consultancy Services Limited,EQ,25-AUG-2004,1,1,INE467B01029,1\n"
    b"GOLDBEES,Nippon India ETF Gold BeES,BE,08-MAR-2007,1,1,INF204KB17I5,1\n"
    b"JUNKBOND,Some Bond,N1,01-JAN-2020,1,1,INE000000001,1\n"
)
AMFI_TXT = (
    b"Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date\n"
    b"Open Ended Schemes(Equity Scheme - Flexi Cap Fund)\n"
    b"122639;INF879O01027;-;Parag Parikh Flexi Cap Fund - Direct Plan - Growth;80.1234;06-Nov-2026\n"
    b"100001;INF000000001;-;Reliance Growth Fund - Direct Plan - Growth;50.0000;06-Nov-2026\n"
)


class NseAdapterTests(SimpleTestCase):
    def test_parse_keeps_wanted_series_and_strips_header_spaces(self):
        rows = list(nse_adapter.iter_all(NSE_CSV.decode().splitlines()))
        self.assertEqual([r[0] for r in rows], ["RELIANCE", "TCS", "GOLDBEES"])
        self.assertEqual(rows[0], ("RELIANCE", "Reliance Industries Limited", "INE002A01018", "EQ"))
        self.assertEqual(rows[2][3], "BE")

    def test_parse_ignores_short_rows_and_no_header(self):
        self.assertEqual(list(nse_adapter.iter_all(["junk", "RELIANCE,x"])), [])


class FakeNetCase(InvTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.net = FakeNet()
        for target, value in ((http, "_urlopen"), ):
            p = mock.patch.object(target, value, self.net)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(http, "sleep", lambda s: None)
        p.start()
        self.addCleanup(p.stop)


class NseListTests(FakeNetCase):
    def test_refresh_upserts_and_is_idempotent(self):
        self.net.add("EQUITY_L", NSE_CSV)
        self.assertEqual(nse_list.refresh(), 3)
        self.assertEqual(NseSecurity.objects.count(), 3)
        self.assertEqual(nse_list.refresh(), 0)            # not due again
        self.assertEqual(nse_list.refresh(force=True), 3)
        self.assertEqual(NseSecurity.objects.count(), 3)
        self.assertEqual(len(self.net.calls), 2)

    def test_due_window(self):
        self.assertTrue(nse_list.due())
        NseSecurity.objects.create(symbol="X", name="X Ltd")
        self.assertFalse(nse_list.due())
        NseSecurity.objects.update(updated_at=timezone.now() - timedelta(days=8))
        self.assertTrue(nse_list.due())

    def test_find_by_name_symbol_and_isin(self):
        self.net.add("EQUITY_L", NSE_CSV)
        nse_list.refresh()
        self.assertEqual([s.symbol for s in nse_list.find("reliance")], ["RELIANCE"])
        self.assertEqual([s.symbol for s in nse_list.find("tata consultancy")], ["TCS"])
        self.assertEqual([s.symbol for s in nse_list.find("tcs")], ["TCS"])
        self.assertEqual([s.symbol for s in nse_list.find("INE467B01029")], ["TCS"])
        self.assertEqual(nse_list.find("r"), [])


class SearchTests(FakeNetCase):
    def seed(self):
        self.net.add("EQUITY_L", NSE_CSV)
        nse_list.refresh()
        AmfiScheme.objects.create(code="122639", name="Parag Parikh Flexi Cap Fund - Direct Plan - Growth", isin="INF879O01027")
        AmfiScheme.objects.create(code="100001", name="Reliance Growth Fund - Direct Plan - Growth", isin="INF000000001")

    def test_unified_results_shape_and_codes(self):
        self.seed()
        out = instrument_search.search(self.profile, "reliance")
        by_source = {r["source"]: r for r in out["results"]}
        self.assertEqual(by_source["nse"]["code"], "RELIANCE.NS")
        self.assertEqual(by_source["nse"]["kind"], "share")
        self.assertEqual(by_source["amfi"]["code"], "100001")
        self.assertEqual(by_source["amfi"]["kind"], "fund")
        for r in out["results"]:
            self.assertEqual(set(r), {"source", "kind", "code", "name", "isin", "plan", "option", "raw_name", "extra", "existing_id"})

    def test_search_by_isin_symbol_and_scheme_code(self):
        self.seed()
        self.assertEqual(instrument_search.search(self.profile, "INE467B01029")["results"][0]["code"], "TCS.NS")
        self.assertEqual(instrument_search.search(self.profile, "GOLDBEES")["results"][0]["code"], "GOLDBEES.NS")
        self.assertEqual(instrument_search.search(self.profile, "122639")["results"][0]["source"], "amfi")

    def test_kind_filter(self):
        self.seed()
        self.assertEqual({r["source"] for r in instrument_search.search(self.profile, "reliance", kind="fund")["results"]}, {"amfi"})
        self.assertEqual({r["source"] for r in instrument_search.search(self.profile, "reliance", kind="share")["results"]}, {"nse"})

    def test_existing_instrument_is_flagged_not_duplicated(self):
        self.seed()
        before = Instrument.objects.count()
        out = instrument_search.search(self.profile, "reliance", kind="share")
        self.assertEqual(out["results"][0]["existing_id"], self.reliance.pk)
        out = instrument_search.search(self.profile, "parag", kind="fund")
        self.assertEqual(out["results"][0]["existing_id"], self.fund.pk)
        self.assertEqual(instrument_search.search(self.profile, "tcs")["results"][0]["existing_id"], None)
        self.assertEqual(Instrument.objects.count(), before)

    def test_constant_query_count(self):
        self.seed()
        with self.assertNumQueries(4):   # the lookup switch, then the lists
            instrument_search.search(self.profile, "reliance")

    def test_network_failure_gives_a_message(self):
        self.net.add("EQUITY_L", 500)
        self.net.add("NAVAll", 500)
        out = instrument_search.search(self.profile, "reliance")
        self.assertEqual(out["results"], [])
        self.assertIn("could not be fetched", out["message"])

    def test_failed_refresh_is_not_repeated_on_every_keystroke(self):
        self.net.add("EQUITY_L", 500)
        instrument_search.search(self.profile, "reliance", kind="share")
        calls = len(self.net.calls)
        self.assertGreater(calls, 0)
        out = instrument_search.search(self.profile, "relianc", kind="share")
        self.assertEqual(len(self.net.calls), calls)
        self.assertIn("could not be fetched", out["message"])

    def test_empty_list_is_fetched_once_on_demand(self):
        self.net.add("EQUITY_L", NSE_CSV)
        out = instrument_search.search(self.profile, "reliance", kind="share")
        self.assertEqual(out["results"][0]["code"], "RELIANCE.NS")
        self.assertEqual(len(self.net.calls), 1)

    def test_short_query_is_empty(self):
        self.assertEqual(instrument_search.search(self.profile, "r"), {"results": [], "message": ""})


class EndpointTests(FakeNetCase):
    def test_requires_login(self):
        resp = Client().get(reverse("investments_add_search"), {"q": "reliance"})
        self.assertIn(resp.status_code, (302, 403))

    def test_json_shape_for_editor(self):
        self.net.add("EQUITY_L", NSE_CSV)
        user, _profile = make_user("ed")
        client = Client()
        client.force_login(user)
        resp = client.get(reverse("investments_add_search"), {"q": "tcs", "kind": "share"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["results"][0]["code"], "TCS.NS")
        self.assertIn("message", body)

    def test_failure_is_json_not_500(self):
        self.net.add("EQUITY_L", 503)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("investments_add_search"), {"q": "reliance", "kind": "share"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["results"], [])
        self.assertTrue(resp.json()["message"])

    def test_add_page_has_picker_and_plain_form(self):
        self.client.force_login(self.user)
        html = self.client.get(reverse("investments_add_2"), {"kind": "share"}).content.decode()
        self.assertIn("data-instrument-picker", html)
        self.assertIn('<form method="get"', html)
        self.assertIn("instrument-picker.js", html)


class FundPlanOptionTests(TestCase):
    def test_find_matches_plan_and_option_fields_and_picker_shows_standard_name(self):
        from investments.services import schemes

        AmfiScheme.objects.create(code="1", name="Foo Fund - Direct Plan - Growth", plan="Direct", option="Growth")
        AmfiScheme.objects.create(code="2", name="Foo Fund-Regular Dividend Payout", plan="Regular", option="IDCW Payout")
        self.assertEqual([s.code for s in schemes.find("foo regular")], ["2"])
        self.assertEqual([s.code for s in schemes.find("foo idcw")], ["2"])
        self.assertEqual([s.code for s in schemes.find("foo dividend")], ["2"])
        self.assertEqual(AmfiScheme.objects.get(code="2").display_name, "Foo Fund Regular Plan IDCW Payout Option")
