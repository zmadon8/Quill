"""The history upload, the Update Prices endpoint and the Price sources page."""
import io
import tempfile
from datetime import date as d
from decimal import Decimal as D
from pathlib import Path
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from investments.adapters import http
from investments.errors import InvestmentsError
from investments.models import ManualPrice, Price
from investments.services import fetch, masters, price_import, prices
from investments.tests.base import InvTestCase, make_user
from investments.tests.fakehttp import FakeNet, fixture

HEADER = "symbol,date,close,basis\n"


def csv_file(text):
    handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
    handle.write(text)
    handle.close()
    return Path(handle.name)


class ImportTests(InvTestCase):
    def test_dry_run_reports_without_writing(self):
        path = csv_file(HEADER + "RELIANCE.NS,2026-11-02,1300,split_adjusted\nRELIANCE.NS,2026-11-03,1310,\nNOSUCH.NS,2026-11-03,5,\n")
        report = price_import.dry_run(path, today=d(2026, 11, 9))
        self.assertEqual((report.rows, report.blocking_count, report.unknown), (3, 0, {"NOSUCH.NS": 1}))
        self.assertEqual(report.per_instrument[self.reliance.pk]["count"], 2)
        self.assertEqual(Price.objects.count(), 0)
        self.assertTrue(report.can_apply)

    def test_apply_writes_upload_rows_replacing_fetched_but_not_manual(self):
        Price.objects.create(instrument=self.reliance, date=d(2026, 11, 2), close=D(1), source="api", basis="split_adjusted")
        ManualPrice.objects.create(instrument=self.reliance, date=d(2026, 11, 3), close=D(777))
        path = csv_file(HEADER + "RELIANCE.NS,2026-11-02,1300,\nRELIANCE.NS,2026-11-03,1310,\n")
        written = price_import.apply(path, today=d(2026, 11, 9))
        self.assertEqual(written, 2)
        row = Price.objects.get(instrument=self.reliance, date=d(2026, 11, 2))
        self.assertEqual((row.close, row.source), (D("1300"), "upload"))
        self.assertEqual(prices.latest_prices([self.reliance.pk], d(2026, 11, 9))[self.reliance.pk], (d(2026, 11, 3), D(777)))
        self.assertGreater(fetch.price_version(), 0)

    def test_bad_rows_block_the_whole_file(self):
        path = csv_file(HEADER + "RELIANCE.NS,2026-11-02,1300,\nRELIANCE.NS,not-a-date,1,\nRELIANCE.NS,2026-11-04,0,\nRELIANCE.NS,2099-01-01,5,\n"
                        "RELIANCE.NS,2026-11-05,9,raw\n")
        report = price_import.dry_run(path, today=d(2026, 11, 9))
        self.assertEqual(report.blocking_count, 4)
        self.assertFalse(report.can_apply)
        with self.assertRaises(InvestmentsError):
            price_import.apply(path, today=d(2026, 11, 9))
        self.assertEqual(Price.objects.count(), 0)

    def test_dates_in_day_first_format_and_isin_and_scheme_code(self):
        masters.update_shared_details(self.profile, self.user, self.reliance, isin="INE002A01018")
        path = csv_file("ISIN,Date,Closing Price\nINE002A01018,02.11.2026,\"1,300.50\"\n122639,03.11.2026,80\n")
        report = price_import.dry_run(path, today=d(2026, 11, 9))
        self.assertEqual(report.blocking_count, 0)
        self.assertEqual(len(report.per_instrument), 2)
        price_import.apply(path, today=d(2026, 11, 9))
        self.assertEqual(Price.objects.get(instrument=self.reliance).close, D("1300.50"))

    def test_gaps_big_moves_duplicates_and_differences_are_reported(self):
        Price.objects.create(instrument=self.reliance, date=d(2026, 1, 5), close=D(100), source="api", basis="split_adjusted")
        path = csv_file(HEADER + "RELIANCE.NS,2026-01-02,100,\nRELIANCE.NS,2026-01-05,110,\nRELIANCE.NS,2026-01-05,111,\nRELIANCE.NS,2026-02-20,50,\n")
        report = price_import.dry_run(path, today=d(2026, 11, 9))
        self.assertEqual(report.duplicates, 1)
        self.assertEqual(report.gaps[0][1:], (d(2026, 1, 5), d(2026, 2, 20)))
        self.assertEqual(report.big_moves[0][1], d(2026, 2, 20))
        self.assertGreaterEqual(report.difference_count, 1)

    def test_file_problems(self):
        with self.assertRaises(InvestmentsError):
            price_import.dry_run(csv_file("a,b\n1,2\n"))                       # no symbol/date/close columns
        with self.assertRaises(InvestmentsError):
            price_import.dry_run(csv_file(""))

    def test_ambiguous_symbols_are_skipped(self):
        masters.create_instrument(self.profile, self.user, kind="share", name="Reliance BSE", code="RELIANCE.NS", allow_duplicate=True)
        report = price_import.dry_run(csv_file(HEADER + "RELIANCE.NS,2026-11-02,1300,\n"), today=d(2026, 11, 9))
        self.assertEqual(report.unknown, {"RELIANCE.NS": 1})

    def test_command(self):
        path = csv_file(HEADER + "RELIANCE.NS,2026-11-02,1300,\n")
        out = io.StringIO()
        call_command("import_prices", "--file", str(path), "--dry-run", stdout=out)
        self.assertEqual(Price.objects.count(), 0)
        call_command("import_prices", "--file", str(path), stdout=out)
        self.assertEqual(Price.objects.count(), 1)
        with self.assertRaises(CommandError):
            call_command("import_prices", "--file", str(csv_file("x\n")), stdout=out)


class PageTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.net = FakeNet()
        for target, name, value in ((http, "_urlopen", self.net),):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(http, "sleep", lambda s: None)
        p.start()
        self.addCleanup(p.stop)

    def test_update_prices_walks_the_plan_and_pauses_afterwards(self):
        self.net.add("RELIANCE.NS", fixture("yahoo_chart_reliance.json"))
        self.net.add("NSEI", fixture("yahoo_chart_reliance.json"))
        self.net.add("mfapi.in", fixture("mfapi_122639.json"))
        self.net.add("NAVAll", fixture("amfi_navall.txt"))
        url = reverse("investments_update_prices")
        data = self.client.post(url, {"step": 0}).json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["steps"], 2)
        self.assertFalse(data["done"])
        data = self.client.post(url, {"step": 1}).json()
        self.assertTrue(data["done"])
        self.assertTrue(Price.objects.filter(instrument=self.reliance).exists())
        self.assertTrue(Price.objects.filter(instrument=self.fund).exists())
        again = self.client.post(url, {"step": 0})
        self.assertEqual(again.status_code, 429)

    def test_update_prices_reports_failures_and_keeps_going(self):
        self.net.add("RELIANCE.NS", 429)
        self.net.add("NSEI", 404)
        self.net.add("mfapi.in", 404)
        self.net.add("NAVAll", 500)
        url = reverse("investments_update_prices")
        self.client.post(url, {"step": 0})
        data = self.client.post(url, {"step": 1}).json()
        self.assertTrue(data["done"])
        self.assertGreaterEqual(len(data["failures"]), 1)

    def test_single_instrument_refresh_fetches_only_it_and_skips_the_pause(self):
        self.net.add("RELIANCE.NS", fixture("yahoo_chart_reliance.json"))
        url = reverse("investments_update_prices")
        for _ in range(2):          # no one-minute pause for a single investment
            data = self.client.post(url, {"step": 0, "instrument": self.reliance.pk}).json()
            self.assertTrue(data["ok"])
            self.assertTrue(data["done"])
            self.assertEqual(data["steps"], 1)
            self.assertEqual(data["tried"], 1)
        self.assertTrue(Price.objects.filter(instrument=self.reliance).exists())
        self.assertFalse(Price.objects.filter(instrument=self.fund).exists())

    def test_single_instrument_refresh_refuses_one_that_cannot_be_fetched(self):
        url = reverse("investments_update_prices")
        self.assertEqual(self.client.post(url, {"step": 0, "instrument": "999999"}).status_code, 400)
        self.assertEqual(self.client.post(url, {"step": 0, "instrument": "abc"}).status_code, 400)

    def test_update_prices_is_for_editors_and_post_only(self):
        self.assertEqual(self.client.get(reverse("investments_update_prices")).status_code, 404)
        from accounts.models import ROLE_READER
        reader, _ = make_user("rd", ROLE_READER, profile=self.profile)
        self.client.force_login(reader)
        self.assertEqual(self.client.post(reverse("investments_update_prices"), {"step": 0}).status_code, 403)

    def test_status_line_and_button(self):
        r = self.client.get(reverse("investments_dashboard"))
        self.assertContains(r, 'id="update-prices"')
        self.assertContains(r, "No prices yet")
        Price.objects.create(instrument=self.reliance, date=d(2026, 11, 6), close=D(5), source="api")
        r = self.client.get(reverse("investments_dashboard"))
        self.assertContains(r, "prices as of close 6 Nov")

    def test_price_sources_page_is_admin_only_and_lists_runs(self):
        self.net.add("RELIANCE.NS", 500)
        self.net.add("NSEI", 404)
        fetch.fetch_prices(ids=[self.reliance.pk], rng=lambda: 0.0)
        r = self.client.get(reverse("investments_admin_prices"))
        self.assertContains(r, "Yahoo")
        self.assertContains(r, "Reliance Industries")
        editor, _ = make_user("ed9", profile=self.profile)
        self.client.force_login(editor)
        self.assertEqual(self.client.get(reverse("investments_admin_prices")).status_code, 403)
        self.assertEqual(self.client.get(reverse("investments_admin_upload")).status_code, 403)

    def test_upload_page_dry_run_then_apply(self):
        body = (HEADER + "RELIANCE.NS,2026-11-02,1300,\nZZZ,2026-11-02,1,\n").encode()
        r = self.client.post(reverse("investments_admin_upload"), {"file": SimpleUploadedFile("p.csv", body), "basis": ""})
        self.assertContains(r, "Dry run")
        self.assertContains(r, "ZZZ")
        self.assertEqual(Price.objects.count(), 0)
        token = r.context["token"]
        r = self.client.post(reverse("investments_admin_upload"), {"apply": "1", "token": token, "basis": ""})
        self.assertRedirects(r, reverse("investments_admin_prices"))
        self.assertEqual(Price.objects.count(), 1)

    def test_upload_page_rejects_other_file_types(self):
        r = self.client.post(reverse("investments_admin_upload"), {"file": SimpleUploadedFile("p.txt", b"x"), "basis": ""})
        self.assertContains(r, "Only .csv and .xlsx")


class LargeFileTests(InvTestCase):
    def test_csv_over_fifty_thousand_rows_is_read(self):
        lines = [HEADER] + [f"RELIANCE.NS,{(d(2000, 1, 1) + __import__('datetime').timedelta(days=i)):%Y-%m-%d},{100 + i % 50},\n" for i in range(55000)]
        path = csv_file("".join(lines))
        report = price_import.dry_run(path, today=d(2200, 1, 1))
        self.assertEqual(report.rows, 55000)
        self.assertEqual(report.blocking_count, 0)

    def test_web_page_refuses_a_file_over_the_cap(self):
        self.client.force_login(self.user)
        big = SimpleUploadedFile("p.csv", b"symbol,date,close\n" + b"x" * (3 * 1024 * 1024 + 1))
        r = self.client.post(reverse("investments_admin_upload"), {"file": big, "basis": ""})
        self.assertContains(r, "import_prices")
