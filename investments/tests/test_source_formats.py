"""Admin-editable data source formats: the defaults read exactly what the adapters always read, a changed alias or address is used by
the next fetch, a file that cannot be read is a visible failure, and the Test button shows rows without saving anything.
All network is the fake net; no test calls a live service."""
import io
import json
import zipfile
from datetime import date as d
from decimal import Decimal as D
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import ROLE_EDITOR
from investments.adapters import amfi, bhavcopy, http, mfapi, nse_list, twelvedata, yahoo
from investments.adapters.base import FetchError, FormatError
from investments.models import AmfiScheme, DataSourceFormat, Price, SourceRun
from investments.services import fetch, instrument_search, price_import, source_formats as sf, statement_import
from investments.tests.base import InvTestCase, make_user
from investments.tests.fakehttp import FakeNet, fixture

NSE = ("TckrSymb,SctySrs,ISIN,ClsPric,TradDt\n"
       "RELIANCE,EQ,INE002A01018,1300.50,2026-11-06\n"
       "TCS,EQ,INE467B01029,3200,2026-11-06\n"
       "RELIANCE,N1,INE002A01018,99,2026-11-06\n")

EXTRA_HOSTS = "example.com,example.test,amfi.example.test,nse.example.test,mf.example.test,env.test"


def changed(key, **values):
    """The format of ``key`` with ``values`` laid over it (validated, as a saved change would be)."""
    cleaned, errors = sf.validate(key, values)
    assert not errors, errors
    return sf.merge(key, cleaned)


def lines(text):
    return text.splitlines(keepends=True)


class DefaultsReproduceTodayTests(SimpleTestCase):
    def test_bhavcopy_equity(self):
        found = bhavcopy.read_equity(lines(NSE), symbols=["RELIANCE", "TCS"], isins=["INE467B01029"])
        self.assertEqual(found[("sym", "RELIANCE")], (d(2026, 11, 6), D("1300.5000")))      # the EQ row beats the N1 (bond) row
        self.assertEqual(found[("isin", "INE467B01029")], (d(2026, 11, 6), D("3200.0000")))

    def test_bhavcopy_old_nse_layout_and_bse_codes(self):
        old = "SYMBOL,SERIES,CLOSE,TIMESTAMP\nINFY,EQ,1500,06-NOV-2026\n"
        self.assertEqual(bhavcopy.read_equity(lines(old), symbols=["INFY"])[("sym", "INFY")], (d(2026, 11, 6), D("1500.0000")))
        bse = "FinInstrmId,TckrSymb,ClsPric,TradDt\n500325,RELIANCE,1301,2026-11-06\n"
        self.assertEqual(bhavcopy.read_equity(lines(bse), codes=["500325"], nse=False)[("code", "500325")][1], D("1301.0000"))

    def test_indices(self):
        text = "Index Name,Index Date,Closing Index Value\nNifty 50,06-11-2026,24000.5\n"
        self.assertEqual(bhavcopy.read_indices(lines(text), ["nifty 50"]), {"nifty 50": (d(2026, 11, 6), D("24000.5000"))})

    def test_amfi_and_list_lines(self):
        found = amfi.parse_lines(lines(fixture("amfi_navall.txt").decode()), ["122639"])
        self.assertEqual(found["122639"][:2], (d(2026, 11, 5), D("81.4012")))
        self.assertEqual(found["122639"][3], "INF879O01027")
        rows = list(amfi.iter_all(lines(fixture("amfi_navall.txt").decode())))
        self.assertIn(("122639", "Parag Parikh Flexi Cap Fund - Direct Plan - Growth", "INF879O01027", d(2026, 11, 5), D("81.4012")), rows)

    def test_defaults_match_the_old_constants(self):
        self.assertEqual(bhavcopy.SERIES_ORDER, ("EQ", "BE", "BZ", "SM", "ST", "RR", "IV", ""))
        self.assertEqual(amfi.DEFAULT_URL, "https://www.amfiindia.com/spages/NAVAll.txt")
        self.assertEqual(sf.DEFAULTS["mfapi"]["url"].format(code=1), "https://api.mfapi.in/mf/1")
        self.assertEqual(bhavcopy.url_for("nse_eq", d(2026, 11, 6)), "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20261106_F_0000.csv.zip")
        self.assertEqual(bhavcopy.url_for("nse_idx", d(2026, 11, 6)), "https://nsearchives.nseindia.com/content/indices/ind_close_all_06112026.csv")

    def test_json_sources(self):
        self.assertEqual(len(mfapi.parse(fixture("mfapi_122639.json")).rows), 3)
        out = yahoo.parse_chart(fixture("yahoo_chart_reliance.json"))
        self.assertTrue(out.rows)
        body = json.dumps({"status": "ok", "meta": {"currency": "INR", "exchange": "NSE"}, "values": [{"datetime": "2026-11-05", "close": "100.5"}]})
        self.assertEqual(twelvedata.parse(body.encode()).rows, [(d(2026, 11, 5), D("100.5"))])


