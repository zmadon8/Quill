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
