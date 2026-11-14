"""Lump Sum alternative investments: amounts instead of units and price, the amount remaining after a sale, and Sell all."""
from datetime import date as d
from decimal import Decimal as D

from django.urls import reverse

from investments.errors import InvestmentsError
from investments.models import AltValue, Instrument, Transaction
from investments.services import core, holdings, masters
from investments.services import holdings_page
from investments.tests.base import InvTestCase

CRORE = D("10000000")


class LumpSumTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.chit = masters.create_instrument(self.profile, self.user, kind="alternative", name="Chit fund", asset_class="debt", lump_sum=True)

    def card(self, day, **extra):
        return {"date": day, "instrument": self.chit.pk, "portfolio": self.portfolio.pk, "broker": self.zerodha.pk, "charges": "0", **extra}

    def buy_lump(self, day="2024-01-01", amount="10000000"):
        r = self.client.post(reverse("investments_txn_new_buy"), self.card(day, lump_amount=amount))
        self.assertRedirects(r, reverse("investments_transactions"))

    def holding(self, as_of):
        rows, _totals = holdings.compute(self.profile, as_of=as_of)
        return next(h for h in rows if h.instrument.pk == self.chit.pk)

    # ---- the flag
    def test_only_alternatives_can_be_lump_sum(self):
        self.assertTrue(self.chit.lump_sum)
        share = masters.create_instrument(self.profile, self.user, kind="share", name="Some Share", code="SOME.NS", lump_sum=True)
        self.assertFalse(share.lump_sum)

    def test_the_flag_is_on_the_add_and_edit_forms(self):
        self.assertContains(self.client.get(reverse("investments_add_2") + "?kind=alternative"), 'name="lump_sum"')
        self.assertContains(self.client.get(reverse("investments_investment_edit", args=[self.chit.pk])), 'name="lump_sum"')

    def test_the_flag_cannot_change_once_there_are_transactions(self):
        other = masters.create_instrument(self.profile, self.user, kind="alternative", name="Gold coin", asset_class="gold")
        self.assertEqual(masters.update_own_instrument(self.profile, self.user, other, lump_sum=True), ["lump_sum"])
        self.buy_lump()
        with self.assertRaises(InvestmentsError):
            masters.update_own_instrument(self.profile, self.user, self.chit, lump_sum=False)

    # ---- buying
    def test_a_purchase_asks_for_an_amount_and_stores_it_as_units_at_a_price_of_one(self):
        self.buy_lump(amount="12500000.50")
        t = Transaction.objects.get()
        self.assertEqual((t.units, t.price), (D("12500000.50"), D("1")))
        self.assertEqual(core.buy_total(t), D("12500000.50"))

    def test_a_purchase_without_an_amount_is_refused(self):
        r = self.client.post(reverse("investments_txn_new_buy"), self.card("2024-01-01"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "This field is required.")
        self.assertEqual(Transaction.objects.count(), 0)

    def test_a_share_still_needs_units_and_price(self):
        post = {"date": "2024-01-01", "instrument": self.reliance.pk, "portfolio": self.portfolio.pk, "broker": self.zerodha.pk, "charges": "0"}
        r = self.client.post(reverse("investments_txn_new_buy"), post)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "This field is required.")
        self.assertEqual(Transaction.objects.count(), 0)

    def test_the_pages_name_the_lump_sum_investments(self):
        html = self.client.get(reverse("investments_txn_new_sell")).content.decode()
        self.assertIn(f'data-lump="{self.chit.pk}"', html)
        self.assertIn("sell-all", html)
        self.assertIn('name="lump_amount"', html)
        self.assertIn('name="remaining"', html)

    # ---- selling
    def test_a_partial_sale_sells_the_matching_share_of_the_units_and_records_what_remains(self):
        self.buy_lump()
        # Worth 1.1 crore on the day: 40 lakh sold, 70 lakh remains, so 4/11 of the cost is sold.
        r = self.client.post(reverse("investments_txn_new_sell"), self.card("2024-07-01", lump_amount="4000000", remaining="7000000"))
        self.assertRedirects(r, reverse("investments_transactions"))
        sale = Transaction.objects.get(side="sell")
        self.assertEqual(sale.units, D("3636363.6364"))
        self.assertLess(abs(core.sell_total(sale) - D("4000000")), D("0.001"))     # proceeds are the amount typed
        value = AltValue.objects.get(profile=self.profile, instrument=self.chit)
        self.assertEqual((value.date, value.total_value), (d(2024, 7, 1), D("7000000")))
        h = self.holding(d(2024, 7, 2))
        self.assertEqual(h.value, D("7000000"))
        self.assertLess(abs(h.realised - D("363636.36")), D("0.02"))                # 40 lakh less 4/11 of the 1 crore cost

    def test_selling_all_leaves_nothing_and_a_value_of_zero(self):
        self.buy_lump()
        r = self.client.post(reverse("investments_txn_new_sell"), self.card("2024-07-01", lump_amount="11000000", remaining="0"))
        self.assertRedirects(r, reverse("investments_transactions"))
        sale = Transaction.objects.get(side="sell")
        self.assertEqual(sale.units, CRORE)
        self.assertEqual(AltValue.objects.get(instrument=self.chit).total_value, D("0"))
        h = self.holding(d(2024, 7, 2))
        self.assertEqual(h.units, D("0"))
        self.assertTrue(h.sold_out)

    def test_a_sale_needs_the_amount_remaining(self):
        self.buy_lump()
        r = self.client.post(reverse("investments_txn_new_sell"), self.card("2024-07-01", lump_amount="4000000"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "This field is required.")
        self.assertEqual(Transaction.objects.filter(side="sell").count(), 0)
        self.assertEqual(AltValue.objects.count(), 0)

    def test_a_sale_from_a_place_that_holds_too_little_is_refused(self):
        self.buy_lump()
        post = {**self.card("2024-07-01", lump_amount="4000000", remaining="7000000"), "broker": self.groww.pk}
        r = self.client.post(reverse("investments_txn_new_sell"), post)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Transaction.objects.filter(side="sell").count(), 0)
        self.assertEqual(AltValue.objects.count(), 0)

    def test_a_sale_before_anything_was_bought_is_refused(self):
        self.buy_lump(day="2024-03-01")
        r = self.client.post(reverse("investments_txn_new_sell"), self.card("2024-01-01", lump_amount="100", remaining="0"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "You held none of this investment")

    def test_interest_grows_from_the_remaining_amount(self):
        masters.update_own_instrument(self.profile, self.user, self.chit, interest_rate=D("10"), interest_type="simple")
        self.buy_lump(day="2024-01-01")
        self.client.post(reverse("investments_txn_new_sell"), self.card("2024-07-01", lump_amount="4000000", remaining="7000000"))
        h = self.holding(d(2025, 7, 1))
        self.assertEqual(h.value, D("7000000") * D("1.1") + D("0"))          # simple interest, 365 days at 10% on the remaining amount

    def test_taxed_as_interest_books_the_gain_as_interest_income(self):
        masters.update_own_instrument(self.profile, self.user, self.chit, taxed_as_interest=True)
        self.buy_lump()
        self.client.post(reverse("investments_txn_new_sell"), self.card("2024-07-01", lump_amount="4000000", remaining="7000000"))
        h = self.holding(d(2024, 7, 2))
        self.assertEqual(h.realised, D("0"))
        self.assertLess(abs(h.interest_income - D("363636.36")), D("0.02"))

    # ---- display and the cached Holdings rows
    def test_pages_show_amounts_not_units(self):
        self.buy_lump()
        self.assertEqual(self.client.get(reverse("investments_holdings")).status_code, 200)
        self.assertEqual(self.client.get(reverse("investments_transactions")).status_code, 200)
        page = self.client.get(reverse("investments_investment", args=[self.chit.pk]))
        self.assertNotContains(page, '<div class="lab">Units</div>')

    def test_holdings_rows_cached_before_lump_sums_existed_still_load(self):
        row = {"id": 1, "name": "Old", "code": "", "kind": "share", "price_source": "manual", "kind_label": "Share"}
        self.assertFalse(holdings_page._Instrument(row).lump_sum)
        self.assertTrue(holdings_page._Instrument({**row, "lump_sum": True}).lump_sum)
        self.assertTrue(Instrument.objects.get(pk=self.chit.pk).lump_sum)


class SellPageTests(InvTestCase):
    """Sell all and the grouped figure are drawn by the script; the page must carry what it needs."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_each_sale_card_has_a_sell_all_button_and_the_buy_page_has_none(self):
        html = self.client.get(reverse("investments_txn_new_sell")).content.decode()
        self.assertEqual(html.count('class="btn q sm sell-all"'), 2)      # the first card and the template
        self.assertNotIn("sell-all", self.client.get(reverse("investments_txn_new_buy")).content.decode())

    def test_available_units_json_gives_the_units_held_in_one_place(self):
        self.buy(d(2024, 1, 1), "1234567.5", 10)
        url = reverse("investments_available_units") + (f"?instrument={self.reliance.pk}&date=2024-06-01&portfolio={self.portfolio.pk}"
                                                         f"&broker={self.zerodha.pk}&folio=")
        data = self.client.get(url).json()
        self.assertTrue(data["ok"] and data["place"])
        self.assertEqual(D(data["units"]), D("1234567.5"))