class TolerantHeaderTests(SimpleTestCase):
    def test_match_ignores_case_spacing_underscores_and_bom(self):
        index = sf.match_columns(["\ufeffTckr_Symb ", "  CLS   PRIC"], {"symbol": ["tckr symb"], "close": ["Cls_Pric"], "date": ["Date"]})
        self.assertEqual(index, {"symbol": 0, "close": 1, "date": None})

    def test_first_alias_wins_not_first_column(self):
        index = sf.match_columns(["Close", "ClsPric"], {"close": ["ClsPric", "Close"]})
        self.assertEqual(index["close"], 1)

    def test_renamed_reordered_case_changed_headers_parse_with_aliases(self):
        text = "trade  date;closing_price;Ticker Symbol;ISIN\n2026-11-06;1300.5;RELIANCE;INE002A01018\n"
        fmt = changed("nse_eq", delimiter=";", columns={"symbol": ["ticker symbol"], "close": ["Closing Price"], "date": ["TRADE DATE"]})
        found = bhavcopy.read_equity(lines(text), symbols=["RELIANCE"], fmt=fmt)
        self.assertEqual(found[("sym", "RELIANCE")], (d(2026, 11, 6), D("1300.5000")))

    def test_header_row_and_date_formats(self):
        text = "Bhavcopy for the day\nTckrSymb,ClsPric,TradDt\nTCS,3200,06/11/2026\n"
        fmt = changed("nse_eq", header_row=1)
        self.assertEqual(bhavcopy.read_equity(lines(text), symbols=["TCS"], fmt=fmt)[("sym", "TCS")][0], d(2026, 11, 6))

    def test_series_filter_is_configurable(self):
        text = "TckrSymb,SctySrs,ClsPric,TradDt\nTCS,XX,3200,2026-11-06\n"
        self.assertEqual(bhavcopy.read_equity(lines(text), symbols=["TCS"]), {})
        fmt = changed("nse_eq", series_keep=["XX"])
        self.assertIn(("sym", "TCS"), bhavcopy.read_equity(lines(text), symbols=["TCS"], fmt=fmt))

    def test_amfi_positions_and_nse_list_aliases(self):
        row = "122639;INF879O01027;-;Some Fund;06-Nov-2026;81.4;extra\n" * 1
        fmt = changed("amfi", nav_col=5, date_col=4, min_fields=5)
        self.assertEqual(amfi.parse_lines([row], ["122639"], fmt)["122639"][:2], (d(2026, 11, 6), D("81.4000")))
        text = "Ticker,Company Name,Series,ISIN Number\nTCS,Tata Consultancy,EQ,INE467B01029\n"
        fmt = changed("nse_list", columns={"symbol": ["ticker"], "name": ["company name"]})
        self.assertEqual(list(nse_list.iter_all(lines(text), fmt)), [("TCS", "Tata Consultancy", "INE467B01029", "EQ")])

    def test_json_paths_and_keys(self):
        body = json.dumps({"payload": {"navs": [{"d": "05-11-2026", "v": "81.4"}]}, "info": {"n": "A Fund"}}).encode()
        fmt = changed("mfapi", rows_path=["payload", "navs"], date_key="d", nav_key="v", name_path=["info", "n"])
        out = mfapi.parse(body, fmt=fmt)
        self.assertEqual((out.rows, out.name), ([(d(2026, 11, 5), D("81.4"))], "A Fund"))
        chart = {"chart": {"result": [{"meta": {"gmtoffset": 0}, "timestamp": [1762300800], "px": {"c": [101.25]}}], "error": None}}
        out = yahoo.parse_chart(json.dumps(chart).encode(), fmt=changed("yahoo", closes_path=["px", "c"]))
        self.assertEqual(out.rows, [(d(2025, 11, 5), D("101.2500"))])


