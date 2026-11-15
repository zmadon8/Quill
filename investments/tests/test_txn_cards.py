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
        self.assertIn('data-combo data-for="x__i__-instrument"', template)      # the combobox replaces the Held only box on Buy
        self.assertNotIn("held-only-box", template)

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


class AlternativeTotalTests(InvTestCase):
    """Alternatives bought per unit: Units with a Price per unit, a Total amount, or both (D187)."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.art = masters.create_instrument(self.profile, self.user, kind="alternative", name="Painting set", asset_class="gold")
        self.url = reverse("investments_txn_new_buy")

    def card(self, prefix="", instrument=None, **extra):
        p = prefix + "-" if prefix else ""
        base = {"date": "2024-01-01", "instrument": (instrument or self.art).pk, "portfolio": self.portfolio.pk, "broker": self.zerodha.pk, "charges": "0"}
        return {p + k: v for k, v in {**base, **extra}.items()}

    def post(self, **extra):
        return self.client.post(self.url, self.card(**extra))

    def test_total_only_gives_price_to_four_places(self):
        self.assertRedirects(self.post(units="3", total="100"), reverse("investments_transactions"))
        self.assertEqual(Transaction.objects.get().price, D("33.3333"))

    def test_price_only_still_works(self):
        self.post(units="3", price="12.5")
        self.assertEqual(Transaction.objects.get().price, D("12.5"))

    def test_both_agreeing_keeps_the_price(self):
        self.post(units="4", price="25", total="100")
        self.assertEqual(Transaction.objects.get().price, D("25"))

    def test_both_disagreeing_the_total_wins(self):
        self.post(units="4", price="30", total="100")
        self.assertEqual(Transaction.objects.get().price, D("25"))

    def test_total_with_zero_units_is_refused(self):
        r = self.post(units="0", total="100")
        self.assertContains(r, "Units must be above zero")
        self.assertEqual(Transaction.objects.count(), 0)

    def test_neither_price_nor_total_is_refused(self):
        self.assertContains(self.post(units="3"), "This field is required.")
        self.assertEqual(Transaction.objects.count(), 0)

    def test_shares_do_not_take_a_total(self):
        r = self.post(instrument=self.reliance, units="3", total="100")
        self.assertContains(r, "only be given for an alternative investment")
        self.assertEqual(Transaction.objects.count(), 0)

    def test_lump_sum_is_unchanged(self):
        chit = masters.create_instrument(self.profile, self.user, kind="alternative", name="Chit", asset_class="debt", lump_sum=True)
        self.client.post(self.url, self.card(instrument=chit, lump_amount="5000", total="7"))
        t = Transaction.objects.get()
        self.assertEqual((t.units, t.price), (D("5000"), D("1")))

    def test_sell_with_total(self):
        self.post(units="10", price="10")
        r = self.client.post(reverse("investments_txn_new_sell"), self.card(date="2024-02-01", units="4", total="60"))
        self.assertRedirects(r, reverse("investments_transactions"))
        self.assertEqual(Transaction.objects.get(side="sell").price, D("15"))

    def test_each_card_is_worked_out_on_its_own(self):
        post = {**self.card(units="2", total="50"), "extra_rows": "1", **self.card("x1", units="4", price="3")}
        self.client.post(self.url, post)
        self.assertEqual(sorted(Transaction.objects.values_list("price", flat=True)), [D("3"), D("25")])
