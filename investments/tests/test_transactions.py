"""Transactions: selling limits, refused edits, awaiting allotment, history, opening balances, transfers, switches."""
from datetime import date as d
from decimal import Decimal as D

from investments.errors import InvestmentsError
from investments.models import InvestmentHistory, Transaction
from investments.services import history, holdings, masters, transactions as tx
from investments.tests.base import InvTestCase


class SellingLimitTests(InvTestCase):
    def test_sale_cannot_exceed_units_held(self):
        self.buy(d(2024, 1, 1), 10, 100)
        with self.assertRaises(InvestmentsError) as cm:
            self.sell(d(2024, 2, 1), 11, 120)
        self.assertEqual(cm.exception.code, "WOULD_GO_NEGATIVE")
        self.assertEqual(Transaction.objects.count(), 1)

    def test_sale_cannot_exceed_broker_units_even_if_total_is_enough(self):
        self.buy(d(2024, 1, 1), 10, 100, broker=self.zerodha)
        self.buy(d(2024, 1, 2), 10, 100, broker=self.groww)
        with self.assertRaises(InvestmentsError):
            self.sell(d(2024, 2, 1), 12, 120, broker=self.zerodha)
        self.sell(d(2024, 2, 1), 10, 120, broker=self.zerodha)

    def test_same_day_purchase_counts_before_sale(self):
        self.sell_first = None
        self.buy(d(2024, 3, 1), 5, 100)
        self.sell(d(2024, 3, 1), 5, 110)

    def test_folio_limit(self):
        folio = masters.add_folio(self.profile, self.user, instrument=self.fund, portfolio=self.portfolio, number="123/45")
        self.buy(d(2024, 1, 1), 10, 50, instrument=self.fund, folio=folio)
        self.buy(d(2024, 1, 1), 10, 50, instrument=self.fund)           # no folio
        with self.assertRaises(InvestmentsError):
            self.sell(d(2024, 2, 1), 11, 55, instrument=self.fund, folio=folio)

    def test_edit_that_breaks_a_later_sale_is_refused_and_lists_the_sale(self):
        buy = self.buy(d(2024, 1, 1), 10, 100)
        sale = self.sell(d(2024, 2, 1), 10, 120)
        with self.assertRaises(InvestmentsError) as cm:
            tx.edit_transaction(self.profile, self.user, buy.pk, units=D(6))
        err = cm.exception
        self.assertEqual(err.code, "WOULD_GO_NEGATIVE")
        self.assertEqual(err.details["conflicts"][0]["id"], sale.pk)
        buy.refresh_from_db()
        self.assertEqual(buy.units, D(10))

    def test_changing_the_broker_of_a_purchase_is_refused_when_sold_from_it(self):
        buy = self.buy(d(2024, 1, 1), 10, 100)
        self.sell(d(2024, 2, 1), 10, 120)
        with self.assertRaises(InvestmentsError):
            tx.edit_transaction(self.profile, self.user, buy.pk, broker=self.groww)

    def test_delete_that_breaks_a_sale_is_refused(self):
        buy = self.buy(d(2024, 1, 1), 10, 100)
        self.sell(d(2024, 2, 1), 4, 120)
        with self.assertRaises(InvestmentsError):
            tx.delete_transaction(self.profile, self.user, buy.pk)
        self.assertTrue(Transaction.objects.filter(pk=buy.pk).exists())

    def test_fixing_the_sale_first_then_the_purchase_works(self):
        buy = self.buy(d(2024, 1, 1), 10, 100)
        sale = self.sell(d(2024, 2, 1), 10, 120)
        tx.edit_transaction(self.profile, self.user, sale.pk, units=D(5))
        tx.edit_transaction(self.profile, self.user, buy.pk, units=D(6))

    def test_future_date_and_bad_numbers_refused(self):
        with self.assertRaises(InvestmentsError):
            self.buy(d(2999, 1, 1), 1, 1)
        with self.assertRaises(InvestmentsError):
            self.buy(d(2024, 1, 1), 0, 1)
        with self.assertRaises(InvestmentsError):
            self.buy(d(2024, 1, 1), 1, -5)

    def test_another_profiles_records_cannot_be_used(self):
        from investments.tests.base import make_user
        other_user, other = make_user("other")
        from investments.models import Broker, Portfolio
        theirs = Portfolio.objects.create(profile=other, name="X")
        with self.assertRaises(InvestmentsError):
            tx.add_transaction(self.profile, self.user, side="buy", instrument=self.reliance, portfolio=theirs, broker=self.zerodha,
                               date=d(2024, 1, 1), units=D(1), price=D(1))
        tb = Broker.objects.create(profile=other, name="TB")
        with self.assertRaises(InvestmentsError):
            tx.add_transaction(self.profile, self.user, side="buy", instrument=self.reliance, portfolio=self.portfolio, broker=tb,
                               date=d(2024, 1, 1), units=D(1), price=D(1))

    def test_version_clash_is_detected(self):
        buy = self.buy(d(2024, 1, 1), 10, 100)
        tx.edit_transaction(self.profile, self.user, buy.pk, expected_version=1, note="a")
        with self.assertRaises(InvestmentsError) as cm:
            tx.edit_transaction(self.profile, self.user, buy.pk, expected_version=1, note="b")
        self.assertEqual(cm.exception.code, "CLASH")