class ReadFailuresAreErrorsTests(SimpleTestCase):
    def test_missing_column_names_it_and_the_headers_seen(self):
        with self.assertRaises(FormatError) as cm:
            bhavcopy.read_equity(lines("TckrSymb,Price,TradDt\nTCS,1,2026-11-06\n"), symbols=["TCS"])
        self.assertEqual(cm.exception.key, "nse_eq")
        self.assertIn("close", cm.exception.missing)
        self.assertIn("Headers seen: TckrSymb, Price, TradDt", str(cm.exception))
        self.assertIsInstance(cm.exception, FetchError)

    def test_zero_rows_from_a_non_empty_file(self):
        with self.assertRaises(FormatError):
            bhavcopy.read_equity(lines("TckrSymb,ClsPric,TradDt\nTCS,abc,not a date\nINFY,x,y\n"), symbols=["TCS"])
        with self.assertRaises(FormatError):
            bhavcopy.read_indices(lines("Index Name,Index Date,Closing Index Value\nNifty 50,??,??\n"))
        with self.assertRaises(FormatError):
            list(amfi.iter_all(["<html>", "moved;to;a;new;site;now;ok"]))
        with self.assertRaises(FormatError):
            amfi.parse_lines(["Code;Name;Price", "x;y;z"], ["1"])

    def test_a_wanted_key_that_is_not_in_a_good_file_is_not_an_error(self):
        self.assertEqual(bhavcopy.read_equity(lines(NSE), symbols=["NOSUCH"]), {})

    def test_other_sources(self):
        with self.assertRaises(FormatError):
            list(nse_list.iter_all(lines("SYMBOL,SERIES\nTCS,EQ\n")))
        with self.assertRaises(FormatError):
            list(nse_list.iter_all(lines("Code,Company,Kind,Isin\nTCS,Tata,EQ,x\n")))
        with self.assertRaises(FormatError):
            mfapi.parse(json.dumps({"data": [{"when": "05-11-2026", "value": "1"}]}).encode())
        with self.assertRaises(FormatError):
            mfapi.parse(json.dumps({"rows": []}).encode())
        with self.assertRaises(FormatError):
            yahoo.parse_chart(json.dumps({"other": 1}).encode())
        with self.assertRaises(FormatError):
            twelvedata.parse(json.dumps({"status": "ok", "values": [{"day": "2026-11-05", "px": "1"}]}).encode())


@override_settings(INVESTMENTS_EXTRA_SOURCE_HOSTS=EXTRA_HOSTS)
class ValidationTests(SimpleTestCase):
    def bad(self, key, **values):
        cleaned, errors = sf.validate(key, values)
        self.assertTrue(errors, values)
        return errors

    def test_rejects_bad_config(self):
        self.bad("nse_eq", nonsense=1)
        self.bad("nse_eq", url="ftp://example.com/x")
        self.bad("nse_eq", url="javascript:alert(1)")
        self.bad("nse_eq", url="https://example.com/{__class__}")
        self.bad("nse_eq", url="https://example.com/{ymd")
        self.bad("nse_eq", url="https://example.com/" + "a" * 600)
        self.bad("nse_eq", url="https://exa mple.com/")
        self.bad("mfapi", url="https://example.com/{ymd}")                 # a date placeholder where only {code} is allowed
        self.bad("nse_eq", delimiter=",,")
        self.bad("nse_eq", header_row="2")
        self.bad("nse_eq", header_row=-1)
        self.bad("nse_eq", header_row=True)
        self.bad("nse_eq", date_formats=["not a format"])
        self.bad("nse_eq", date_formats=[])
        self.bad("nse_eq", columns={"colour": ["x"]})
        self.bad("nse_eq", columns={"symbol": "TckrSymb"})
        self.bad("nse_eq", columns={"symbol": ["x" * 200]})
        self.bad("nse_eq", columns=["x"])
        self.bad("yahoo", closes_path=[])
        self.bad("yahoo", closes_path=["a", {"b": 1}])
        self.bad("yahoo", closes_path="indicators.close")
        self.bad("mfapi", date_key="")
        self.assertTrue(sf.validate("nosuch", {})[1])
        self.assertTrue(sf.validate("amfi", "text")[1])

    def test_accepts_good_config(self):
        cleaned, errors = sf.validate("nse_eq", {"url": "https://example.com/{yyyy}/{mm}/{dd}/{MON}/f.csv", "delimiter": "|", "header_row": 2,
                                                 "date_formats": ["%d %b %Y"], "columns": {"symbol": ["a", "b"]}, "series_keep": ["EQ"]})
        self.assertEqual(errors, [])
        self.assertEqual(cleaned["columns"], {"symbol": ["a", "b"]})
        self.assertEqual(sf.validate("yahoo", {"closes_path": ["x", 0, "c"]})[0], {"closes_path": ["x", 0, "c"]})

    def test_expand_is_a_whitelist_and_never_formats_attributes(self):
        day = d(2026, 11, 6)
        self.assertEqual(sf.expand("{yyyy}-{mm}-{dd}-{yy}-{ymd}-{dmy}-{MON}-{Mon}", day), "2026-11-06-26-20261106-06112026-NOV-Nov")
        self.assertEqual(sf.expand("{code}/{__class__}", code="7"), "7/{__class__}")

    def test_dig(self):
        self.assertEqual(sf.dig({"a": [{"b": 5}]}, ["a", 0, "b"]), 5)
        self.assertIsNone(sf.dig({"a": []}, ["a", 0, "b"]))
        self.assertEqual(sf.dig({"a": 1}, ["a", "b"], "none"), "none")

    def test_form_round_trip(self):
        post = {"f_" + name: sf.show(value, kind) for name, kind, value in sf.fields("yahoo", sf.default("yahoo"))}
        post["f_closes_path"] = "px.0.c"
        submitted, errors = sf.parse_form("yahoo", post)
        self.assertEqual((errors, submitted["closes_path"]), ([], ["px", 0, "c"]))
        self.assertEqual(sf.validate("yahoo", submitted)[1], [])


