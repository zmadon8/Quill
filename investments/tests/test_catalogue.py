"""The Admin catalogue: what an Admin can do, and what is never shown (plan 21.1)."""
from datetime import date as d
from decimal import Decimal as D
from django.urls import reverse
from unittest import mock


from investments.adapters import http
from investments.errors import InvestmentsError
from investments.models import (
    CatalogueHistory, Folio, Instrument, ManualPrice, PinnedPrice, Price, ProfileInvestment,
)
from investments.services import catalogue, fetch, masters, prices, transactions as tx
from investments.tests.base import InvTestCase, make_user
from investments.tests.fakehttp import FakeNet, fixture


class CatalogueServiceTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.other_user, self.other = make_user("holder2")       # a second profile that holds the share, with a different Admin-less user
        self.other_portfolio = __import__("investments.models", fromlist=["Portfolio"]).Portfolio.objects.create(profile=self.other, name="P")
        self.other_broker = __import__("investments.models", fromlist=["Broker"]).Broker.objects.create(profile=self.other, name="B")
        tx.add_transaction(self.other, self.other_user, side="buy", instrument=self.reliance, portfolio=self.other_portfolio,
                           broker=self.other_broker, date=d(2024, 1, 1), units=D(7), price=D(100))
        self.admin_without_holdings, _ = make_user("lonely_admin", admin=True)

    def test_an_admin_who_holds_nothing_can_find_and_fix_prices_of_another_profiles_investment(self):
        admin = self.admin_without_holdings
        found = catalogue.listing(q="reliance")
        self.assertEqual([i.name for i in found], ["Reliance Industries"])
        Price.objects.create(instrument=self.reliance, date=d(2026, 11, 5), close=D(1), source="api", basis="split_adjusted")
        catalogue.set_price(admin, self.reliance, d(2026, 11, 5), "1320.5", "typo in the feed")
        self.assertEqual(prices.latest_prices([self.reliance.pk], d(2026, 11, 9))[self.reliance.pk], (d(2026, 11, 5), D("1320.5")))
        entry = CatalogueHistory.objects.get(record_type="price")
        self.assertEqual((entry.old, entry.new, entry.reason, entry.by), ("1.0000", "1320.5000", "typo in the feed", admin))

    def test_only_admins(self):
        editor, _ = make_user("ed7", profile=self.profile)
        for call in (lambda: catalogue.set_price(editor, self.reliance, d(2026, 1, 1), 5),
                     lambda: catalogue.update_details(editor, self.reliance, name="x"),
                     lambda: catalogue.merge(editor, self.reliance, self.fund),
                     lambda: catalogue.delete_instrument(editor, self.reliance),
                     lambda: catalogue.change_basis(editor, self.reliance, "raw")):
            with self.assertRaises(InvestmentsError) as cm:
                call()
            self.assertEqual(cm.exception.code, "FORBIDDEN")

    def test_edited_price_survives_the_next_nightly_fetch(self):
        net = FakeNet()
        net.add("RELIANCE.NS", fixture("yahoo_chart_reliance.json"))
        with mock.patch.object(http, "_urlopen", net), mock.patch.object(http, "sleep", lambda s: None):
            fetch.fetch_prices(ids=[self.reliance.pk], today=d(2026, 11, 9), rng=lambda: 0.0)
            catalogue.set_price(self.user, self.reliance, d(2026, 11, 5), "9999")
            fetch.fetch_prices(ids=[self.reliance.pk], today=d(2026, 11, 9), rng=lambda: 0.0)
        self.assertEqual(prices.latest_prices([self.reliance.pk], d(2026, 11, 5))[self.reliance.pk][1], D("9999"))
        self.assertEqual(Price.objects.get(instrument=self.reliance, date=d(2026, 11, 5)).close, D("1320.0000"))

    def test_deleted_price_is_logged_and_can_be_put_back(self):
        Price.objects.create(instrument=self.reliance, date=d(2026, 11, 5), close=D(1320), source="api")
        catalogue.delete_price(self.user, self.reliance, d(2026, 11, 5), "bad tick")
        self.assertFalse(prices.series(self.reliance))
        row = CatalogueHistory.objects.get(record_type="price_deleted")
        catalogue.restore_price(self.user, row.pk)
        self.assertEqual(prices.series(self.reliance), [(d(2026, 11, 5), D("1320"))])

    def test_editing_a_pinned_date_updates_the_pin(self):
        PinnedPrice.objects.create(instrument=self.reliance, asked_date=d(2026, 3, 31), trading_date=d(2026, 3, 30), close=D(5), reason="year_end")
        self.assertEqual(catalogue.set_price(self.user, self.reliance, d(2026, 3, 30), 77), 1)
        self.assertEqual(PinnedPrice.objects.get().close, D(77))

    def test_holders_are_names_only(self):
        names = catalogue.holder_profiles(self.reliance)
        self.assertEqual(sorted(names), sorted([self.profile.name, self.other.name]) if ProfileInvestment.objects.filter(profile=self.profile, instrument=self.reliance).exists() else [self.other.name])
        self.assertTrue(all(isinstance(n, str) for n in names))

    def test_shared_detail_changes_are_logged_and_counted(self):
        self.assertEqual(catalogue.affected_profiles(self.reliance), 2)
        self.assertEqual(catalogue.update_details(self.user, self.reliance, "rename", name="Reliance Industries Ltd", sector="Energy"), 2)
        self.assertEqual(CatalogueHistory.objects.filter(record_type="instrument").count(), 2)
        self.assertEqual(catalogue.update_details(self.user, self.reliance, "same", name="Reliance Industries Ltd"), 0)

    def test_merge_moves_everything_and_keeps_the_kept_prices(self):
        dup = masters.create_instrument(self.profile, self.user, kind="share", name="Reliance Ind. Ltd", code="RELIANCE.BO", allow_duplicate=True)
        folio = masters.add_folio(self.profile, self.user, instrument=dup, portfolio=self.portfolio, number="F1")
        t = self.buy(d(2024, 1, 1), 5, 10, instrument=dup, folio=folio)
        Price.objects.create(instrument=self.reliance, date=d(2026, 11, 5), close=D(100), source="api")
        Price.objects.create(instrument=dup, date=d(2026, 11, 5), close=D(999), source="api")
        Price.objects.create(instrument=dup, date=d(2026, 11, 6), close=D(101), source="api")
        preview = catalogue.merge_preview(self.reliance, dup)
        self.assertEqual(preview["problems"], [])
        self.assertEqual(preview["per_profile"], {self.profile.name: 1})
        self.assertEqual(preview["prices_moved"], 1)
        catalogue.merge(self.user, self.reliance, dup, "same company")
        t.refresh_from_db()
        self.assertEqual(t.instrument_id, self.reliance.pk)
        self.assertEqual(Folio.objects.get().instrument_id, self.reliance.pk)
        self.assertFalse(Instrument.objects.filter(pk=dup.pk).exists())
        self.assertEqual(Price.objects.get(instrument=self.reliance, date=d(2026, 11, 5)).close, D(100))
        self.assertEqual(Price.objects.filter(instrument=self.reliance).count(), 2)
        from backups.models import BackupFile
        self.assertTrue(BackupFile.objects.filter(kind="pre_catalogue").exists())

    def test_merge_refusals(self):
        with self.assertRaises(InvestmentsError):
            catalogue.merge(self.user, self.reliance, self.fund)                     # different type
        with self.assertRaises(InvestmentsError):
            catalogue.merge(self.user, self.reliance, self.reliance)
        private = masters.create_instrument(self.profile, self.user, kind="alternative", name="PPF")
        self.assertTrue(catalogue.merge_preview(self.reliance, private)["problems"])

    def test_change_basis_drops_fetched_keeps_uploads_and_takes_a_backup(self):
        Price.objects.create(instrument=self.reliance, date=d(2026, 11, 5), close=D(1), source="api", basis="split_adjusted")
        Price.objects.create(instrument=self.reliance, date=d(2026, 11, 6), close=D(2), source="upload", basis="split_adjusted")
        self.assertEqual(catalogue.basis_preview(self.reliance), {"fetched": 1, "uploaded": 1})
        net = FakeNet()
        net.add("chart", 500)
        with mock.patch.object(http, "_urlopen", net), mock.patch.object(http, "sleep", lambda s: None):
            result = catalogue.change_basis(self.user, self.reliance, "raw", "bhavcopy")
        self.reliance.refresh_from_db()
        self.assertEqual(self.reliance.price_basis, "raw")
        self.assertEqual(result["uploaded"], 1)
        self.assertEqual(list(Price.objects.values_list("source", "basis")), [("upload", "raw")])

    def test_delete_is_refused_while_a_profile_holds_records(self):
        with self.assertRaises(InvestmentsError) as cm:
            catalogue.delete_instrument(self.user, self.reliance)
        self.assertEqual(cm.exception.code, "IN_USE")
        empty = catalogue.create_instrument(self.user, kind="share", name="Unused Co", code="UNUSED.NS")
        catalogue.delete_instrument(self.user, empty, "added by mistake")
        self.assertFalse(Instrument.objects.filter(pk=empty.pk).exists())
        self.assertTrue(CatalogueHistory.objects.filter(record_type="instrument_deleted").exists())

    def test_listing_flags(self):
        dup = masters.create_instrument(self.profile, self.user, kind="share", name="Another", code="RELIANCE.NS", allow_duplicate=True)
        Price.objects.create(instrument=self.reliance, date=d(2020, 1, 1), close=D(1), source="api")
        flags = {i.name: i.flags for i in catalogue.listing(today=d(2026, 11, 9))}
        self.assertIn("duplicate", flags["Reliance Industries"])
        self.assertIn("stale", flags["Reliance Industries"])
        self.assertEqual([i.name for i in catalogue.listing(flag="duplicate")].count("Another"), 1)
        self.assertEqual(dup.profile_id, None)

    def test_price_rows_page_flags_a_move_that_recovers(self):
        for n, close in enumerate([100, 101, 30, 102, 103]):
            Price.objects.create(instrument=self.reliance, date=d(2026, 10, 1 + n), close=D(close), source="api")
        rows, page, pages, total = catalogue.price_rows(self.reliance)
        self.assertEqual((page, pages, total), (1, 1, 5))
        self.assertEqual([r["date"] for r in rows if r["odd"]], [d(2026, 10, 3)])

    def test_the_log_cannot_be_edited_through_any_service(self):
        catalogue.set_price(self.user, self.reliance, d(2026, 1, 2), 5)
        first = CatalogueHistory.objects.get()
        catalogue.set_price(self.user, self.reliance, d(2026, 1, 2), 6)
        self.assertEqual(CatalogueHistory.objects.count(), 2)
        first.refresh_from_db()
        self.assertEqual(first.new, "5.0000")


class CataloguePageTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_pages_never_show_units_costs_dates_folios_notes_or_transactions(self):
        folio = masters.add_folio(self.profile, self.user, instrument=self.reliance, portfolio=self.portfolio, number="SECRET-FOLIO-77")
        self.buy(d(2024, 1, 1), "123.4567", "2468.13", folio=folio, note="private note about divorce")
        masters.update_profile_details(self.profile, self.user, self.reliance, notes="my secret note about the tax audit",
                                       links=[{"label": "Annual report", "url": "https://example.test/ar"}])
        Price.objects.create(instrument=self.reliance, date=d(2026, 11, 5), close=D("1320"), source="api")
        pages = [self.client.get(reverse("investments_admin_catalogue")), self.client.get(reverse("investments_admin_catalogue_item", args=[self.reliance.pk])),
                 self.client.get(reverse("investments_admin_catalogue") + "?q=reliance")]
        for r in pages:
            self.assertEqual(r.status_code, 200)
            body = r.content.decode()
            for secret in ("123.4567", "2468.13", "SECRET-FOLIO-77", "private note", "secret note", "tax audit", "1 Jan 2024", "Jan 1, 2024", "2024-01-01"):
                self.assertNotIn(secret, body)
        self.assertContains(pages[1], self.profile.name)            # the holder is named

    def test_editor_gets_403_on_every_catalogue_url(self):
        editor, _ = make_user("ed11", profile=self.profile)
        self.client.force_login(editor)
        for name, args in (("investments_admin_catalogue", []), ("investments_admin_catalogue_item", [self.reliance.pk]),
                           ("investments_admin_catalogue_action", [self.reliance.pk]), ("investments_admin_catalogue_new", [])):
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 403, name)
            self.assertEqual(self.client.post(reverse(name, args=args), {"action": "price"}).status_code, 403, name)

    def test_item_page_actions(self):
        url = reverse("investments_admin_catalogue_action", args=[self.reliance.pk])
        self.client.post(url, {"action": "price", "date": "2026-11-05", "close": "1,320.5", "reason": "fix"})
        self.assertEqual(ManualPrice.objects.get().close, D("1320.5"))
        self.client.post(url, {"action": "delete_price", "date": "2026-11-05", "reason": "oops"})
        self.assertFalse(ManualPrice.objects.exists())
        r = self.client.post(url, {"action": "merge", "other": self.fund.pk})
        self.assertContains(r, "different types")
        r = self.client.post(url, {"action": "basis", "new_basis": "raw"})
        self.assertContains(r, "re-uploading")
        self.reliance.refresh_from_db()
        self.assertEqual(self.reliance.price_basis, "split_adjusted")           # a preview changes nothing
        self.client.post(url, {"action": "details", "name": "Reliance Industries", "code": "RELIANCE.NS", "currency": "inr", "asset_class": "equity",
                               "price_source": "yahoo", "fetch_enabled": "on", "sector": "Energy", "isin": "", "exchange": "", "fallback_source": ""})
        self.reliance.refresh_from_db()
        self.assertEqual((self.reliance.sector, self.reliance.currency), ("Energy", "INR"))

    def test_new_investment_and_symbol(self):
        self.client.post(reverse("investments_admin_catalogue_new"), {"kind": "share", "name": "TCS", "code": "TCS.NS", "currency": "INR"})
        tcs = Instrument.objects.get(name="TCS")
        self.assertEqual(tcs.price_basis, "split_adjusted")
        self.client.post(reverse("investments_admin_catalogue_action", args=[tcs.pk]), {"action": "symbol", "source": "yahoo", "symbol": "TCS.BO"})
        self.assertEqual(fetch.symbol_for(tcs, "yahoo"), "TCS.BO")

    def test_export_needs_openpyxl(self):
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            self.skipTest("openpyxl is not installed in this environment; CI runs it")
        r = self.client.get(reverse("investments_admin_catalogue") + "?export=xlsx")
        self.assertEqual(r.status_code, 200)
        self.assertIn("spreadsheetml", r["Content-Type"])
