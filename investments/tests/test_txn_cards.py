"""Buy and sell pages: every added transaction is a full card; sales are checked cumulatively; the units-available endpoint."""
from datetime import date as d
from decimal import Decimal as D

from django.urls import reverse

from investments.models import Transaction
from investments.services import masters
from investments.tests.base import InvTestCase


class TxnCardTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def card(self, prefix, day, units, price, instrument=None, broker=None, **extra):
        p = prefix + "-" if prefix else ""
        return {p + "date": day, p + "instrument": (instrument or self.reliance).pk, p + "portfolio": self.portfolio.pk,
                p + "broker": (broker or self.zerodha).pk, p + "units": units, p + "price": price, p + "charges": "0",
                **{p + k: v for k, v in extra.items()}}

    def test_buy_page_cards_have_the_full_field_set(self):
        html = self.client.get(reverse("investments_txn_new_buy")).content.decode()
        template = html[html.index('<template id="extra-row-template">'):html.index("</template>")]
        for name in ("date", "instrument", "portfolio", "broker", "units", "price", "allotment_date", "charges", "folio", "new_folio",
                     "origin", "corporate_action", "note"):
            self.assertIn(f'name="x__i__-{name}"', template)
        self.assertIn('class="txn-card txn-row"', template)
        self.assertIn('class="held-only-box" data-for="x__i__-instrument"', template)

    def test_sell_page_cards_show_units_available(self):
        html = self.client.get(reverse("investments_txn_new_sell")).content.decode()
        self.assertEqual(html.count("Units available to sell:"), 2)      # the first card and the template
        self.assertNotIn('id="available-text"', html)
        self.assertNotIn("Units available to sell:", self.client.get(reverse("investments_txn_new_buy")).content.decode())

    def test_buy_with_two_full_cards_saves_both(self):
        post = {**self.card("", "2024-01-01", "10", "100"), "extra_rows": "1",
                **self.card("x1", "2024-02-01", "5", "50", instrument=self.fund, broker=self.groww, note="second")}
        self.assertRedirects(self.client.post(reverse("investments_txn_new_buy"), post), reverse("investments_transactions"))
        self.assertEqual(Transaction.objects.count(), 2)
        second = Transaction.objects.get(instrument=self.fund)
        self.assertEqual((second.date, second.broker_id, second.note), (d(2024, 2, 1), self.groww.pk, "second"))

    def test_a_bad_card_saves_nothing(self):
        post = {**self.card("", "2024-01-01", "10", "100"), "extra_rows": "1", **self.card("x1", "2024-02-01", "", "50")}
        r = self.client.post(reverse("investments_txn_new_buy"), post)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertContains(r, 'name="x1-units"')

    def test_folio_sale_in_an_extra_card_is_allowed(self):
        folio = masters.add_folio(self.profile, self.user, instrument=self.reliance, portfolio=self.portfolio, number="F1")
        self.buy(d(2024, 1, 1), 20, 100, folio=folio)
        post = {**self.card("", "2024-03-01", "5", "120", folio=folio.pk), "extra_rows": "1",
                **self.card("x1", "2024-03-02", "5", "120", folio=folio.pk)}
        self.assertRedirects(self.client.post(reverse("investments_txn_new_sell"), post), reverse("investments_transactions"))
        self.assertEqual(Transaction.objects.filter(side="sell").count(), 2)

    def test_sales_on_one_holding_are_checked_cumulatively(self):
        self.buy(d(2024, 1, 1), 10, 100)
        post = {**self.card("", "2024-03-01", "6", "120"), "extra_rows": "1", **self.card("x1", "2024-03-02", "6", "120")}
        r = self.client.post(reverse("investments_txn_new_sell"), post)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(Transaction.objects.filter(side="sell").count(), 0)

    def test_sales_are_saved_in_date_order(self):
        self.buy(d(2024, 1, 1), 10, 100)
        self.sell(d(2024, 5, 1), 4, 100)
        # The second card has the earlier date: cards are saved by date, each checked against what is held then and after.
        post = {**self.card("", "2024-03-02", "3", "120"), "extra_rows": "1", **self.card("x1", "2024-03-01", "3", "120")}
        self.assertRedirects(self.client.post(reverse("investments_txn_new_sell"), post), reverse("investments_transactions"))
        self.assertEqual(Transaction.objects.filter(side="sell").count(), 3)

    def test_demerger_prefill_is_still_on_the_first_card(self):
        html = self.client.get(reverse("investments_txn_new_buy") + f"?instrument={self.fund.pk}").content.decode()
        self.assertIn(f'<option value="{self.fund.pk}" selected>', html)

    def test_availability_for_one_place_as_at_the_date(self):
        self.buy(d(2024, 1, 1), 10, 100)
        self.sell(d(2024, 3, 1), 4, 100)
        url = reverse("investments_available_units")
        base = {"instrument": self.reliance.pk, "portfolio": self.portfolio.pk, "broker": self.zerodha.pk, "folio": ""}
        self.assertEqual(self.client.get(url, {**base, "date": "2024-02-01"}).json()["units"], "10.0000")
        self.assertEqual(D(self.client.get(url, {**base, "date": "2024-04-01"}).json()["units"]), D(6))
        other = self.client.get(url, {**base, "broker": self.groww.pk, "date": "2024-04-01"}).json()
        self.assertEqual((other["place"], D(other["units"])), (True, D(0)))

    def test_availability_needs_login(self):
        self.client.logout()
        self.assertNotEqual(self.client.get(reverse("investments_available_units"), {"instrument": self.reliance.pk}).status_code, 200)