@override_settings(INVESTMENTS_EXTRA_SOURCE_HOSTS=EXTRA_HOSTS)
class StoredConfigTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.net = FakeNet()
        for target, value in ((http, "_urlopen"), ):
            p = mock.patch.object(target, value, self.net)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(http, "sleep", lambda s: None)
        p.start()
        self.addCleanup(p.stop)

    def test_get_merges_stored_over_defaults_and_reset_restores(self):
        merged, errors = sf.save("nse_eq", {"columns": {"close": ["Settle"]}, "delimiter": ","}, self.user)
        self.assertEqual(errors, [])
        self.assertEqual(sf.stored_config("nse_eq"), {"columns": {"close": ["Settle"]}})        # only the difference is stored
        fmt = sf.get("nse_eq")
        self.assertEqual(fmt["columns"]["close"], ["Settle"])
        self.assertEqual(fmt["columns"]["symbol"], sf.DEFAULTS["nse_eq"]["columns"]["symbol"])
        self.assertEqual(sf.DEFAULTS["nse_eq"]["columns"]["close"], ["ClsPric", "CLOSE"])        # the built-in format is untouched
        sf.reset("nse_eq")
        self.assertEqual(sf.get("nse_eq")["columns"]["close"], ["ClsPric", "CLOSE"])
        self.assertFalse(DataSourceFormat.objects.exists())

    def test_saving_the_built_in_values_stores_nothing(self):
        sf.save("amfi", {"url": sf.DEFAULTS["amfi"]["url"], "nav_col": -2}, self.user)
        self.assertFalse(DataSourceFormat.objects.exists())

    def test_invalid_stored_config_falls_back_to_the_built_in_format(self):
        DataSourceFormat.objects.create(key="amfi", config={"url": "ftp://bad"})
        self.assertEqual(sf.get("amfi")["url"], sf.DEFAULTS["amfi"]["url"])

    def test_adapters_use_the_stored_address_and_columns(self):
        sf.save("amfi", {"url": "https://amfi.example.test/nav.txt"}, self.user)
        self.net.add("amfi.example.test", fixture("amfi_navall.txt"))
        self.assertEqual(amfi.fetch(["122639"])["122639"][1], D("81.4012"))
        self.assertTrue(self.net.calls[0].startswith("https://amfi.example.test/nav.txt"))
        sf.save("nse_eq", {"url": "https://nse.example.test/{yyyy}{mm}{dd}.csv", "columns": {"close": ["Settle Price"]}}, self.user)
        self.assertEqual(bhavcopy.url_for("nse_eq", d(2026, 11, 6)), "https://nse.example.test/20261106.csv")
        text = "TckrSymb,Settle Price,TradDt\nTCS,3200,2026-11-06\n"
        self.assertEqual(bhavcopy.read_equity(lines(text), symbols=["TCS"])[("sym", "TCS")][1], D("3200.0000"))
        sf.save("mfapi", {"url": "https://mf.example.test/mf/{code}.json"}, self.user)
        self.net.add("mf.example.test", fixture("mfapi_122639.json"))
        mfapi.fetch("122639")
        self.assertIn("https://mf.example.test/mf/122639.json", self.net.calls)

    def test_the_environment_address_applies_until_an_admin_sets_one(self):
        with self.settings(INVESTMENTS_AMFI_URL="https://env.test/nav.txt"):
            self.net.add("env.test", fixture("amfi_navall.txt"))
            amfi.fetch(["122639"])
            self.assertTrue(self.net.calls[-1].startswith("https://env.test/"))
            sf.save("amfi", {"url": "https://example.test/nav.txt"}, self.user)
            self.net.add("example.test", fixture("amfi_navall.txt"))
            amfi.fetch(["122639"])
            self.assertTrue(self.net.calls[-1].startswith("https://example.test/"))

    def test_imports_accept_renamed_columns_once_aliases_are_added(self):
        header = "Scrip,When,Rate\nRELIANCE.NS,2026-11-02,1300\n"
        path = _csv(header)
        with self.assertRaises(Exception) as cm:
            price_import.dry_run(path, today=d(2026, 11, 9))
        self.assertIn("No column found for: symbol, date", str(getattr(cm.exception, "message", cm.exception)))
        self.assertIn("Headings in the file: Scrip, When, Rate", str(getattr(cm.exception, "message", cm.exception)))
        sf.save("price_import", {"columns": {"symbol": ["scrip"], "date": ["when"], "close": ["rate"]}}, self.user)
        report = price_import.dry_run(path, today=d(2026, 11, 9))
        self.assertEqual((report.rows, report.blocking_count), (1, 0))
        self.assertNotIn(0, statement_import.guess_columns(["Trade Dt", "Scrip", "Qty"]).values())
        self.assertNotIn("date", statement_import.guess_columns(["Trade Dt", "Scrip", "Qty"]))
        sf.save("statement_import", {"columns": {"date": ["trade dt"]}}, self.user)
        self.assertEqual(statement_import.guess_columns(["Trade Dt", "Scrip", "Qty"]), {"date": 0, "investment": 1, "units": 2})


