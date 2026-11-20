"""Buy and sell pages: every added transaction is a full card; sales are checked cumulatively; the units-available endpoint."""
import re
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
        for name in ("date", "instrument", "portfolio", "broker", "units", "price", "folio", "new_folio", "origin", "corporate_action"):
            self.assertIn(f'name="x__i__-{name}"', template)
        for name in ("allotment_date", "charges", "note"):          # not on a purchase (owner round 2026-11)
            self.assertNotIn(f'name="x__i__-{name}"', template)
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
        self.assertEqual(self.client.get(url, {**base, "date": "2024-02-01"}).json()["units"], "10")   # no trailing zeros for Sell all
        self.assertEqual(D(self.client.get(url, {**base, "date": "2024-04-01"}).json()["units"]), D(6))
        other = self.client.get(url, {**base, "broker": self.groww.pk, "date": "2024-04-01"}).json()
        self.assertEqual((other["place"], D(other["units"])), (True, D(0)))

    def test_availability_needs_login(self):
        self.client.logout()
        self.assertNotEqual(self.client.get(reverse("investments_available_units"), {"instrument": self.reliance.pk}).status_code, 200)


class PriceAndTentativeFormTests(InvTestCase):
    """Price per unit is required on an ordinary entry (the Total amount box is gone); "Mark as Tentative" relaxes it."""

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

    def test_there_is_no_total_box_any_more(self):
        for url in (self.url, reverse("investments_txn_new_sell")):
            html = self.client.get(url).content.decode()
            self.assertNotIn('name="total"', html)
            self.assertNotIn("Total amount", html)

    def test_price_and_units_are_required_on_an_ordinary_entry(self):
        self.assertContains(self.post(units="3"), "This field is required.")
        self.assertContains(self.post(price="10"), "This field is required.")
        self.assertEqual(Transaction.objects.count(), 0)

    def test_price_and_units_still_save(self):
        self.assertRedirects(self.post(units="3", price="12.5"), reverse("investments_transactions"))
        self.assertEqual(Transaction.objects.get().price, D("12.5"))

    def test_a_posted_total_is_ignored(self):
        self.post(units="4", price="30", total="100")
        self.assertEqual(Transaction.objects.get().price, D("30"))

    def test_lump_sum_is_unchanged(self):
        chit = masters.create_instrument(self.profile, self.user, kind="alternative", name="Chit", asset_class="debt", lump_sum=True)
        self.client.post(self.url, self.card(instrument=chit, lump_amount="5000"))
        t = Transaction.objects.get()
        self.assertEqual((t.units, t.price), (D("5000"), D("1")))

    def test_edit_of_a_sale_still_needs_its_price(self):
        self.post(units="10", price="10")
        sale = self.client.post(reverse("investments_txn_new_sell"), self.card(date="2024-02-01", units="4", price="15"))
        self.assertRedirects(sale, reverse("investments_transactions"))
        t = Transaction.objects.get(side="sell")
        form = self.card(date="2024-02-01", units="4", version=t.version)
        self.assertContains(self.client.post(reverse("investments_txn_edit", args=[t.pk]), form), "This field is required.")

    # ---- Mark as Tentative

    def test_the_buy_and_sell_forms_have_the_tick_box_and_the_amount_box(self):
        self.buy(d(2024, 1, 1), 10, 100, instrument=self.art)
        for url, label in ((self.url, "Amount paid"), (reverse("investments_txn_new_sell"), "Expected proceeds")):
            html = self.client.get(url).content.decode()
            self.assertIn('name="tentative"', html)
            self.assertIn("Mark as Tentative", html)
            self.assertIn('name="amount"', html)
            self.assertIn(label, html)
            self.assertIn("(only for a tentative entry)", html)

    def test_the_old_awaiting_addresses_redirect_with_the_box_ticked(self):
        for path, name in (("awaiting/", "investments_txn_new_buy"), ("awaiting-redemption/", "investments_txn_new_sell")):
            r = self.client.get("/investments/transactions/" + path)
            self.assertEqual((r.status_code, r["Location"]), (302, reverse(name) + "?tentative=1"))
            tag = re.search(r'<input[^>]*name="tentative"[^>]*>', self.client.get(r["Location"]).content.decode()).group(0)
            self.assertIn("checked", tag)

    def test_only_the_four_basic_fields_are_needed_when_ticked(self):
        r = self.post(tentative="on")
        self.assertRedirects(r, reverse("investments_transactions"))
        t = Transaction.objects.get()
        self.assertEqual((t.status, t.units, t.price, t.amount), ("tentative", None, None, None))

    def test_partial_values_are_kept(self):
        self.post(tentative="on", units="5", amount="450")
        t = Transaction.objects.get()
        self.assertEqual((t.units, t.price, t.amount), (D("5"), None, D("450")))

    def test_the_four_basic_fields_are_still_required_when_ticked(self):
        r = self.client.post(self.url, {"tentative": "on", "date": "2024-01-01"})
        self.assertContains(r, "This field is required.")
        self.assertEqual(Transaction.objects.count(), 0)

    def test_an_amount_typed_without_the_tick_is_not_kept(self):
        self.post(units="3", price="10", amount="999")
        self.assertIsNone(Transaction.objects.get().amount)

    def test_a_tentative_sale_skips_the_you_held_none_check(self):
        self.buy(d(2024, 3, 1), 10, 100, instrument=self.art)
        r = self.client.post(reverse("investments_txn_new_sell"), self.card(date="2024-01-01", tentative="on", amount="900"))
        self.assertRedirects(r, reverse("investments_transactions"))
        self.assertEqual(Transaction.objects.get(side="sell").status, "tentative")
        r = self.client.post(reverse("investments_txn_new_sell"), self.card(date="2024-01-01", units="1", price="9"))
        self.assertContains(r, "You held none of this investment")

    def test_a_tentative_entry_cannot_be_a_bonus(self):
        r = self.post(tentative="on", origin="bonus")
        self.assertContains(r, "ordinary purchase")
        self.assertEqual(Transaction.objects.count(), 0)

    def test_each_card_has_its_own_tick(self):
        post = {**self.card(units="2", price="5"), "extra_rows": "1", **self.card("x1", tentative="on")}
        self.client.post(self.url, post)
        self.assertEqual(sorted(Transaction.objects.values_list("status", flat=True)), ["final", "tentative"])

    def test_editing_a_tentative_entry_shows_the_tick_and_untick_finalises_it(self):
        self.post(tentative="on", amount="450")
        t = Transaction.objects.get()
        html = self.client.get(reverse("investments_txn_edit", args=[t.pk])).content.decode()
        self.assertIn('name="tentative"', html)
        self.assertIn("checked", re.search(r'<input[^>]*name="tentative"[^>]*>', html).group(0))
        keep = self.client.post(reverse("investments_txn_edit", args=[t.pk]), self.card(tentative="on", units="5", amount="450", version=t.version))
        self.assertEqual(keep.status_code, 302)
        t.refresh_from_db()
        self.assertEqual((t.status, t.units, t.amount), ("tentative", D("5"), D("450")))
        refused = self.client.post(reverse("investments_txn_edit", args=[t.pk]), self.card(units="5", version=t.version))
        self.assertContains(refused, "This field is required.")
        done = self.client.post(reverse("investments_txn_edit", args=[t.pk]), self.card(units="5", price="90", version=t.version))
        self.assertEqual(done.status_code, 302)
        t.refresh_from_db()
        self.assertEqual((t.status, t.amount, t.price), ("final", None, D("90")))

    def test_a_final_entry_has_no_tick_box(self):
        self.post(units="3", price="10")
        t = Transaction.objects.get()
        html = self.client.get(reverse("investments_txn_edit", args=[t.pk])).content.decode()
        self.assertNotIn('name="tentative"', html)
        self.assertNotIn('name="amount"', html)

    def test_each_card_is_cleaned_on_its_own(self):
        post = {**self.card(units="2", price="50"), "extra_rows": "1", **self.card("x1", units="4", price="3")}
        self.client.post(self.url, post)
        self.assertEqual(sorted(Transaction.objects.values_list("price", flat=True)), [D("3"), D("50")])