class AwaitingTests(InvTestCase):
    def awaiting(self, amount="50000", day=d(2024, 11, 4), **kw):
        return tx.add_transaction(self.profile, self.user, side="buy", instrument=self.fund, portfolio=self.portfolio,
                                  broker=self.zerodha, date=day, awaiting=True, amount=D(amount), **kw)

    def test_counts_at_cost_with_no_units_and_adds_nothing_to_gain(self):
        self.awaiting()
        rows, totals = holdings.compute(self.profile, as_of=d(2024, 11, 10))
        (h,) = rows
        self.assertEqual(h.units, 0)
        self.assertEqual(h.awaiting, D(50000))
        self.assertEqual(h.value, D(50000))
        self.assertEqual(h.gain, 0)
        self.assertEqual(totals.invested, D(50000))
        self.assertEqual(totals.gain, 0)

    def test_it_is_an_outflow_in_xirr_from_the_date_paid(self):
        self.awaiting("100000", day=d(2023, 1, 1))
        rows, totals = holdings.compute(self.profile, as_of=d(2024, 1, 1))
        # paid 1,00,000 and valued at cost a year later: a return of nil
        self.assertAlmostEqual(rows[0].xirr, 0.0, places=6)

    def test_cannot_be_sold_from_and_is_not_in_limits(self):
        self.awaiting()
        with self.assertRaises(InvestmentsError):
            self.sell(d(2024, 11, 5), 1, 50, instrument=self.fund)

    def test_leave_out_setting_removes_it(self):
        self.awaiting()
        masters.update_settings(self.profile, self.user, awaiting_treatment="leave_out")
        rows, totals = holdings.compute(self.profile, as_of=d(2024, 11, 10))
        self.assertEqual(totals.invested, 0)
        self.assertFalse(rows)

    def test_completion_works_out_the_third_figure_and_keeps_date_paid(self):
        a = self.awaiting("50000")
        done = tx.complete_transaction(self.profile, self.user, a.pk, allotment_date=d(2024, 11, 6), units=D("1000"), nav=None)
        self.assertEqual(done.price, D("50.0000"))
        self.assertEqual(done.status, "final")
        self.assertEqual(done.date, d(2024, 11, 4))
        self.assertEqual(done.allotment_date, d(2024, 11, 6))
        done2 = tx.complete_transaction(self.profile, self.user, self.awaiting("20000", day=d(2024, 11, 7)).pk,
                                        allotment_date=d(2024, 11, 8), units=None, nav=D("40"))
        self.assertEqual(done2.units, D("500.0000"))

    def test_completion_with_charges(self):
        a = self.awaiting("50000", charges=D("2.50"))
        done = tx.complete_transaction(self.profile, self.user, a.pk, allotment_date=d(2024, 11, 5), units=D(999), nav=None)
        self.assertEqual(done.charges, D("2.50"))
        self.assertEqual(done.price, ((D(50000) - D("2.5")) / D(999)).quantize(D("0.0001")))

    def test_difference_beyond_tolerance_needs_confirmation(self):
        a = self.awaiting("50000")
        with self.assertRaises(InvestmentsError) as cm:
            tx.complete_transaction(self.profile, self.user, a.pk, allotment_date=d(2024, 11, 6), units=D(900), nav=D(50))
        self.assertEqual(cm.exception.code, "DIFFERENCE")
        tx.complete_transaction(self.profile, self.user, a.pk, allotment_date=d(2024, 11, 6), units=D(900), nav=D(50), confirm_difference=True)

    def test_rounding_difference_passes(self):
        a = self.awaiting("50000")
        tx.complete_transaction(self.profile, self.user, a.pk, allotment_date=d(2024, 11, 6), units=D("1234.5678"), nav=D("40.5000"))

    def test_allotment_before_payment_refused(self):
        a = self.awaiting("50000")
        with self.assertRaises(InvestmentsError):
            tx.complete_transaction(self.profile, self.user, a.pk, allotment_date=d(2024, 11, 1), units=D(1000))

    def test_completed_units_start_the_holding_on_allotment_date_and_obey_limits(self):
        a = self.awaiting("50000")
        tx.complete_transaction(self.profile, self.user, a.pk, allotment_date=d(2024, 11, 8), units=D(1000))
        with self.assertRaises(InvestmentsError):
            self.sell(d(2024, 11, 5), 10, 50, instrument=self.fund)      # before the units existed
        self.sell(d(2024, 11, 8), 10, 50, instrument=self.fund)

    def test_cancel_logs_and_can_be_restored(self):
        a = self.awaiting()
        tx.cancel_awaiting(self.profile, self.user, a.pk)
        self.assertFalse(Transaction.objects.filter(pk=a.pk).exists())
        row = InvestmentHistory.objects.filter(record_id=a.pk).order_by("-version").first()
        self.assertEqual(row.change_kind, "cancel")
        history.restore(self.profile, self.user, row.pk)
        self.assertTrue(Transaction.objects.filter(pk=a.pk, status="awaiting").exists())

    def test_completion_is_in_the_history_with_old_and_new_values(self):
        a = self.awaiting()
        tx.complete_transaction(self.profile, self.user, a.pk, allotment_date=d(2024, 11, 6), units=D(1000))
        versions = list(InvestmentHistory.objects.filter(record_type="transaction", record_id=a.pk).order_by("version"))
        self.assertEqual([v.change_kind for v in versions], ["create", "complete"])
        changed = {k for k, _o, _n in history.diff(versions[0].snapshot, versions[1].snapshot)}
        self.assertIn("units", changed)
        self.assertIn("status", changed)

    def test_awaiting_redemption_is_not_checked_until_completed(self):
        self.buy(d(2024, 1, 1), 10, 50, instrument=self.fund)
        a = tx.add_transaction(self.profile, self.user, side="sell", instrument=self.fund, portfolio=self.portfolio, broker=self.zerodha,
                               date=d(2024, 6, 1), awaiting=True, amount=D(5000))
        with self.assertRaises(InvestmentsError) as cm:
            tx.complete_transaction(self.profile, self.user, a.pk, allotment_date=d(2024, 6, 3), units=D(20), nav=D(250))
        self.assertEqual(cm.exception.code, "WOULD_GO_NEGATIVE")
        tx.complete_transaction(self.profile, self.user, a.pk, allotment_date=d(2024, 6, 3), units=D(10), nav=D(500))

    def test_overdue_after_reminder_days(self):
        a = self.awaiting(day=d(2024, 11, 4))
        self.assertFalse(tx.overdue(a, 7, today=d(2024, 11, 11)))
        self.assertTrue(tx.overdue(a, 7, today=d(2024, 11, 12)))

    def test_nav_suggestions(self):
        from investments.services import prices
        a = self.awaiting("50000")
        prices.set_manual_price(self.profile, self.user, self.fund, d(2024, 11, 5), "50")
        prices.set_manual_price(self.profile, self.user, self.fund, d(2024, 11, 6), "51")
        prices.set_manual_price(self.profile, self.user, self.fund, d(2024, 11, 1), "40")
        rows = tx.nav_suggestions(self.profile, a)
        self.assertEqual([r["date"] for r in rows], [d(2024, 11, 5), d(2024, 11, 6)])
        self.assertEqual(rows[0]["units"], D("1000.0000"))