def _csv(text):
    import tempfile
    from pathlib import Path

    handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
    handle.write(text)
    handle.close()
    return Path(handle.name)


class VisibleFailureTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.net = FakeNet()
        for target, value in ((http, "_urlopen"), ):
            p = mock.patch.object(target, value, self.net)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(http, "sleep", lambda s: None)
        p.start()
        self.addCleanup(p.stop)
        self.buy(d(2026, 10, 1), 10, 80, instrument=self.fund)
        instrument_search.set_lookup_enabled(False)          # the weekly list downloads are not what these tests are about

    def run_fetch(self):
        return fetch.fetch_prices(today=d(2026, 11, 9), rng=lambda: 0.0)

    def test_unreadable_amfi_file_is_a_sourcerun_failure_and_an_alert(self):
        self.net.add("amfiindia", b"Code;Name;Price\nfoo;bar;baz;1;2;3\n")
        self.net.add("mfapi.in", 404)
        self.run_fetch()
        run = SourceRun.objects.filter(source="amfi").first()
        entry = run.failures[0]
        self.assertEqual((entry["name"], entry["fmt"]), ("AMFI daily file", "amfi"))
        self.assertIn("none could be read", entry["error"])
        self.client.force_login(self.user)
        response = self.client.get(reverse("investments_alerts"))
        self.assertContains(response, 'data-table-id="inv-format-problems"')
        self.assertContains(response, "AMFI daily NAV file")
        self.assertContains(response, reverse("investments_admin_source_format", args=["amfi"]))

    def test_the_alert_goes_when_a_later_run_reads_the_file(self):
        self.net.add("amfiindia", b"junk;line;only\nmore;junk;here\n")
        self.net.add("mfapi.in", 404)
        self.run_fetch()
        self.assertEqual([p["key"] for p in sf.problems()], ["amfi"])
        self.net.routes.clear()
        self.net.add("amfiindia", fixture("amfi_navall.txt"))
        self.net.add("mfapi.in", fixture("mfapi_122639.json"))
        self.run_fetch()
        self.assertEqual(sf.problems(), [])
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse("investments_alerts")), "inv-format-problems")

    def test_missing_bhavcopy_column_is_reported_on_the_run(self):
        from investments.services import bhav

        self.buy(d(2026, 10, 1), 10, 1000)
        for day in (d(2026, 11, 2), d(2026, 11, 3)):
            Price.objects.create(instrument=self.reliance, date=day, close=D("1000"), source="api")
        bhav.set_mode(bhav.MODE_FIRST)
        bhavcopy.clear_cache()
        self.addCleanup(bhavcopy.clear_cache)
        self.net.add("nsearchives", b"TckrSymb,Price,TradDt\nRELIANCE,1,2026-11-06\n")
        self.net.add("bseindia", 404)
        self.net.add("chart", 404)
        self.run_fetch()
        run = SourceRun.objects.filter(source="bhavcopy").first()
        self.assertTrue(any(f.get("fmt") == "nse_eq" and "close" in f["error"] for f in run.failures))
        self.assertIn("nse_eq", [p["key"] for p in sf.problems()])

    def test_a_run_that_tried_nothing_does_not_hide_the_alert(self):
        from django.utils import timezone

        self.net.add("amfiindia", b"junk;line;only\nmore;junk;here\n")
        self.net.add("mfapi.in", 404)
        self.run_fetch()
        now = timezone.now()
        SourceRun.objects.create(source="amfi", trigger="manual", started=now, finished=now, tried=0)
        self.assertEqual([p["key"] for p in sf.problems()], ["amfi"])
        SourceRun.objects.create(source="amfi", trigger="manual", started=now, finished=now, tried=3)
        self.assertEqual([p["key"] for p in sf.problems()], ["amfi"])       # tried something, but never read the AMFI file
        SourceRun.objects.create(source="amfi", trigger="manual", started=now, finished=now, tried=3, formats=["amfi"])
        self.assertEqual(sf.problems(), [])

    def test_a_run_that_read_another_format_of_the_source_keeps_the_alert(self):
        from django.utils import timezone

        now = timezone.now()
        SourceRun.objects.create(source="bhavcopy", trigger="cron", started=now, finished=now, tried=2,
                                 failures=[{"id": 0, "name": "NSE bhavcopy", "error": "no close column", "fmt": "nse_eq"}], formats=["bse_eq"])
        SourceRun.objects.create(source="bhavcopy", trigger="cron", started=now, finished=now, tried=2, formats=["bse_eq"])
        self.assertEqual([p["key"] for p in sf.problems()], ["nse_eq"])
        SourceRun.objects.create(source="bhavcopy", trigger="cron", started=now, finished=now, tried=2, formats=["nse_eq", "bse_eq"])
        self.assertEqual(sf.problems(), [])

    def test_nse_list_and_scheme_list_failures_are_recorded_and_cleared(self):
        from investments.services import nse_list as nse_service

        self.net.add("EQUITY_L", b"Code,Company,Kind,Isin\nTCS,Tata,EQ,x\n")
        with self.assertRaises(FormatError) as cm:
            nse_service.refresh(force=True)
        sf.record_failure("nse_list", "NSE equity list", cm.exception)
        self.assertEqual([p["key"] for p in sf.problems()], ["nse_list"])
        sf.clear_failure("nse_list")
        self.assertEqual(sf.problems(), [])


