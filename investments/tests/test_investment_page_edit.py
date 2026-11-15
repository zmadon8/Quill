"""Editing and deleting a transaction from the investment page, with a validated way back (docs/DESIGN.md D183), and the Manual Price
History heading and tags on that page."""
from urllib.parse import quote

from django.urls import reverse

from accounts.models import ROLE_READER
from investments.models import ManualPrice, Transaction
from investments.services import masters
from investments.tests.base import InvTestCase, d, make_user


class InvestmentPageEditTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.buy_txn = self.buy(d(2024, 1, 1), 10, 100)
        self.page = reverse("investments_investment", args=[self.reliance.pk])
        self.edit = reverse("investments_txn_edit", args=[self.buy_txn.pk])

    def form(self, **over):
        data = {"date": "2024-01-01", "instrument": self.reliance.pk, "portfolio": self.portfolio.pk, "broker": self.zerodha.pk,
                "units": "10", "price": "105", "charges": "0", "version": self.buy_txn.version}
        data.update(over)
        return data

    def test_editor_sees_an_edit_link_that_returns_to_the_investment_page(self):
        html = self.client.get(self.page).content.decode()
        self.assertIn(f'href="{self.edit}?next={quote(self.page, safe="")}"', html)

    def test_the_edit_link_keeps_the_filters_of_the_page(self):
        html = self.client.get(self.page + "?on=2024-06-30").content.decode()
        self.assertIn(f'href="{self.edit}?next={quote(self.page + "?on=2024-06-30", safe="")}"', html)

    def test_reader_sees_no_edit_link_and_cannot_open_the_edit_page(self):
        reader, _ = make_user("reader", ROLE_READER, profile=self.profile)
        self.client.force_login(reader)
        self.assertNotContains(self.client.get(self.page), self.edit)
        self.assertEqual(self.client.get(self.edit).status_code, 403)
        self.assertEqual(self.client.post(f"{self.edit}?next={self.page}", self.form()).status_code, 403)

    def test_saving_with_a_safe_next_returns_to_the_investment_page(self):
        r = self.client.post(f"{self.edit}?next={quote(self.page, safe='')}", self.form())
        self.assertRedirects(r, self.page)
        self.assertEqual(Transaction.objects.get(pk=self.buy_txn.pk).price, 105)

    def test_the_edit_page_carries_next_into_cancel_and_delete(self):
        html = self.client.get(f"{self.edit}?next={quote(self.page, safe='')}").content.decode()
        self.assertIn(f'href="{self.page}">Cancel', html)
        self.assertIn(f'action="{reverse("investments_txn_delete", args=[self.buy_txn.pk])}?next={quote(self.page, safe="")}"', html)

    def test_an_unsafe_next_falls_back_to_the_transactions_list(self):
        for bad in ("https://evil.example/", "//evil.example", "/\\evil.example", "javascript:alert(1)"):
            txn = Transaction.objects.get(pk=self.buy_txn.pk)
            r = self.client.post(f"{self.edit}?next={quote(bad, safe='')}", self.form(version=txn.version))
            self.assertRedirects(r, reverse("investments_transactions"), msg_prefix=bad)

    def test_deleting_with_next_returns_to_the_investment_page(self):
        r = self.client.post(reverse("investments_txn_delete", args=[self.buy_txn.pk]), {}, QUERY_STRING=f"next={quote(self.page, safe='')}")
        self.assertRedirects(r, self.page)
        self.assertFalse(Transaction.objects.filter(pk=self.buy_txn.pk).exists())

    def test_deleting_with_an_unsafe_next_goes_to_the_transactions_list(self):
        r = self.client.post(reverse("investments_txn_delete", args=[self.buy_txn.pk]), {}, QUERY_STRING="next=//evil.example")
        self.assertRedirects(r, reverse("investments_transactions"))

    def test_a_refused_edit_still_shows_the_refusal_and_links_back_to_the_edit_page(self):
        self.sell(d(2024, 2, 1), 10, 120)
        target = f"{self.edit}?next={quote(self.page, safe='')}"
        r = self.client.post(target, self.form(units="6"))
        self.assertEqual(r.status_code, 409)
        self.assertContains(r, "This change is refused", status_code=409)
        self.assertContains(r, f'href="{target}">Back', status_code=409)

    def test_a_refused_delete_links_back_to_the_edit_page(self):
        self.sell(d(2024, 2, 1), 10, 120)
        r = self.client.post(reverse("investments_txn_delete", args=[self.buy_txn.pk]), {}, QUERY_STRING=f"next={quote(self.page, safe='')}")
        self.assertEqual(r.status_code, 409)
        self.assertContains(r, f'href="{self.edit}?next={quote(self.page, safe="")}">Back', status_code=409)


class ManualPriceHistoryPageTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_a_manual_priced_investment_shows_the_heading_and_the_tag_after_a_buy(self):
        masters.update_shared_details(self.profile, self.user, self.reliance, price_source="manual")
        self.reliance.refresh_from_db()
        self.buy(d(2024, 1, 5), 10, 101)
        self.assertTrue(ManualPrice.objects.filter(instrument=self.reliance, date=d(2024, 1, 5)).exists())
        r = self.client.get(reverse("investments_investment", args=[self.reliance.pk]))
        self.assertContains(r, "Manual Price History")
        self.assertContains(r, '<span class="tag">From purchase</span>')
        self.assertContains(r, "kept and wins")

    def test_a_private_manual_investment_shows_the_heading_and_the_tag(self):
        own = masters.create_instrument(self.profile, self.user, kind="share", name="Unlisted Co", asset_class="equity")
        masters.update_shared_details(self.profile, self.user, own, price_source="manual")
        own.refresh_from_db()
        self.buy(d(2024, 1, 5), 4, 250, instrument=own)
        r = self.client.get(reverse("investments_investment", args=[own.pk]))
        self.assertContains(r, "Manual Price History")
        self.assertContains(r, '<span class="tag">From purchase</span>')

    def test_an_alternative_shows_the_heading_and_the_tag_after_a_buy(self):
        gold = masters.create_instrument(self.profile, self.user, kind="alternative", name="Gold coins", asset_class="gold")
        self.buy(d(2024, 1, 5), 5, 6000, instrument=gold)
        r = self.client.get(reverse("investments_investment", args=[gold.pk]))
        self.assertContains(r, "Manual Price History")
        self.assertContains(r, '<span class="tag">From purchase</span>')
        for name in ("investments_dashboard", "investments_holdings"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
