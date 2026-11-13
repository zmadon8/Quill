"""The Admin-wide switch for the NSE and AMFI lookup (no live network: everything goes through the fake)."""
from datetime import date
from unittest import mock

from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from investments.adapters import http
from investments.models import AmfiScheme, NseSecurity
from investments.services import fetch, instrument_search
from investments.tests.base import InvTestCase, make_user
from investments.tests.fakehttp import FakeNet
from investments.tests.test_instrument_search import AMFI_TXT, NSE_CSV


class LookupToggleTests(InvTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.net = FakeNet()
        p = mock.patch.object(http, "_urlopen", self.net)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(http, "sleep", lambda s: None)
        p.start()
        self.addCleanup(p.stop)

    def requested(self, *needles):
        return [c for c in self.net.calls if any(n in str(c) for n in needles)]

    def test_default_is_on(self):
        self.assertTrue(instrument_search.lookup_enabled())

    def test_off_hides_picker_but_keeps_manual_entry(self):
        instrument_search.set_lookup_enabled(False)
        self.client.force_login(self.user)
        html = self.client.get(reverse("investments_add_2"), {"kind": "share"}).content.decode()
        self.assertNotIn("data-instrument-picker", html)
        self.assertIn('<form method="get"', html)
        instrument_search.set_lookup_enabled(True)
        html = self.client.get(reverse("investments_add_2"), {"kind": "share"}).content.decode()
        self.assertIn("data-instrument-picker", html)

    def test_off_endpoint_refuses_and_downloads_nothing(self):
        self.net.add("EQUITY_L", NSE_CSV)
        instrument_search.set_lookup_enabled(False)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("investments_add_search"), {"q": "reliance", "kind": "share"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["message"], "Lookup is switched off")
        self.assertEqual(self.net.calls, [])
        self.assertFalse(NseSecurity.objects.exists())

    def test_off_no_script_search_shows_nothing_and_reads_nothing(self):
        AmfiScheme.objects.create(code="122639", name="Parag Parikh Flexi Cap Fund", isin="INF879O01019")
        self.client.force_login(self.user)
        resp = self.client.get(reverse("investments_add_2"), {"kind": "fund", "q": "parag"})
        self.assertContains(resp, "Parag Parikh")
        instrument_search.set_lookup_enabled(False)
        for kind in ("fund", "share"):
            resp = self.client.get(reverse("investments_add_2"), {"kind": kind, "q": "parag"})
            self.assertNotContains(resp, "Parag Parikh")
            self.assertContains(resp, "Lookup is switched off")
        self.assertEqual(self.net.calls, [])

    def test_on_endpoint_still_works(self):
        self.net.add("EQUITY_L", NSE_CSV)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("investments_add_search"), {"q": "tcs", "kind": "share"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["results"][0]["code"], "TCS.NS")

    def test_off_fetch_run_requests_neither_list(self):
        instrument_search.set_lookup_enabled(False)
        self.net.add("EQUITY_L", NSE_CSV)
        self.net.add("NAVAll", AMFI_TXT)
        fetch.fetch_prices(rng=lambda: 0.0, today=date(2026, 11, 9))
        self.assertFalse(NseSecurity.objects.exists())
        self.assertFalse(AmfiScheme.objects.exists())
        self.assertEqual(self.requested("EQUITY_L"), [])

    def test_on_fetch_run_loads_the_lists(self):
        self.net.add("EQUITY_L", NSE_CSV)
        self.net.add("NAVAll", AMFI_TXT)
        fetch.fetch_prices(rng=lambda: 0.0, today=date(2026, 11, 9))
        self.assertTrue(NseSecurity.objects.exists())

    def test_admin_can_change_it_from_settings(self):
        self.client.force_login(self.user)
        self.client.post(reverse("investments_settings"), {"action": "lookup"})
        self.assertFalse(instrument_search.lookup_enabled())
        self.client.post(reverse("investments_settings"), {"action": "lookup", "lookup_enabled": "on"})
        self.assertTrue(instrument_search.lookup_enabled())

    def test_settings_page_shows_control_to_admin_only(self):
        self.client.force_login(self.user)
        self.assertIn("Search the NSE and AMFI lists", self.client.get(reverse("investments_settings")).content.decode())
        editor, _profile = make_user("ed")
        client = Client()
        client.force_login(editor)
        self.assertNotIn("Search the NSE and AMFI lists", client.get(reverse("investments_settings")).content.decode())

    def test_non_admin_cannot_change_it(self):
        editor, _profile = make_user("ed")
        client = Client()
        client.force_login(editor)
        resp = client.post(reverse("investments_settings"), {"action": "lookup"})
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(instrument_search.lookup_enabled())


class ListStatusRefreshTests(InvTestCase):
    """Settings > Investments > General: Admin list status and the Refresh lists now button."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.net = FakeNet()
        for target, value in ((http, "_urlopen"), (http, "sleep")):
            p = mock.patch.object(target, value, self.net if value == "_urlopen" else (lambda s: None))
            p.start()
            self.addCleanup(p.stop)

    def test_admin_sees_status_and_button(self):
        NseSecurity.objects.create(symbol="TCS", name="Tata Consultancy Services Limited", isin="INE467B01029", series="EQ")
        self.client.force_login(self.user)
        html = self.client.get(reverse("investments_settings")).content.decode()
        self.assertIn("Refresh lists now", html)
        self.assertIn('data-table-id="inv-settings_general-lists"', html)
        self.assertIn("Never", html)   # the AMFI list is empty

    def test_non_admin_sees_no_button_and_cannot_post(self):
        user, profile = make_user("plain")
        self.client.force_login(user)
        html = self.client.get(reverse("investments_settings")).content.decode()
        self.assertNotIn("Refresh lists now", html)
        resp = self.client.post(reverse("investments_settings"), {"action": "refresh_lists"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self.net.calls, [])

    def test_refresh_clears_throttle_and_loads_both_lists(self):
        cache.set("instrument_search:refresh_failed:NSE", True, 900)
        cache.set("instrument_search:refresh_failed:AMFI", True, 900)
        self.net.add("EQUITY_L", NSE_CSV)
        self.net.add("NAVAll", AMFI_TXT)
        self.client.force_login(self.user)
        resp = self.client.post(reverse("investments_settings"), {"action": "refresh_lists"}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(cache.get("instrument_search:refresh_failed:NSE"))
        self.assertIsNone(cache.get("instrument_search:refresh_failed:AMFI"))
        self.assertTrue(NseSecurity.objects.exists())
        self.assertTrue(AmfiScheme.objects.exists())
        self.assertContains(resp, "list is refreshed")

    def test_refresh_failure_is_shown_as_last_error(self):
        self.client.force_login(self.user)
        resp = self.client.post(reverse("investments_settings"), {"action": "refresh_lists"}, follow=True)
        self.assertContains(resp, "could not be refreshed")
        self.assertTrue(all(s["error"] for s in instrument_search.status()))

    def test_refresh_does_nothing_while_lookup_is_off(self):
        instrument_search.set_lookup_enabled(False)
        self.client.force_login(self.user)
        self.client.post(reverse("investments_settings"), {"action": "refresh_lists"})
        self.assertEqual(self.net.calls, [])
