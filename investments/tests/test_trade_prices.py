"""Manual Price History entries made from transactions (docs/DESIGN.md D181, D182): the price of a buy or sell is the price on its date for
investments whose prices are typed by hand, and a Lump Sum records the value after a purchase and the value before a sale."""
from decimal import Decimal as D

from django.urls import reverse

from investments.errors import InvestmentsError
from investments.models import AltValue, ManualPrice, Price
from investments.services import holdings, masters, prices, series, trade_prices
from investments.services import transactions as tx
from investments.tests.base import InvTestCase, d


class ManualPricedBase(InvTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        masters.update_shared_details(self.profile, self.user, self.reliance, price_source="manual")
        self.reliance.refresh_from_db()
        self.gold = masters.create_instrument(self.profile, self.user, kind="alternative", name="Gold coins", asset_class="gold")

    def manual(self, day):
        return ManualPrice.objects.filter(instrument=self.reliance, date=day).first()

    def alt(self, day, instrument=None):
        return AltValue.objects.filter(profile=self.profile, instrument=instrument or self.gold, date=day).first()


class UnitPricedManualInvestmentTests(ManualPricedBase):
    def test_a_purchase_is_the_price_on_its_date(self):
        self.buy(d(2024, 1, 5), 10, "101.25")
        row = self.manual(d(2024, 1, 5))
        self.assertEqual((row.close, row.note, row.entered_by), (D("101.25"), "From purchase", self.user))

    def test_a_sale_is_the_price_on_its_date(self):
        self.buy(d(2024, 1, 5), 10, 100)
        self.sell(d(2024, 2, 1), 4, 120)
        self.assertEqual((self.manual(d(2024, 2, 1)).close, self.manual(d(2024, 2, 1)).note), (D("120"), "From sale"))
        self.assertEqual(self.manual(d(2024, 1, 5)).note, "From purchase")

    def test_trades_on_one_day_give_the_units_weighted_average(self):
        self.buy(d(2024, 1, 1), 20, 90)
        self.buy(d(2024, 2, 1), 10, 100)
        self.sell(d(2024, 2, 1), 5, 110)
        row = self.manual(d(2024, 2, 1))
        self.assertEqual((row.close, row.note), (D("103.3333"), "From purchase and sale"))     # (10 x 100 + 5 x 110) / 15

    def test_the_order_trades_were_entered_in_does_not_matter(self):
        self.buy(d(2024, 1, 1), 20, 90)
        self.sell(d(2024, 2, 1), 5, 110)
        self.buy(d(2024, 2, 1), 10, 100)
        self.assertEqual(self.manual(d(2024, 2, 1)).close, D("103.3333"))

    def test_a_hand_entry_for_the_date_is_kept(self):
        prices.set_manual_price(self.profile, self.user, self.reliance, d(2024, 1, 5), D("99"), "my quote")
        self.buy(d(2024, 1, 5), 10, 101)
        row = self.manual(d(2024, 1, 5))
        self.assertEqual((row.close, row.note), (D("99"), "my quote"))

    def test_a_hand_edit_of_a_derived_entry_makes_it_a_hand_entry(self):
        t = self.buy(d(2024, 1, 5), 10, 101)
        prices.set_manual_price(self.profile, self.user, self.reliance, d(2024, 1, 5), D("102"), "checked on the site")
        tx.edit_transaction(self.profile, self.user, t.pk, price="150")
        self.assertEqual(self.manual(d(2024, 1, 5)).close, D("102"))

    def test_an_uploaded_price_for_the_date_is_kept(self):
        masters.update_shared_details(self.profile, self.user, self.reliance, price_source="upload")
        self.reliance.refresh_from_db()
        Price.objects.create(instrument=self.reliance, date=d(2024, 1, 5), close=D("98"), source="upload")
        self.buy(d(2024, 1, 5), 10, 101)
        self.buy(d(2024, 1, 6), 10, 103)
        self.assertIsNone(self.manual(d(2024, 1, 5)))
        self.assertEqual(self.manual(d(2024, 1, 6)).close, D("103"))

    def test_editing_the_price_updates_the_entry(self):
        t = self.buy(d(2024, 1, 5), 10, 100)
        tx.edit_transaction(self.profile, self.user, t.pk, price="105.5")
        self.assertEqual(self.manual(d(2024, 1, 5)).close, D("105.5"))

    def test_editing_the_date_moves_the_entry(self):
        t = self.buy(d(2024, 1, 5), 10, 100)
        tx.edit_transaction(self.profile, self.user, t.pk, date=d(2024, 1, 6))
        self.assertIsNone(self.manual(d(2024, 1, 5)))
        self.assertEqual((self.manual(d(2024, 1, 6)).close, self.manual(d(2024, 1, 6)).note), (D("100"), "From purchase"))

    def test_deleting_the_trade_removes_the_entry_but_a_hand_entry_survives(self):
        t = self.buy(d(2024, 1, 5), 10, 100)
        keep = self.buy(d(2024, 1, 8), 10, 100)
        prices.set_manual_price(self.profile, self.user, self.reliance, d(2024, 1, 8), D("97"), "typed")
        tx.delete_transaction(self.profile, self.user, t.pk)
        tx.delete_transaction(self.profile, self.user, keep.pk)
        self.assertIsNone(self.manual(d(2024, 1, 5)))
        self.assertEqual(self.manual(d(2024, 1, 8)).close, D("97"))

    def test_another_profiles_trade_keeps_the_shared_entry(self):
        from investments.models import Broker, Portfolio
        from investments.tests.base import make_user

        other_user, other = make_user("second")
        portfolio, broker = Portfolio.objects.create(profile=other, name="Main"), Broker.objects.create(profile=other, name="Zerodha")
        mine = self.buy(d(2024, 1, 5), 10, 100)
        tx.add_transaction(other, other_user, side="buy", instrument=self.reliance, portfolio=portfolio, broker=broker, date=d(2024, 1, 5),
                           units=D(30), price=D(104))
        self.assertEqual(self.manual(d(2024, 1, 5)).close, D("103"))                  # (10 x 100 + 30 x 104) / 40
        tx.delete_transaction(self.profile, self.user, mine.pk)
        self.assertEqual(self.manual(d(2024, 1, 5)).close, D("104"))

    def test_a_trade_in_a_shared_instrument_bumps_the_shared_price_version(self):
        from investments.services import fetch

        before = fetch.price_version()
        self.buy(d(2024, 1, 5), 10, 100)
        self.assertGreater(fetch.price_version(), before)

    def test_opening_balances_estimates_and_bonus_units_are_not_prices(self):
        self.buy(d(2024, 1, 1), 10, 100, is_opening=True)
        self.buy(d(2024, 1, 2), 10, 100, is_estimated=True)
        tx.add_transaction(self.profile, self.user, side="buy", instrument=self.reliance, portfolio=self.portfolio, broker=self.zerodha,
                           date=d(2024, 1, 3), units=D(5), price=D(0), origin="bonus")
        self.assertEqual(ManualPrice.objects.count(), 0)

    def test_an_investment_with_a_fetched_price_source_gets_no_entry(self):
        self.buy(d(2024, 1, 5), 10, 100, instrument=self.fund)
        self.assertEqual(ManualPrice.objects.count(), 0)

    def test_completing_an_awaiting_purchase_makes_the_entry(self):
        awaiting = tx.add_transaction(self.profile, self.user, side="buy", instrument=self.reliance, portfolio=self.portfolio, broker=self.zerodha,
                                      date=d(2024, 1, 5), awaiting=True, amount=D(1000))
        self.assertEqual(ManualPrice.objects.count(), 0)
        tx.complete_transaction(self.profile, self.user, awaiting.pk, allotment_date=d(2024, 1, 6), units=D(10), nav=D(100))
        self.assertEqual(self.manual(d(2024, 1, 5)).close, D("100"))

    def test_the_investment_page_lists_the_entries_with_their_tags(self):
        self.buy(d(2024, 1, 5), 10, 100)
        page = self.client.get(reverse("investments_investment", args=[self.reliance.pk]))
        self.assertContains(page, "Manual Price History")
        self.assertContains(page, '<span class="tag">From purchase</span>')


class AlternativeInvestmentTests(ManualPricedBase):
    def test_the_value_is_units_held_times_the_price(self):
        self.buy(d(2024, 1, 1), 10, 100, instrument=self.gold)
        row = self.alt(d(2024, 1, 1))
        self.assertEqual((row.total_value, row.nav, row.note), (D("1000.00"), D("100"), "From purchase"))
        self.buy(d(2024, 2, 1), 5, 120, instrument=self.gold)
        self.assertEqual(self.alt(d(2024, 2, 1)).total_value, D("1800.00"))                  # 15 units at 120

    def test_a_sale_values_what_is_left(self):
        self.buy(d(2024, 1, 1), 10, 100, instrument=self.gold)
        self.sell(d(2024, 3, 1), 4, 150, instrument=self.gold)
        row = self.alt(d(2024, 3, 1))
        self.assertEqual((row.total_value, row.note), (D("900.00"), "From sale"))              # 6 units at 150

    def test_a_backdated_trade_works_the_later_entries_out_again(self):
        self.buy(d(2024, 1, 1), 10, 100, instrument=self.gold)
        self.buy(d(2024, 2, 1), 5, 120, instrument=self.gold)
        self.buy(d(2023, 12, 1), 10, 90, instrument=self.gold)
        self.assertEqual(self.alt(d(2023, 12, 1)).total_value, D("900.00"))
        self.assertEqual(self.alt(d(2024, 1, 1)).total_value, D("2000.00"))                    # 20 units now
        self.assertEqual(self.alt(d(2024, 2, 1)).total_value, D("3000.00"))                    # 25 units

    def test_a_hand_value_for_the_date_is_kept_and_other_dates_still_follow(self):
        prices.set_alt_value(self.profile, self.user, self.gold, d(2024, 1, 1), 1234, note="statement")
        self.buy(d(2024, 1, 1), 10, 100, instrument=self.gold)
        self.assertEqual((self.alt(d(2024, 1, 1)).total_value, self.alt(d(2024, 1, 1)).note), (D("1234.0000"), "statement"))
        self.buy(d(2024, 2, 1), 5, 120, instrument=self.gold)
        self.assertEqual(self.alt(d(2024, 2, 1)).total_value, D("1800.00"))

    def test_deleting_the_trade_removes_its_value_and_recomputes_later_ones(self):
        first = self.buy(d(2024, 1, 1), 10, 100, instrument=self.gold)
        self.buy(d(2024, 2, 1), 5, 120, instrument=self.gold)
        tx.delete_transaction(self.profile, self.user, first.pk)
        self.assertIsNone(self.alt(d(2024, 1, 1)))
        self.assertEqual(self.alt(d(2024, 2, 1)).total_value, D("600.00"))

    def test_selling_everything_leaves_no_value_for_that_date(self):
        self.buy(d(2024, 1, 1), 10, 100, instrument=self.gold)
        self.sell(d(2024, 3, 1), 10, 150, instrument=self.gold)
        self.assertIsNone(self.alt(d(2024, 3, 1)))

    def test_an_investment_with_an_interest_rate_gets_no_value_from_a_trade(self):
        fd = masters.create_instrument(self.profile, self.user, kind="alternative", name="Bank FD", asset_class="debt", interest_rate=D(8))
        self.buy(d(2024, 1, 1), 1, 100000, instrument=fd)
        self.assertEqual(AltValue.objects.filter(instrument=fd).count(), 0)

    def test_giving_an_interest_rate_removes_the_values_made_from_trades_but_not_hand_values(self):
        self.buy(d(2024, 1, 1), 10, 100, instrument=self.gold)
        prices.set_alt_value(self.profile, self.user, self.gold, d(2024, 2, 1), 1500, note="statement")
        masters.update_alt_interest(self.profile, self.user, self.gold, interest_rate=D(7), interest_type="simple", maturity_date=None)
        self.assertEqual(list(AltValue.objects.filter(instrument=self.gold).values_list("note", flat=True)), ["statement"])

    def test_a_lump_sum_buy_made_with_units_and_price_gets_no_unit_price_entry(self):
        chit = masters.create_instrument(self.profile, self.user, kind="alternative", name="Chit", asset_class="debt", lump_sum=True)
        self.assertFalse(trade_prices.eligible(chit))
        self.buy(d(2024, 1, 1), 100, 1, instrument=chit)
        self.assertEqual(AltValue.objects.filter(instrument=chit).count(), 0)

    def test_the_investment_page_shows_the_heading_and_tag(self):
        self.buy(d(2024, 1, 1), 10, 100, instrument=self.gold)
        page = self.client.get(reverse("investments_investment", args=[self.gold.pk]))
        self.assertContains(page, "<h2>Manual Price History</h2>")
        self.assertContains(page, '<span class="tag">From purchase</span>')


class LumpSumTradePriceTests(ManualPricedBase):
    def setUp(self):
        super().setUp()
        self.chit = masters.create_instrument(self.profile, self.user, kind="alternative", name="Chit fund", asset_class="debt", lump_sum=True)

    def lump(self, side, day, amount, **kw):
        return tx.add_lump_sum_transaction(self.profile, self.user, side=side, instrument=self.chit, portfolio=self.portfolio, broker=self.zerodha,
                                           date=day, amount=D(amount), **kw)

    def value(self, day):
        return self.alt(day, self.chit)

    def test_a_purchase_with_a_value_after_saves_it(self):
        self.lump("buy", d(2024, 1, 1), 100000, value_after=D(130000))
        row = self.value(d(2024, 1, 1))
        self.assertEqual((row.total_value, row.note), (D("130000"), "From purchase"))

    def test_the_first_purchase_without_a_value_records_nothing(self):
        self.lump("buy", d(2024, 1, 1), 100000)
        self.assertEqual(AltValue.objects.count(), 0)

    def test_a_later_purchase_adds_its_amount_to_the_last_value(self):
        self.lump("buy", d(2024, 1, 1), 100000, value_after=D(100000))
        prices.set_alt_value(self.profile, self.user, self.chit, d(2024, 2, 1), 120000, note="statement")
        self.lump("buy", d(2024, 3, 1), 50000)
        row = self.value(d(2024, 3, 1))
        self.assertEqual((row.total_value, row.note), (D("170000.00"), "From purchase"))

    def test_a_later_purchase_never_replaces_a_hand_value_for_its_date(self):
        self.lump("buy", d(2024, 1, 1), 100000, value_after=D(100000))
        prices.set_alt_value(self.profile, self.user, self.chit, d(2024, 4, 1), 200000, note="statement")
        self.lump("buy", d(2024, 4, 1), 10000)
        self.assertEqual((self.value(d(2024, 4, 1)).total_value, self.value(d(2024, 4, 1)).note), (D("200000.0000"), "statement"))

    def test_a_typed_value_after_replaces_a_hand_value_but_keeps_its_note(self):
        prices.set_alt_value(self.profile, self.user, self.chit, d(2024, 1, 1), 90000, note="statement")
        buy = self.lump("buy", d(2024, 1, 1), 100000, value_after=D(130000))
        row = self.value(d(2024, 1, 1))
        self.assertEqual((row.total_value, row.note), (D("130000"), "statement"))
        tx.delete_transaction(self.profile, self.user, buy.pk)
        self.assertIsNotNone(self.value(d(2024, 1, 1)))

    def test_a_purchase_with_an_interest_rate_adds_nothing(self):
        masters.update_own_instrument(self.profile, self.user, self.chit, interest_rate=D(8))
        self.lump("buy", d(2024, 1, 1), 100000, value_after=D(100000))
        self.lump("buy", d(2024, 3, 1), 50000)
        self.assertIsNone(self.value(d(2024, 3, 1)))

    def test_a_sale_saves_the_value_before_it_on_the_day_before_and_what_remains_on_the_day(self):
        self.lump("buy", d(2024, 1, 1), 140000)
        sale = self.lump("sell", d(2024, 7, 1), 30000, remaining=D(110000))
        before, after = self.value(d(2024, 6, 30)), self.value(d(2024, 7, 1))
        self.assertEqual((before.total_value, before.note), (D("140000.00"), "Before sale"))
        self.assertEqual((after.total_value, after.note), (D("110000"), "From sale"))
        self.assertEqual(sale.units, D("30000"))

    def test_a_sale_shows_no_gain_or_loss_across_the_sale_day(self):
        self.lump("buy", d(2024, 1, 1), 140000)
        self.lump("sell", d(2024, 7, 1), 30000, remaining=D(110000))
        rows, _t = holdings.compute(self.profile, as_of=d(2024, 6, 30))
        value_before = next(h for h in rows if h.instrument.pk == self.chit.pk).value
        rows, _t = holdings.compute(self.profile, as_of=d(2024, 7, 1))
        h = next(h for h in rows if h.instrument.pk == self.chit.pk)
        self.assertEqual(value_before, D("140000"))
        self.assertEqual(h.value + D("30000"), value_before)              # what is left plus the proceeds is what it was worth the day before
        self.assertEqual(h.realised, D("0"))
        values, _flows = series.portfolio_value_series(self.profile, [d(2024, 6, 30), d(2024, 7, 1)])
        self.assertEqual((values[0], values[1]), (D("140000"), D("110000")))

    def test_a_sale_on_the_day_of_the_purchase_has_no_value_before_it(self):
        self.lump("buy", d(2024, 1, 1), 140000)
        self.lump("sell", d(2024, 1, 1), 30000, remaining=D(110000))
        self.assertIsNone(self.value(d(2023, 12, 31)))
        self.assertEqual(self.value(d(2024, 1, 1)).note, "From sale")

    def test_a_sale_leaves_a_value_of_a_person_on_the_day_before_alone(self):
        self.lump("buy", d(2024, 1, 1), 140000)
        prices.set_alt_value(self.profile, self.user, self.chit, d(2024, 6, 30), 138000, note="statement")
        self.lump("sell", d(2024, 7, 1), 30000, remaining=D(110000))
        self.assertEqual(self.value(d(2024, 6, 30)).total_value, D("138000.0000"))

    def test_sell_all_uses_the_adjusted_remaining_in_the_value_before(self):
        from investments.models import Portfolio

        other = Portfolio.objects.create(profile=self.profile, name="Other")
        self.lump("buy", d(2024, 1, 1), 60000)
        tx.add_lump_sum_transaction(self.profile, self.user, side="buy", instrument=self.chit, portfolio=other, broker=self.zerodha,
                                    date=d(2024, 1, 2), amount=D(40000))
        self.lump("sell", d(2024, 7, 1), 66000, remaining=D(0))
        self.assertEqual(self.value(d(2024, 7, 1)).total_value, D("44000.00"))
        self.assertEqual(self.value(d(2024, 6, 30)).total_value, D("110000.00"))

    def test_deleting_the_sale_removes_both_values(self):
        self.lump("buy", d(2024, 1, 1), 140000)
        sale = self.lump("sell", d(2024, 7, 1), 30000, remaining=D(110000))
        tx.delete_transaction(self.profile, self.user, sale.pk)
        self.assertEqual(AltValue.objects.count(), 0)

    def test_deleting_the_purchase_removes_its_value(self):
        buy = self.lump("buy", d(2024, 1, 1), 100000, value_after=D(130000))
        prices.set_alt_value(self.profile, self.user, self.chit, d(2024, 2, 1), 120000, note="statement")
        tx.delete_transaction(self.profile, self.user, buy.pk)
        self.assertEqual(list(AltValue.objects.values_list("note", flat=True)), ["statement"])

    def test_an_old_remaining_after_a_sale_note_is_still_derived(self):
        self.assertTrue(prices.is_derived("Remaining after a sale"))
        self.assertFalse(prices.is_derived("statement"))
        self.assertFalse(prices.is_derived(""))

    def test_the_date_and_amount_of_a_lump_sum_entry_cannot_be_edited(self):
        buy = self.lump("buy", d(2024, 1, 1), 100000, value_after=D(100000))
        with self.assertRaises(InvestmentsError) as raised:
            tx.edit_transaction(self.profile, self.user, buy.pk, units="200000")
        self.assertEqual(raised.exception.code, "LUMP_SUM_EDIT")
        with self.assertRaises(InvestmentsError):
            tx.edit_transaction(self.profile, self.user, buy.pk, date=d(2024, 1, 2))
        tx.edit_transaction(self.profile, self.user, buy.pk, note="topped up", charges="10")
        buy.refresh_from_db()
        self.assertEqual((buy.note, buy.charges), ("topped up", D("10")))

    def test_the_forms_ask_for_the_value_after_only_on_a_purchase(self):
        self.assertContains(self.client.get(reverse("investments_txn_new_buy")), 'name="value_after"')
        self.assertNotContains(self.client.get(reverse("investments_txn_new_sell")), 'name="value_after"')
        buy = self.lump("buy", d(2024, 1, 1), 100000, value_after=D(100000))
        self.assertNotContains(self.client.get(reverse("investments_txn_edit", args=[buy.pk])), 'name="value_after"')

    def test_the_purchase_form_saves_the_value_after(self):
        post = {"date": "2024-01-01", "instrument": self.chit.pk, "portfolio": self.portfolio.pk, "broker": self.zerodha.pk, "charges": "0",
                "lump_amount": "100000", "value_after": "130000"}
        self.assertRedirects(self.client.post(reverse("investments_txn_new_buy"), post), reverse("investments_transactions"))
        self.assertEqual(self.value(d(2024, 1, 1)).total_value, D("130000"))