class OpeningTransferSwitchTests(InvTestCase):
    def test_opening_balance_lots_are_ordinary_purchases_flagged_opening(self):
        lots_ = [{"date": d(2019, 5, 1), "units": D(10), "cost_per_unit": D(100)},
                 {"date": d(2020, 5, 1), "units": D(5), "cost_per_unit": D(120), "estimated": True}]
        created = tx.add_opening_balances(self.profile, self.user, instrument=self.reliance, portfolio=self.portfolio,
                                          broker=self.zerodha, lines=lots_)
        self.assertTrue(all(t.is_opening and t.charges == 0 for t in created))
        self.assertTrue(created[1].is_estimated)
        self.sell(d(2024, 1, 1), 12, 200)        # obeys FIFO and limits like any purchase
        with self.assertRaises(InvestmentsError):
            self.sell(d(2024, 2, 1), 4, 200)

    def test_transfer_moves_units_between_brokers_keeping_dates(self):
        self.buy(d(2022, 1, 1), 10, 100)
        tx.add_transfer(self.profile, self.user, instrument=self.reliance, date=d(2023, 1, 1), units=D(10),
                        from_portfolio=self.portfolio, from_broker=self.zerodha, to_portfolio=self.portfolio, to_broker=self.groww)
        rows, _ = holdings.compute(self.profile, broker=self.groww.pk, as_of=d(2024, 1, 1))
        self.assertEqual(rows[0].units, D(10))
        self.assertEqual(rows[0].lots[0].bought_on, d(2022, 1, 1))
        with self.assertRaises(InvestmentsError):
            self.sell(d(2024, 1, 1), 1, 100, broker=self.zerodha)
        self.sell(d(2024, 1, 1), 10, 100, broker=self.groww)

    def test_transfer_of_too_many_units_refused_and_deleting_it_rechecks(self):
        self.buy(d(2022, 1, 1), 10, 100)
        with self.assertRaises(InvestmentsError):
            tx.add_transfer(self.profile, self.user, instrument=self.reliance, date=d(2023, 1, 1), units=D(11),
                            from_portfolio=self.portfolio, from_broker=self.zerodha, to_portfolio=self.portfolio, to_broker=self.groww)
        tr = tx.add_transfer(self.profile, self.user, instrument=self.reliance, date=d(2023, 1, 1), units=D(10),
                             from_portfolio=self.portfolio, from_broker=self.zerodha, to_portfolio=self.portfolio, to_broker=self.groww)
        self.sell(d(2024, 1, 1), 10, 100, broker=self.groww)
        with self.assertRaises(InvestmentsError):
            tx.delete_transfer(self.profile, self.user, tr.pk)

    def test_transfer_to_same_place_refused(self):
        self.buy(d(2022, 1, 1), 10, 100)
        with self.assertRaises(InvestmentsError):
            tx.add_transfer(self.profile, self.user, instrument=self.reliance, date=d(2023, 1, 1), units=D(1),
                            from_portfolio=self.portfolio, from_broker=self.zerodha, to_portfolio=self.portfolio, to_broker=self.zerodha)

    def test_switch_is_a_linked_sale_and_purchase(self):
        other = masters.create_instrument(self.profile, self.user, kind="fund", name="HDFC Index Fund", code="119063")
        self.buy(d(2023, 1, 1), 100, 10, instrument=self.fund)
        sw, sale, buy = tx.add_switch(self.profile, self.user, date=d(2024, 1, 1), portfolio=self.portfolio, broker=self.zerodha,
                                      from_instrument=self.fund, units_out=D(100), price_out=D(15), to_instrument=other,
                                      units_in=D(50), price_in=D(30))
        self.assertEqual((sale.switch_id, buy.switch_id), (sw.pk, sw.pk))
        with self.assertRaises(InvestmentsError):
            tx.delete_transaction(self.profile, self.user, sale.pk)
        tx.delete_switch(self.profile, self.user, sw.pk)
        self.assertEqual(Transaction.objects.count(), 1)


