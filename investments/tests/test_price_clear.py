"""Clear the price history of one shared investment (owner round 2026-11)."""
from datetime import date as d
from decimal import Decimal as D
from unittest import mock

from django.urls import reverse

from accounts.models import ROLE_READER
from investments.errors import InvestmentsError
from investments.models import CatalogueHistory, Instrument, ManualPrice, PinnedPrice, Price
from investments.services import catalogue, masters
from investments.tests.base import InvTestCase, make_user


class ClearPriceHistoryTests(InvTestCase):
    def setUp(self):
        super().setUp()
        for day in (d(2024, 1, 1), d(2024, 1, 2), d(2024, 1, 3)):
            Price.objects.create(instrument=self.reliance, date=day, close=D(100), source="api", basis="split_adjusted")
        Price.objects.create(instrument=self.reliance, date=d(2024, 1, 4), close=D(101), source="helper", basis="split_adjusted")
        Price.objects.create(instrument=self.reliance, date=d(2024, 1, 5), close=D(102), source="upload", basis="split_adjusted")
        ManualPrice.objects.create(instrument=self.reliance, date=d(2024, 1, 8), close=D(99))
        PinnedPrice.objects.create(instrument=self.reliance, asked_date=d(2024, 3, 31), trading_date=d(2024, 3, 28), close=D(105),
                                   reason="year_end")
        Price.objects.create(instrument=self.fund, date=d(2024, 1, 1), close=D(50), source="api")
        self.url = reverse("investments_price_action", args=[self.reliance.pk])
        self.client.force_login(self.user)

    def test_preview_counts_and_changes_nothing(self):
        preview = catalogue.clear_preview(self.reliance)
        self.assertEqual((preview["fetched"], preview["uploaded"], preview["manual"], preview["pinned"], preview["problem"]), (4, 1, 1, 1, ""))
        response = self.client.post(self.url, {"action": "clear_prices"})
        self.assertContains(response, "Clear the price history of Reliance Industries")
        self.assertContains(response, 'name="include_uploaded"')
        self.assertContains(response, 'name="include_manual"')
        self.assertEqual(Price.objects.filter(instrument=self.reliance).count(), 5)

    def test_confirm_removes_fetched_prices_only_by_default(self):
        response = self.client.post(self.url, {"action": "clear_prices", "confirm": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Price.objects.filter(instrument=self.reliance, source__in=["api", "helper"]).exists())
        self.assertTrue(Price.objects.filter(instrument=self.reliance, source="upload").exists())
        self.assertTrue(ManualPrice.objects.filter(instrument=self.reliance).exists())
        self.assertTrue(PinnedPrice.objects.filter(instrument=self.reliance).exists())
        self.assertTrue(Price.objects.filter(instrument=self.fund).exists())      # other investments are untouched
        entry = CatalogueHistory.objects.get(record_type="prices_cleared")
        self.assertEqual((entry.field, entry.old), ("fetched", "4 rows"))

    def test_uploaded_and_hand_entered_prices_go_when_chosen_after_a_backup(self):
        with mock.patch.object(catalogue, "_backup") as backup:
            self.client.post(self.url, {"action": "clear_prices", "confirm": "1", "include_uploaded": "1", "include_manual": "1"})
        backup.assert_called_once()
        self.assertFalse(Price.objects.filter(instrument=self.reliance).exists())
        self.assertFalse(ManualPrice.objects.filter(instrument=self.reliance).exists())
        self.assertTrue(PinnedPrice.objects.filter(instrument=self.reliance).exists())

    def test_no_backup_when_hand_entered_prices_are_kept(self):
        with mock.patch.object(catalogue, "_backup") as backup:
            catalogue.clear_price_history(self.user, self.reliance, include_uploaded=True)
        backup.assert_not_called()

    def test_an_index_is_never_cleared(self):
        masters.ensure_builtin_indices()
        nifty = Instrument.objects.get(code="^NSEI", profile=None)
        self.assertTrue(catalogue.clear_preview(nifty)["problem"])
        with self.assertRaises(InvestmentsError):
            catalogue.clear_price_history(self.user, nifty)

    def test_a_reader_cannot_clear(self):
        reader, _ = make_user("reader-clear", role=ROLE_READER, profile=self.profile)
        self.client.force_login(reader)
        response = self.client.post(self.url, {"action": "clear_prices", "confirm": "1"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Price.objects.filter(instrument=self.reliance).count(), 5)

    def test_the_investment_page_offers_the_button(self):
        self.buy(d(2024, 1, 1), 10, 100)
        page = self.client.get(reverse("investments_investment", args=[self.reliance.pk])).content.decode()
        self.assertIn('name="action" value="clear_prices"', page)
        self.assertIn("Clear price history", page)