@override_settings(INVESTMENTS_EXTRA_SOURCE_HOSTS=EXTRA_HOSTS)
class AdminPageTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.net = FakeNet()
        for target, value in ((http, "_urlopen"), ):
            p = mock.patch.object(target, value, self.net)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(http, "sleep", lambda s: None)
        p.start()
        self.addCleanup(p.stop)

    def post(self, key, action, edits=None, **extra):
        data = {"f_" + name: sf.show(value, kind) for name, kind, value in sf.fields(key)}
        data.update({"f_" + k: v for k, v in (edits or {}).items()})
        data["action"] = action
        data.update(extra)
        return self.client.post(reverse("investments_admin_source_format", args=[key]), data)

    def test_list_and_edit_pages(self):
        response = self.client.get(reverse("investments_admin_source_formats"))
        self.assertContains(response, 'data-table-id="inv-source-formats"')
        for key in sf.KEYS:
            self.assertContains(response, reverse("investments_admin_source_format", args=[key]))
            page = self.client.get(reverse("investments_admin_source_format", args=[key]))
            self.assertContains(page, 'data-table-id="inv-source-format-fields"')
        self.assertEqual(self.client.get(reverse("investments_admin_source_format", args=["nosuch"])).status_code, 404)
        self.assertContains(self.client.get(reverse("investments_admin_prices")), reverse("investments_admin_source_formats"))

    def test_only_an_admin_may_see_or_change_them(self):
        editor, _ = make_user("ed3", ROLE_EDITOR, profile=self.profile)
        self.client.force_login(editor)
        self.assertEqual(self.client.get(reverse("investments_admin_source_formats")).status_code, 403)
        self.assertEqual(self.client.get(reverse("investments_admin_source_format", args=["amfi"])).status_code, 403)
        self.assertEqual(self.post("amfi", "save", {"url": "https://example.test/x"}).status_code, 403)
        self.assertEqual(self.post("amfi", "reset").status_code, 403)
        self.assertFalse(DataSourceFormat.objects.exists())

    def test_csrf_is_enforced(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(reverse("investments_admin_source_format", args=["amfi"]), {"action": "reset"})
        self.assertEqual(response.status_code, 403)

    def test_save_then_reset(self):
        response = self.post("nse_eq", "save", {"columns.close": "Settle Price, ClsPric"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(sf.stored_config("nse_eq"), {"columns": {"close": ["Settle Price", "ClsPric"]}})
        page = self.client.get(reverse("investments_admin_source_format", args=["nse_eq"]))
        self.assertContains(page, "Reset to default")
        self.assertContains(page, "Settle Price, ClsPric")
        self.assertEqual(self.post("nse_eq", "reset").status_code, 302)
        self.assertEqual(sf.stored_config("nse_eq"), {})

    def test_bad_values_are_refused_with_a_message_and_nothing_is_saved(self):
        response = self.post("amfi", "save", {"url": "ftp://example.test/x"})
        self.assertContains(response, "Not saved or tested")
        self.assertContains(response, "http://")
        self.assertContains(response, "ftp://example.test/x")                      # what was typed stays in the box
        response = self.post("amfi", "save", {"nav_col": "abc"})
        self.assertContains(response, "whole number")
        self.assertFalse(DataSourceFormat.objects.exists())

    def test_test_button_with_an_uploaded_sample_shows_rows_and_saves_nothing(self):
        sample = SimpleUploadedFile("sample.csv", NSE.encode())
        response = self.post("nse_eq", "test", sample=sample)
        self.assertContains(response, 'data-table-id="inv-source-format-test"')
        self.assertContains(response, "RELIANCE")
        self.assertContains(response, "1300.50")
        self.assertFalse(DataSourceFormat.objects.exists())
        self.assertFalse(Price.objects.exists())
        self.assertFalse(SourceRun.objects.exists())

    def test_test_button_uses_the_values_as_typed(self):
        text = "TckrSymb,Settle,TradDt\nTCS,3200,2026-11-06\n"
        shown = self.post("nse_eq", "test", sample=SimpleUploadedFile("s.csv", text.encode()))
        self.assertContains(shown, "no column found for close")
        shown = self.post("nse_eq", "test", {"columns.close": "Settle"}, sample=SimpleUploadedFile("s.csv", text.encode()))
        self.assertContains(shown, "3200")
        self.assertEqual(sf.stored_config("nse_eq"), {})

    def test_test_button_downloads_a_sample_through_the_fake_net(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("BhavCopy.csv", NSE)
        self.net.add("nsearchives", buffer.getvalue())
        response = self.post("nse_eq", "test")
        self.assertContains(response, "TCS")
        self.assertContains(response, "BhavCopy_NSE_CM_0_0_0_")
        self.net.routes.clear()
        self.net.add("amfiindia", fixture("amfi_navall.txt"))
        self.assertContains(self.post("amfi", "test"), "Parag Parikh Flexi Cap Fund - Direct Plan - Growth")
        self.net.routes.clear()
        self.net.add("mfapi.in", fixture("mfapi_122639.json"))
        response = self.post("mfapi", "test", sample_value="122639")
        self.assertContains(response, "81.4012")
        self.assertIn("https://api.mfapi.in/mf/122639", self.net.calls)
        self.net.routes.clear()
        self.net.add("chart", fixture("yahoo_chart_reliance.json"))
        self.assertContains(self.post("yahoo", "test", sample_value="RELIANCE.NS"), "data-table-id=\"inv-source-format-test\"")

    def test_test_button_shows_errors_not_a_crash(self):
        self.net.add("amfiindia", b"<html>moved</html>")
        self.assertContains(self.post("amfi", "test"), "none could be read")
        self.net.routes.clear()
        self.net.add("amfiindia", 500)
        self.assertContains(self.post("amfi", "test"), "HTTP 500")
        self.assertContains(self.post("amfi", "test", sample=SimpleUploadedFile("e.txt", b"   ")), "The sample is empty")
        self.assertContains(self.post("price_import", "test"), "Choose a sample file")
        broken = SimpleUploadedFile("s.csv", b"PK\x03\x04 not a zip")
        self.assertContains(self.post("nse_eq", "test", sample=broken), "zip could not be opened")

    def test_test_button_for_the_import_columns(self):
        sample = SimpleUploadedFile("p.csv", b"Scrip,When,Rate\nX,2026-11-02,5\n")
        self.assertContains(self.post("price_import", "test", sample=sample), "No column found for symbol, date")
        sample = SimpleUploadedFile("p.csv", b"Scrip,When,Rate\nX,2026-11-02,5\n")
        response = self.post("price_import", "test", {"columns.symbol": "scrip", "columns.date": "when", "columns.close": "rate"}, sample=sample)
        self.assertContains(response, 'data-table-id="inv-source-format-test"')
        self.assertContains(response, "Scrip")
        sample = SimpleUploadedFile("s.csv", b"Date,Symbol,Units\n2026-11-02,X,5\n")
        self.assertContains(self.post("statement_import", "test", sample=sample), "Units")


class HostRestrictionTests(SimpleTestCase):
    def test_other_hosts_are_refused_unless_the_owner_lists_them(self):
        cleaned, errors = sf.validate("amfi", {"url": "https://evil.example/nav.txt"})
        self.assertTrue(errors)
        self.assertIn("not allowed", errors[0])
        with override_settings(INVESTMENTS_EXTRA_SOURCE_HOSTS="evil.example"):
            cleaned, errors = sf.validate("amfi", {"url": "https://evil.example/nav.txt"})
            self.assertFalse(errors)

    def test_built_in_host_with_a_new_path_is_fine(self):
        cleaned, errors = sf.validate("amfi", {"url": "https://www.amfiindia.com/new/NAVAll.txt"})
        self.assertFalse(errors, errors)

    def test_userinfo_trick_is_refused(self):
        cleaned, errors = sf.validate("amfi", {"url": "https://www.amfiindia.com@evil.example/nav.txt"})
        self.assertTrue(errors)

    def test_key_placeholder_only_on_the_built_in_host(self):
        good = "https://api.twelvedata.com/v2/series?symbol={symbol}&apikey={key}"
        self.assertFalse(sf.validate("twelvedata", {"url": good})[1])
        with override_settings(INVESTMENTS_EXTRA_SOURCE_HOSTS="mine.example"):
            cleaned, errors = sf.validate("twelvedata", {"url": "https://mine.example/x?symbol={symbol}&apikey={key}"})
            self.assertTrue(errors)
            self.assertIn("{key}", errors[0])
            self.assertFalse(sf.validate("twelvedata", {"url": "https://mine.example/x?symbol={symbol}"})[1])


class PublicAddressGuardTests(SimpleTestCase):
    def check(self, url, addresses):
        infos = [(2, 1, 6, "", (a, 0)) for a in addresses]
        with mock.patch.object(http.socket, "getaddrinfo", return_value=infos):
            http.check_public(url)

    def test_private_loopback_and_link_local_are_refused(self):
        for address in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "172.16.0.1", "::1"):
            with self.assertRaises(FetchError, msg=address):
                self.check("https://x.example/f", [address])

    def test_any_private_answer_among_several_refuses(self):
        with self.assertRaises(FetchError):
            self.check("https://x.example/f", ["93.184.216.34", "10.0.0.1"])

    def test_public_address_passes(self):
        self.check("https://x.example/f", ["93.184.216.34"])

    def test_connection_to_a_private_peer_is_refused_and_closed(self):
        class Conn:
            host, closed = "x.example", False

            class sock:
                @staticmethod
                def getpeername():
                    return ("10.0.0.1", 443)

            def close(self):
                self.closed = True

        conn = Conn()
        with self.assertRaises(FetchError):
            http._check_peer(conn)
        self.assertTrue(conn.closed)
        conn.sock = mock.Mock(getpeername=lambda: ("93.184.216.34", 443))
        http._check_peer(conn)

    def test_only_the_database_refusal_of_a_unit_test_is_tolerated(self):
        with mock.patch("django.db.transaction.atomic"), mock.patch("investments.models.DataSourceFormat.objects") as objects:
            objects.filter.side_effect = AssertionError("Database queries to 'default' are not allowed in SimpleTestCase")
            self.assertEqual(sf.stored_config("amfi"), {})
            objects.filter.side_effect = AssertionError("a real bug")
            with self.assertRaises(AssertionError):
                sf.stored_config("amfi")

    def test_redirect_to_a_private_host_is_refused(self):
        handler = http._GuardedRedirect()
        request = http._request("https://x.example/f")
        with mock.patch.object(http.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("169.254.169.254", 0))]):
            with self.assertRaises(FetchError):
                handler.redirect_request(request, None, 302, "Found", {}, "http://metadata.internal/latest")

    def test_default_opener_checks_before_connecting(self):
        with mock.patch.object(http.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 0))]):
            with self.assertRaises(FetchError):
                http.open_url("http://localhost:9/x")


