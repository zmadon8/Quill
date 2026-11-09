"""Holdings, values and XIRR from transactions; masters; delete rules; backup and purge round trips."""
from datetime import date as d
from decimal import Decimal as D

from investments.errors import InvestmentsError
from investments.models import Folio, Instrument, InvestmentHistory, Portfolio, ProfileInvestment, Transaction
from investments.services import holdings, masters, prices, transactions as tx
from investments.tests.base import InvTestCase, make_user


class HoldingsTests(InvTestCase):
    def test_units_cost_value_gain_from_fifo(self):
        self.buy(d(2023, 1, 1), 10, 100)
        self.buy(d(2023, 6, 1), 10, 200)
        self.sell(d(2023, 9, 1), 15, 300)
        prices.set_manual_price(self.profile, self.user, self.reliance, d(2024, 1, 1), "250")
        rows, totals = holdings.compute(self.profile, as_of=d(2024, 1, 1))
        (h,) = rows
        self.assertEqual(h.units, D(5))
        self.assertEqual(h.cost, D(1000))            # the five left come from the 200 lot
        self.assertEqual(h.avg_cost, D(200))
        self.assertEqual(h.value, D(1250))
        self.assertEqual(h.gain, D(250))
        self.assertEqual(h.realised, D(4500) - D(1000) - D(1000))
        self.assertEqual(totals.value, D(1250))

    def test_unpriced_holding_is_valued_at_cost_and_flagged(self):
        self.buy(d(2023, 1, 1), 10, 100)
        (h,), _ = holdings.compute(self.profile, as_of=d(2024, 1, 1))
        self.assertTrue(h.unpriced)
        self.assertEqual(h.value, D(1000))

    def test_xirr_of_a_simple_holding(self):
        self.buy(d(2023, 1, 1), 10, 100)
        prices.set_manual_price(self.profile, self.user, self.reliance, d(2024, 1, 1), "110")
        (h,), totals = holdings.compute(self.profile, as_of=d(2024, 1, 1))
        self.assertAlmostEqual(h.xirr, 0.10, places=6)
        self.assertAlmostEqual(totals.xirr, 0.10, places=6)

    def test_portfolio_and_broker_filters(self):
        other = Portfolio.objects.create(profile=self.profile, name="Spouse")
        self.buy(d(2023, 1, 1), 10, 100, broker=self.zerodha)
        tx.add_transaction(self.profile, self.user, side="buy", instrument=self.reliance, portfolio=other, broker=self.groww,
                           date=d(2023, 1, 1), units=D(4), price=D(100))
        all_rows, _ = holdings.compute(self.profile, as_of=d(2024, 1, 1))
        self.assertEqual(all_rows[0].units, D(14))
        rows, _ = holdings.compute(self.profile, portfolio=other.pk, as_of=d(2024, 1, 1))
        self.assertEqual(rows[0].units, D(4))
        rows, _ = holdings.compute(self.profile, broker=self.zerodha.pk, as_of=d(2024, 1, 1))
        self.assertEqual(rows[0].units, D(10))

    def test_sold_out_investment_is_listed_as_sold_out(self):
        self.buy(d(2023, 1, 1), 10, 100)
        self.sell(d(2023, 6, 1), 10, 120)
        (h,), totals = holdings.compute(self.profile, as_of=d(2024, 1, 1))
        self.assertTrue(h.sold_out)
        self.assertEqual(totals.count, 0)

    def test_position_on_a_past_date(self):
        self.buy(d(2023, 1, 1), 10, 100)
        self.sell(d(2023, 6, 1), 4, 120)
        (h,), _ = holdings.compute(self.profile, as_of=d(2023, 3, 1))
        self.assertEqual(h.units, D(10))

    def test_alternative_investment_uses_dated_values_and_setting(self):
        fd = masters.create_instrument(self.profile, self.user, kind="alternative", name="HDFC Bank FD", asset_class="debt")
        tx.add_transaction(self.profile, self.user, side="buy", instrument=fd, portfolio=self.portfolio, broker=self.zerodha,
                           date=d(2024, 1, 1), units=D(1), price=D(100000))
        prices.set_alt_value(self.profile, self.user, fd, d(2024, 1, 1), 100000)
        prices.set_alt_value(self.profile, self.user, fd, d(2024, 1, 11), 101000)
        (h,), _ = holdings.compute(self.profile, as_of=d(2024, 1, 6))
        self.assertEqual(h.value, D(100000))
        masters.update_settings(self.profile, self.user, alt_treatment="averaged")
        (h,), _ = holdings.compute(self.profile, as_of=d(2024, 1, 6))
        self.assertEqual(h.value, D(100500))
        self.assertEqual(InvestmentHistory.objects.filter(record_type="altvalue").count(), 2)

    def test_allocation_sums_to_one(self):
        self.buy(d(2023, 1, 1), 10, 100)
        self.buy(d(2023, 1, 1), 10, 100, instrument=self.fund)
        rows, _ = holdings.compute(self.profile, as_of=d(2024, 1, 1))
        alloc = holdings.allocation(rows)
        self.assertAlmostEqual(sum(a[2] for a in alloc), 1.0)

    def test_few_queries_for_many_holdings(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        for i in range(15):
            inst = masters.create_instrument(self.profile, self.user, kind="share", name=f"Co {i}", code=f"C{i}.NS")
            self.buy(d(2023, 1, 1), 10, 100, instrument=inst)
        with CaptureQueriesContext(connection) as ctx:
            holdings.compute(self.profile, as_of=d(2024, 1, 1))
        self.assertLess(len(ctx), 16)          # a fixed number, however many holdings


class MastersTests(InvTestCase):
    def test_shared_vs_private_instruments(self):
        fd = masters.create_instrument(self.profile, self.user, kind="alternative", name="PPF - Ziyad")
        self.assertEqual(fd.profile_id, self.profile.pk)
        self.assertIsNone(self.reliance.profile_id)

    def test_duplicate_instrument_refused_with_existing_id(self):
        with self.assertRaises(InvestmentsError) as cm:
            masters.create_instrument(self.profile, self.user, kind="share", name="reliance  industries")
        self.assertEqual(cm.exception.details["existing_id"], self.reliance.pk)
        with self.assertRaises(InvestmentsError):
            masters.create_instrument(self.profile, self.user, kind="share", name="Something else", code="reliance.ns")

    def test_broker_rules(self):
        with self.assertRaises(InvestmentsError):
            masters.add_broker(self.profile, self.user, " zerodha ")
        with self.assertRaises(InvestmentsError):
            masters.add_broker(self.profile, self.user, "  ")
        self.buy(d(2024, 1, 1), 1, 1)
        with self.assertRaises(InvestmentsError):
            masters.delete_broker(self.profile, self.user, self.zerodha.pk)
        masters.delete_broker(self.profile, self.user, self.groww.pk)
        masters.set_broker_hidden(self.profile, self.user, self.zerodha.pk, True)

    def test_default_brokers_may_be_none_and_are_per_type(self):
        row = masters.update_settings(self.profile, self.user, default_broker_share=self.zerodha)
        self.assertEqual(row.default_broker_for("share"), self.zerodha)
        self.assertIsNone(row.default_broker_for("fund"))
        masters.update_settings(self.profile, self.user, default_broker_share=None)
        self.assertIsNone(masters.update_settings(self.profile, self.user).default_broker_for("share"))
        other_user, other = make_user("o2")
        from investments.models import Broker
        foreign = Broker.objects.create(profile=other, name="X")
        with self.assertRaises(InvestmentsError):
            masters.update_settings(self.profile, self.user, default_broker_share=foreign)

    def test_folio_look_alike_asks_and_exact_text_is_kept(self):
        f = masters.add_folio(self.profile, self.user, instrument=self.fund, portfolio=self.portfolio, number="ab/123 45")
        self.assertEqual(f.number, "ab/123 45")
        with self.assertRaises(InvestmentsError) as cm:
            masters.add_folio(self.profile, self.user, instrument=self.fund, portfolio=self.portfolio, number="AB/12345")
        self.assertEqual(cm.exception.code, "SIMILAR_FOLIO")
        masters.add_folio(self.profile, self.user, instrument=self.fund, portfolio=self.portfolio, number="AB/12345", confirm_new=True)
        with self.assertRaises(InvestmentsError):
            masters.add_folio(self.profile, self.user, instrument=self.fund, portfolio=self.portfolio, number="ab/123 45")

    def test_editor_can_delete_only_an_investment_without_records(self):
        editor, _ = make_user("ed", profile=self.profile)
        masters.delete_instrument(self.profile, editor, self.fund)
        self.assertFalse(Instrument.objects.filter(pk=self.fund.pk).exists())
        self.buy(d(2024, 1, 1), 1, 1)
        with self.assertRaises(InvestmentsError) as cm:
            masters.delete_instrument(self.profile, editor, self.reliance)
        self.assertEqual(cm.exception.code, "FORBIDDEN")

    def test_admin_delete_needs_name_takes_backup_and_logs(self):
        from backups.models import BackupFile
        t = self.buy(d(2024, 1, 1), 1, 1)
        with self.assertRaises(InvestmentsError) as cm:
            masters.delete_instrument(self.profile, self.user, self.reliance, confirm_name="wrong")
        self.assertEqual(cm.exception.code, "CONFIRM_NAME")
        self.assertEqual(cm.exception.details["counts"]["transactions"], 1)
        self.assertFalse(BackupFile.objects.filter(kind="pre_inv_delete").exists())
        masters.delete_instrument(self.profile, self.user, self.reliance, confirm_name="Reliance Industries")
        self.assertTrue(BackupFile.objects.filter(kind="pre_inv_delete").exists())
        self.assertFalse(Transaction.objects.filter(pk=t.pk).exists())
        self.assertTrue(InvestmentHistory.objects.filter(record_id=t.pk, change_kind="delete").exists())

    def test_shared_instrument_stays_while_another_profile_uses_it(self):
        other_user, other = make_user("o3")
        masters.get_profile_investment(other, self.reliance)
        masters.delete_instrument(self.profile, self.user, self.reliance)
        self.assertTrue(Instrument.objects.filter(pk=self.reliance.pk).exists())
        masters.delete_instrument(other, other_user, self.reliance)
        self.assertFalse(Instrument.objects.filter(pk=self.reliance.pk).exists())

    def test_hide_only_when_sold_out(self):
        self.buy(d(2024, 1, 1), 5, 10)
        with self.assertRaises(InvestmentsError):
            masters.update_profile_details(self.profile, self.user, self.reliance, hidden=True)
        self.sell(d(2024, 2, 1), 5, 12)
        masters.update_profile_details(self.profile, self.user, self.reliance, hidden=True)
        self.assertTrue(ProfileInvestment.objects.get(profile=self.profile, instrument=self.reliance).hidden)

    def test_shared_details_are_admin_only(self):
        editor, _ = make_user("ed2", profile=self.profile)
        with self.assertRaises(InvestmentsError):
            masters.update_shared_details(self.profile, editor, self.reliance, name="Hacked")
        masters.update_shared_details(self.profile, self.user, self.reliance, name="Reliance Industries Ltd")
        self.reliance.refresh_from_db()
        self.assertEqual(self.reliance.name, "Reliance Industries Ltd")

    def test_links_must_be_http(self):
        with self.assertRaises(InvestmentsError):
            masters.update_profile_details(self.profile, self.user, self.reliance, links=[{"label": "x", "url": "javascript:alert(1)"}])

    def test_builtin_indices_and_default(self):
        masters.ensure_builtin_indices()
        masters.ensure_builtin_indices()
        self.assertEqual(Instrument.objects.filter(kind="index", code="^NSEI").count(), 1)
        self.assertEqual(masters.default_index_for(self.profile).name, "Nifty 50")
        with self.assertRaises(InvestmentsError):
            masters.update_settings(self.profile, self.user, default_index=self.reliance)

    def test_cannot_buy_an_index(self):
        masters.ensure_builtin_indices()
        nifty = Instrument.objects.get(code="^NSEI")
        with self.assertRaises(InvestmentsError):
            self.buy(d(2024, 1, 1), 1, 1, instrument=nifty)


class BackupAndPurgeTests(InvTestCase):
    def test_backup_restore_round_trip_reproduces_data_and_history(self):
        from backups import services
        t = self.buy(d(2024, 1, 1), 10, 100)
        masters.add_folio(self.profile, self.user, instrument=self.fund, portfolio=self.portfolio, number="F1")
        prices.set_manual_price(self.profile, self.user, self.reliance, d(2024, 1, 2), "123.45")
        backup = services.create_backup("manual", self.user)
        before = (Transaction.objects.count(), Folio.objects.count(), InvestmentHistory.objects.count())
        Transaction.objects.all().delete()
        document = services.parse_backup(__import__("gzip").decompress(bytes(backup.data)), 10**9)
        services.restore_backup(document, self.user)
        self.assertEqual((Transaction.objects.count(), Folio.objects.count(), InvestmentHistory.objects.count()), before)
        self.assertEqual(Transaction.objects.get(pk=t.pk).units, D(10))
        self.assertEqual(self.reliance.manual_prices.get().close, D("123.4500"))

    def test_profile_purge_removes_investments_data_and_private_instruments(self):
        from accounts import purge
        fd = masters.create_instrument(self.profile, self.user, kind="alternative", name="Gold coins")
        self.buy(d(2024, 1, 1), 10, 100)
        tx.add_transaction(self.profile, self.user, side="buy", instrument=fd, portfolio=self.portfolio, broker=self.zerodha,
                           date=d(2024, 1, 1), units=D(1), price=D(5000))
        counts = purge._purge_one(self.profile)
        self.assertFalse(Transaction.objects.exists())
        self.assertFalse(Instrument.objects.filter(pk=fd.pk).exists())
        self.assertTrue(Instrument.objects.filter(pk=self.reliance.pk).exists())     # shared instrument remains
        self.assertTrue(counts)

    def test_profile_in_use_counts_transactions(self):
        from accounts.profiles import profile_usage, profile_usage_map
        self.buy(d(2024, 1, 1), 10, 100)
        self.assertEqual(profile_usage(self.profile)[1], 1)
        self.assertEqual(profile_usage_map([self.profile])[self.profile.pk][1], 1)
