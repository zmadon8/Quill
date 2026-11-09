"""The optional local helper (plan 28.5) and the bhavcopy tool."""
import io
import json
import subprocess
import sys
import tempfile
from datetime import date as d
from decimal import Decimal as D
from pathlib import Path

from django.test import override_settings
from django.urls import reverse

from investments.models import ManualPrice, Price
from investments.services import fetch, helper
from investments.tests.base import InvTestCase

ROOT = Path(__file__).resolve().parents[2]


class HelperOffTests(InvTestCase):
    @override_settings(PRICE_HELPER_ENABLED=False)
    def test_endpoints_are_404_and_the_page_says_off(self):
        self.assertEqual(self.client.get(reverse("investments_helper_wanted")).status_code, 404)
        self.assertEqual(self.client.post(reverse("investments_helper_ingest"), "{}", content_type="application/json").status_code, 404)
        self.client.force_login(self.user)
        r = self.client.get(reverse("investments_admin_prices"))
        self.assertContains(r, "Local helper: <b>off</b>")
        self.assertNotContains(r, "Make a token")


@override_settings(PRICE_HELPER_ENABLED=True, DEBUG=True)
class HelperOnTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.row, self.token = helper.create_token(self.user, "Mac")
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}

    def post(self, rows, **extra):
        return self.client.post(reverse("investments_helper_ingest"), json.dumps({"rows": rows}), content_type="application/json", **{**self.auth, **extra})

    def test_wanted_lists_helper_sources_and_either_only_when_stale(self):
        self.assertEqual(self.client.get(reverse("investments_helper_wanted"), **self.auth).json()["wanted"], [])     # server mode: nothing
        helper.set_mode("yahoo", "helper")
        symbols = {w["symbol"] for w in self.client.get(reverse("investments_helper_wanted"), **self.auth).json()["wanted"]}
        self.assertIn("RELIANCE.NS", symbols)
        helper.set_mode("yahoo", "either")
        Price.objects.create(instrument=self.reliance, date=d.today(), close=D(1), source="api", basis="split_adjusted")
        symbols = {w["symbol"] for w in self.client.get(reverse("investments_helper_wanted"), **self.auth).json()["wanted"]}
        self.assertNotIn("RELIANCE.NS", symbols)
        self.assertNotIn(self.reliance, [i for i in fetch.tracked_instruments() if helper.server_skips(i.price_source)])

    def test_upload_fills_a_stale_symbol_and_bumps_the_version(self):
        r = self.post([{"source": "helper", "symbol_or_code": "RELIANCE.NS", "date": "2026-11-06", "close": "1327.8", "basis": "split_adjusted"}])
        self.assertEqual(r.json()["written"], 1)
        self.assertEqual(Price.objects.get().source, "helper")
        self.assertEqual(fetch.price_version(), 1)

    def test_rejected_for_a_wrong_basis_and_unknown_symbols_listed(self):
        r = self.post([{"symbol_or_code": "RELIANCE.NS", "date": "2026-11-06", "close": "10", "basis": "raw"}, {"symbol_or_code": "NOPE", "date": "2026-11-06", "close": "1"}])
        body = r.json()
        self.assertEqual((body["written"], body["unknown"], len(body["rejected"])), (0, ["NOPE"], 1))
        self.assertFalse(Price.objects.exists())

    def test_never_overwrites_manual_or_upload_rows(self):
        ManualPrice.objects.create(instrument=self.reliance, date=d(2026, 11, 5), close=D(5))
        Price.objects.create(instrument=self.reliance, date=d(2026, 11, 6), close=D(7), source="upload", basis="split_adjusted")
        self.post([{"symbol_or_code": "RELIANCE.NS", "date": "2026-11-05", "close": "100"}, {"symbol_or_code": "RELIANCE.NS", "date": "2026-11-06", "close": "100"}])
        self.assertEqual(ManualPrice.objects.get().close, D(5))
        self.assertEqual(Price.objects.get(date=d(2026, 11, 6)).close, D(7))
        self.assertEqual(Price.objects.get(date=d(2026, 11, 5)).close, D(100))                          # stored, but the hand-entered price wins
        from investments.services import prices
        self.assertEqual(prices.latest_prices([self.reliance.pk], d(2026, 11, 5))[self.reliance.pk][1], D(5))

    def test_revoked_or_missing_token_is_refused_and_csv_works(self):
        self.assertEqual(self.client.get(reverse("investments_helper_wanted")).status_code, 401)
        helper.revoke(self.row.pk)
        self.assertEqual(self.client.get(reverse("investments_helper_wanted"), **self.auth).status_code, 401)
        _row, token = helper.create_token(self.user, "Second")
        r = self.client.post(reverse("investments_helper_ingest"), "symbol_or_code,date,close\nRELIANCE.NS,2026-11-06,10\n", content_type="text/csv",
                             HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.json()["written"], 1)

    def test_limits(self):
        r = self.post([{"symbol_or_code": "X", "date": "2026-01-01", "close": "1"}] * 5001)
        self.assertEqual(r.status_code, 413)

    def test_admin_page_tokens_and_modes(self):
        self.client.force_login(self.user)
        r = self.client.post(reverse("investments_admin_prices"), {"action": "token", "label": "Office"})
        self.assertContains(r, "shown only now")
        self.client.post(reverse("investments_admin_prices"), {"action": "mode", "source": "amfi", "mode": "either"})
        self.assertEqual(helper.mode("amfi"), "either")


class ToolTests(InvTestCase):
    def test_bhavcopy_both_layouts(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "old.csv").write_text("SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP\nRELIANCE,EQ,1,1,1,2500.5,1,1,1,1,05-JUL-2024\nRELIANCE,BE,1,1,1,9,1,1,1,1,05-JUL-2024\nTCS,EQ,1,1,1,3900,1,1,1,1,05-JUL-2024\n")
        (tmp / "new.csv").write_text("TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric\n2024-07-08,2024-07-08,CM,NSE,STK,2885,INE002A01018,RELIANCE,EQ,,,,,RELIANCE IND,1,1,1,2510.25\n")
        out = tmp / "out.csv"
        result = subprocess.run([sys.executable, str(ROOT / "tools" / "bhavcopy_to_csv.py"), "--symbols", "RELIANCE", "--out", str(out), str(tmp / "old.csv"), str(tmp / "new.csv")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(out.read_text().splitlines(), ["symbol,date,close,basis", "RELIANCE.NS,2024-07-05,2500.50,raw", "RELIANCE.NS,2024-07-08,2510.25,raw"])

    def test_helper_script_compiles_and_shows_help(self):
        result = subprocess.run([sys.executable, str(ROOT / "tools" / "price_helper.py"), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("--config", result.stdout)
        self.assertIsNotNone(io)