class AmfiListIsAllOrNothingTests(InvTestCase):
    def test_changed_layout_leaves_the_stored_list_untouched(self):
        from investments.services import schemes

        AmfiScheme.objects.create(code="100", name="Old name", isin="INF000000001")
        body = "".join(f"{100 + i};INF{i:09d};-;Scheme {i};10.5;not a date\n" for i in range(700)).encode()
        net = FakeNet()
        net.add("NAVAll", body)
        with mock.patch.object(http, "_urlopen", net), mock.patch.object(http, "sleep", lambda s: None):
            with self.assertRaises(FormatError):
                schemes.refresh(force=True)
        self.assertEqual(AmfiScheme.objects.count(), 1)
        self.assertEqual(AmfiScheme.objects.get(code="100").name, "Old name")


class TestButtonLimitsTests(TestCase):
    def test_oversized_csv_field_is_an_error_not_a_crash(self):
        from investments.services import source_format_test

        body = b"Index Name,Index Date,Closing Index Value\n" + b"x" * 200_000 + b",06-11-2026,1\n"
        result = source_format_test.run("nse_idx", sf.get("nse_idx"), upload=body)
        self.assertTrue(result["error"])

    def test_zip_declaring_too_much_is_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("a.csv", "a,b\n1,2\n")
        with mock.patch.object(bhavcopy, "MAX_UNZIPPED", 3):
            with self.assertRaises(FetchError):
                bhavcopy.lines_of("nse_eq", buf.getvalue())