class HistoryTests(InvTestCase):
    def test_every_change_is_logged_with_a_snapshot(self):
        t = self.buy(d(2024, 1, 1), 10, 100)
        tx.edit_transaction(self.profile, self.user, t.pk, price=D(101))
        tx.delete_transaction(self.profile, self.user, t.pk)
        rows = list(InvestmentHistory.objects.filter(record_type="transaction", record_id=t.pk).order_by("version"))
        self.assertEqual([r.change_kind for r in rows], ["create", "edit", "delete"])
        self.assertEqual(rows[1].snapshot["price"], "101")
        self.assertEqual(rows[1].changed_by, self.user)

    def test_deleted_entry_restores_with_same_id(self):
        t = self.buy(d(2024, 1, 1), 10, 100)
        tx.delete_transaction(self.profile, self.user, t.pk)
        row = InvestmentHistory.objects.filter(record_id=t.pk, change_kind="delete").get()
        restored = history.restore(self.profile, self.user, row.pk)
        self.assertEqual(restored.pk, t.pk)
        self.assertEqual(restored.units, D(10))
        self.assertEqual(InvestmentHistory.objects.filter(record_id=t.pk).order_by("-version").first().change_kind, "restore")
        self.assertFalse(history.can_restore(self.profile, row))

    def test_restore_that_would_break_a_sale_is_refused(self):
        t = self.buy(d(2024, 1, 1), 10, 100)
        tx.delete_transaction(self.profile, self.user, t.pk)
        self.buy(d(2024, 1, 2), 5, 100)
        other = self.sell(d(2024, 2, 1), 5, 120)
        row = InvestmentHistory.objects.filter(record_id=t.pk, change_kind="delete").get()
        history.restore(self.profile, self.user, row.pk)         # more units: fine
        self.assertTrue(Transaction.objects.filter(pk=t.pk).exists())
        self.assertTrue(Transaction.objects.filter(pk=other.pk).exists())

    def test_history_survives_the_nightly_history_purge(self):
        from datetime import timedelta
        from django.utils import timezone
        t = self.buy(d(2024, 1, 1), 10, 100)
        tx.edit_transaction(self.profile, self.user, t.pk, price=D(101))
        InvestmentHistory.objects.update(changed_at=timezone.now() - timedelta(days=400))
        from accounts import purge
        purge.purge_old_history()
        self.assertEqual(InvestmentHistory.objects.count(), 2)

    def test_other_profile_cannot_restore(self):
        from investments.tests.base import make_user
        t = self.buy(d(2024, 1, 1), 10, 100)
        tx.delete_transaction(self.profile, self.user, t.pk)
        row = InvestmentHistory.objects.filter(change_kind="delete").get()
        _u, other = make_user("someone")
        with self.assertRaises(InvestmentsError):
            history.restore(other, self.user, row.pk)
