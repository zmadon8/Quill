"""Dividends, corporate actions (shared, confirmed per profile, both price bases) and alerts (plan 7, 8, 14, 16.2, 31)."""
from datetime import date as d, timedelta
from decimal import Decimal as D

from django.test import SimpleTestCase
from django.urls import reverse

from investments import corporate as corporate_math, lots
from investments.errors import InvestmentsError
from investments.models import AlertState, CorporateAction, DividendSignal, Guardrail, Instrument, PinnedPrice, Portfolio, Price
from investments.services import alerts, corporate, dividends, holdings, masters, transactions as tx
from investments.tests.base import InvTestCase, make_user

A = lots.Bucket(1, 1, None)
B = lots.Bucket(1, 2, None)


class LotMathTests(SimpleTestCase):
    def test_split_multiplies_units_keeps_cost_and_dates(self):
        events = [lots.Event(lots.BUY, d(2023, 1, 1), D(10), A, "b1", D(1000))] + corporate_math.events([(7, "split", d(2024, 1, 1), D(5))])
        result = lots.replay(events)
        (lot,) = result.all_lots()
        self.assertEqual((lot.units, lot.cost, lot.bought_on), (D(50), D(1000), d(2023, 1, 1)))

    def test_bonus_adds_a_zero_cost_lot_from_its_date_in_each_bucket(self):
        events = [lots.Event(lots.BUY, d(2023, 1, 1), D(10), A, "b1", D(1000)), lots.Event(lots.BUY, d(2023, 1, 1), D(4), B, "b2", D(400))]
        events += corporate_math.events([(8, "bonus", d(2024, 1, 1), D("0.5"))])     # 1 free for every 2
        result = lots.replay(events)
        self.assertEqual(result.units(A), D(15))
        self.assertEqual(result.units(B), D(6))
        bonus = [l for l in result.lots[A] if l.cost == 0][0]
        self.assertEqual((bonus.bought_on, bonus.units), (d(2024, 1, 1), D(5)))
        sale = lots.replay(events + [lots.Event(lots.SELL, d(2024, 6, 1), D(12), A, "s", D(1800))])
        self.assertEqual([m.buy_ref for m in sale.matches], ["b1", ("ca", 8)])            # FIFO: the original lot first, then the bonus lot

    def test_purchase_on_the_ex_date_is_not_split(self):
        events = [lots.Event(lots.BUY, d(2024, 1, 1), D(10), A, "b1", D(100))] + corporate_math.events([(1, "split", d(2024, 1, 1), D(2))])
        self.assertEqual(lots.replay(events).units(), D(10))

    def test_basis_factor(self):
        actions = [(1, "split", d(2024, 1, 1), D(5)), (2, "bonus", d(2025, 1, 1), D("0.5"))]
        self.assertEqual(corporate_math.basis_factor(actions, d(2023, 6, 1), "split_adjusted"), D("7.5"))
        self.assertEqual(corporate_math.basis_factor(actions, d(2024, 6, 1), "split_adjusted"), D("1.5"))
        self.assertEqual(corporate_math.basis_factor(actions, d(2023, 6, 1), "raw"), D(1))


class CorporateActionTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.buy(d(2023, 1, 1), 10, 1000)

    def split(self, apply=True, profile=None, user=None):
        ca = corporate.record(profile or self.profile, user or self.user, instrument=self.reliance, ex_date=d(2024, 1, 1), kind="split", ratio_old=1, ratio_new=5)
        if apply:
            corporate.respond(profile or self.profile, user or self.user, ca.pk, "applied")
        return ca

    def test_pending_until_confirmed_then_applied_and_trades_unchanged(self):
        ca = self.split(apply=False)
        rows, totals = holdings.compute(self.profile, as_of=d(2024, 6, 1))
        self.assertTrue(rows[0].provisional)
        self.assertEqual(rows[0].units, D(10))
        self.assertEqual(totals.provisional, 1)
        corporate.respond(self.profile, self.user, ca.pk, "applied")
        rows, _ = holdings.compute(self.profile, as_of=d(2024, 6, 1))
        self.assertFalse(rows[0].provisional)
        self.assertEqual((rows[0].units, rows[0].cost), (D(50), D(10000)))
        from investments.models import Transaction
        self.assertEqual(Transaction.objects.get().units, D(10))

    def test_shared_record_confirmed_separately_by_each_profile(self):
        other_user, other = make_user("o5")
        pf = Portfolio.objects.create(profile=other, name="P")
        from investments.models import Broker
        br = Broker.objects.create(profile=other, name="B")
        tx.add_transaction(other, other_user, side="buy", instrument=self.reliance, portfolio=pf, broker=br, date=d(2023, 1, 1), units=D(3), price=D(1000))
        ca = self.split(apply=True)
        self.assertEqual(CorporateAction.objects.count(), 1)
        self.assertEqual([a.pk for a in corporate.pending(other)], [ca.pk])
        self.assertEqual(holdings.compute(other, as_of=d(2024, 6, 1))[0][0].units, D(3))
        corporate.respond(other, other_user, ca.pk, "not_applicable")
        self.assertEqual(corporate.pending(other), [])
        self.assertEqual(holdings.compute(other, as_of=d(2024, 6, 1))[0][0].units, D(3))

    def test_block_mode_leaves_the_holding_out_of_totals(self):
        self.split(apply=False)
        masters.update_settings(self.profile, self.user, corporate_action_mode="block")
        rows, totals = holdings.compute(self.profile, as_of=d(2024, 6, 1))
        self.assertTrue(rows[0].blocked)
        self.assertIsNone(rows[0].xirr)
        self.assertEqual((totals.value, totals.invested, totals.blocked), (D(0), D(0), 1))

    def test_selling_the_new_units_needs_the_split_applied(self):
        ca = self.split(apply=False)
        with self.assertRaises(InvestmentsError):
            self.sell(d(2024, 2, 1), 30, 210)
        corporate.respond(self.profile, self.user, ca.pk, "applied")
        self.sell(d(2024, 2, 1), 30, 210)
        with self.assertRaises(InvestmentsError) as cm:           # taking it off would leave the sale short
            corporate.respond(self.profile, self.user, ca.pk, "not_applicable")
        self.assertEqual(cm.exception.code, "WOULD_GO_NEGATIVE")

    def test_past_valuation_on_both_price_bases(self):
        self.split(apply=True)
        # split-adjusted series: the price before the split is restated (200 instead of 1000)
        Price.objects.create(instrument=self.reliance, date=d(2023, 6, 1), close=D(200), source="api", basis="split_adjusted")
        rows, _ = holdings.compute(self.profile, as_of=d(2023, 6, 1))
        self.assertEqual(rows[0].units, D(10))
        self.assertEqual(rows[0].value, D(10000))                # 10 units then = 50 on today's basis, times 200
        # raw series: actual units then times the price as traded
        masters.update_shared_details(self.profile, self.user, self.reliance, price_source="manual")
        self.reliance.price_basis = "raw"
        self.reliance.save()
        Price.objects.filter(instrument=self.reliance).update(close=D(1000), basis="raw")
        rows, _ = holdings.compute(self.profile, as_of=d(2023, 6, 1))
        self.assertEqual(rows[0].value, D(10000))

    def test_recording_adjusts_earlier_pins_of_a_split_adjusted_instrument_once(self):
        PinnedPrice.objects.create(instrument=self.reliance, asked_date=d(2023, 3, 31), trading_date=d(2023, 3, 31), close=D(1000), reason="year_end")
        PinnedPrice.objects.create(instrument=self.reliance, asked_date=d(2024, 3, 31), trading_date=d(2024, 3, 28), close=D(210), reason="year_end")
        self.split(apply=False)
        closes = dict(PinnedPrice.objects.values_list("asked_date", "close"))
        self.assertEqual(closes[d(2023, 3, 31)], D(200))
        self.assertEqual(closes[d(2024, 3, 31)], D(210))
        self.split(apply=False)                                   # recording again changes nothing
        self.assertEqual(PinnedPrice.objects.get(asked_date=d(2023, 3, 31)).close, D(200))

    def test_bonus_and_near_duplicates_and_bad_ratios(self):
        corporate.record(self.profile, self.user, instrument=self.reliance, ex_date=d(2024, 5, 1), kind="bonus", ratio_old=2, ratio_new=1)
        with self.assertRaises(InvestmentsError):
            corporate.record(self.profile, self.user, instrument=self.reliance, ex_date=d(2024, 5, 3), kind="bonus", ratio_old=2, ratio_new=1)
        with self.assertRaises(InvestmentsError):
            corporate.record(self.profile, self.user, instrument=self.reliance, ex_date=d(2024, 7, 1), kind="split", ratio_old=1, ratio_new=1)

    def test_detected_split_from_the_feed_becomes_a_pending_action(self):
        from unittest import mock
        from investments.adapters import http
        from investments.services import fetch
        from investments.tests.fakehttp import FakeNet, fixture
        net = FakeNet()
        net.add("RELIANCE.NS", fixture("yahoo_chart_reliance.json"))
        with mock.patch.object(http, "_urlopen", net), mock.patch.object(http, "sleep", lambda s: None):
            fetch.fetch_prices(ids=[self.reliance.pk], today=d(2026, 11, 9), rng=lambda: 0.0)
        ca = CorporateAction.objects.get()
        self.assertTrue(ca.detected)
        self.assertEqual((ca.ratio_old, ca.ratio_new), (D(1), D(2)))
        self.assertEqual(corporate.pending(self.profile), [ca])
        self.assertTrue(DividendSignal.objects.filter(instrument=self.reliance, ex_date=d(2026, 11, 3)).exists())

    def test_large_fall_without_action_is_flagged(self):
        today = d.today()
        Price.objects.create(instrument=self.reliance, date=today - timedelta(days=10), close=D(1000), source="api")
        Price.objects.create(instrument=self.reliance, date=today - timedelta(days=9), close=D(210), source="api")
        self.assertEqual(len(corporate.large_moves_without_action(self.profile)), 1)
        corporate.record(self.profile, self.user, instrument=self.reliance, ex_date=today - timedelta(days=9), kind="split", ratio_old=1, ratio_new=5)
        self.assertEqual(corporate.large_moves_without_action(self.profile), [])

    def test_confirmation_is_in_the_history(self):
        from investments.models import InvestmentHistory
        self.split(apply=True)
        self.assertTrue(InvestmentHistory.objects.filter(record_type="ca_response").exists())


class DividendTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.buy(d(2023, 1, 1), 10, 100)

    def add(self, day=d(2023, 7, 1), amount="50"):
        return dividends.add(self.profile, self.user, date=day, instrument=self.reliance, portfolio=self.portfolio, broker=self.zerodha, amount=D(amount))

    def test_never_in_value_and_in_xirr_only_when_switched_on(self):
        Price.objects.create(instrument=self.reliance, date=d(2024, 1, 1), close=D(100), source="api")
        self.add()
        rows, totals = holdings.compute(self.profile, as_of=d(2024, 1, 1))
        self.assertEqual(totals.value, D(1000))
        self.assertEqual(totals.dividends, D(50))
        self.assertAlmostEqual(totals.xirr, 0.0, places=6)
        rows, totals = holdings.compute(self.profile, as_of=d(2024, 1, 1), include_dividends=True)
        self.assertEqual(totals.value, D(1000))
        self.assertGreater(totals.xirr, 0.04)

    def test_suggestion_and_reminder(self):
        DividendSignal.objects.create(instrument=self.reliance, ex_date=d.today() - timedelta(days=10), per_unit=D("2.5"))
        due = dividends.due(self.profile)
        self.assertEqual((len(due), due[0]["amount"]), (1, D("25.00")))
        s = dividends.suggestion(self.profile, self.reliance, d.today())
        self.assertEqual(s["amount"], D("25.00"))
        self.add(day=d.today() - timedelta(days=2), amount="25")
        self.assertEqual(dividends.due(self.profile), [])

    def test_by_financial_year_and_history_and_validation(self):
        self.add(day=d(2023, 3, 30))
        self.add(day=d(2023, 4, 2), amount="70")
        self.assertEqual([(fy, r) for fy, r, _t in dividends.by_year(self.profile)], [("2023-24", D(70)), ("2022-23", D(50))])
        with self.assertRaises(InvestmentsError):
            self.add(day=d(2999, 1, 1))
        from investments.models import InvestmentHistory
        self.assertEqual(InvestmentHistory.objects.filter(record_type="dividend").count(), 2)

    def test_pages(self):
        self.client.force_login(self.user)
        r = self.client.post(reverse("investments_dividend_new"), {"date": "2023-07-01", "instrument": self.reliance.pk, "portfolio": self.portfolio.pk,
                                                                   "broker": self.zerodha.pk, "amount": "1,250.50", "tax_deducted": "125"})
        self.assertRedirects(r, reverse("investments_dividends"))
        r = self.client.get(reverse("investments_dividends"))
        self.assertContains(r, "Reliance Industries")
        self.assertContains(r, "2023-24")
        r = self.client.get(reverse("investments_dashboard") + "?div=1")
        self.assertContains(r, 'aria-checked="true"')
        self.assertTrue(holdings.core.get_settings(self.profile).include_dividends)


class AlertTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.today = d.today()
        self.buy(self.today - timedelta(days=100), 10, 100)

    def close(self, days_ago, price):
        Price.objects.update_or_create(instrument=self.reliance, date=self.today - timedelta(days=days_ago), defaults={"close": D(price), "source": "api"})

    def test_rule_a_daily_fall_and_window(self):
        self.close(10, 100)
        self.close(1, 100)
        self.close(0, 93)
        found = {a.kind: a for a in alerts.evaluate(self.profile)}
        self.assertIn("rule_a", found)
        self.assertIn("Fell 7.00% in a day", found["rule_a"].label)
        self.close(0, 84)
        self.assertIn("rule_a_window", {a.kind for a in alerts.evaluate(self.profile)})

    def test_rule_b_against_cost_per_portfolio_with_term(self):
        self.close(1, 75)
        self.close(0, 75)
        (a,) = [x for x in alerts.evaluate(self.profile) if x.kind == "rule_b"]
        self.assertIn("25.00% below cost", a.label)
        self.assertEqual(a.portfolio_name, "Main")
        self.assertEqual((a.term, a.days_to_long), ("short-term", 265))

    def test_guardrail_replaces_global_and_dismiss_snooze_rearm(self):
        self.close(1, 150)
        self.close(0, 150)
        Guardrail.objects.create(profile=self.profile, instrument=self.reliance, portfolio=self.portfolio, kind="target_gain", value=D(30))
        kinds = [a.kind for a in alerts.evaluate(self.profile)]
        self.assertEqual(kinds, ["guardrail"])
        key = alerts.visible(self.profile)[0]["key"]
        alerts.act(self.profile, key, "dismiss")
        self.assertEqual(alerts.visible(self.profile), [])
        alerts.act(self.profile, key, "reset")
        alerts.act(self.profile, key, "snooze", until=self.today + timedelta(days=3))
        self.assertEqual(alerts.visible(self.profile), [])
        alerts.act(self.profile, key, "reset")
        alerts.act(self.profile, key, "rearm", level=60)
        holdings.core.touch(self.profile)
        self.assertEqual([a for a in alerts.evaluate(self.profile) if a.kind == "guardrail"], [])      # 50% gain, re-armed at 60%
        self.assertTrue(AlertState.objects.filter(rearm_level=60).exists())

    def test_awaiting_purchases_are_left_out(self):
        tx.add_transaction(self.profile, self.user, side="buy", instrument=self.fund, portfolio=self.portfolio, broker=self.zerodha,
                           date=self.today - timedelta(days=3), awaiting=True, amount=D(5000))
        Price.objects.create(instrument=self.fund, date=self.today, close=D(1), source="api")
        self.assertFalse([a for a in alerts.evaluate(self.profile) if a.instrument_id == self.fund.pk])

    def test_maturity_and_page_and_badge(self):
        fd = masters.create_instrument(self.profile, self.user, kind="alternative", name="FD", maturity_date=self.today + timedelta(days=10))
        self.assertIn("maturity", [a.kind for a in alerts.evaluate(self.profile)])
        self.client.force_login(self.user)
        r = self.client.get(reverse("investments_alerts"))
        self.assertContains(r, "Matures in 10 days")
        self.assertContains(r, 'class="dot"')
        self.assertEqual(fd.profile_id, self.profile.pk)

    def test_settings_page_saves(self):
        self.client.force_login(self.user)
        r = self.client.post(reverse("investments_settings_alerts"), {"rule_a_enabled": "on", "rule_a_fall_pct": "4", "rule_a_rise_pct": "9", "rule_a_window_days": "10",
                                                                        "rule_b_loss_pct": "15", "rule_b_gain_pct": "50", "maturity_alert_days": "20"})
        self.assertRedirects(r, reverse("investments_settings_alerts"))
        row = holdings.core.get_settings(self.profile)
        self.assertEqual((row.rule_a_fall_pct, row.rule_b_enabled, row.rule_a_window_fall_pct), (D(4), False, None))


class PageTests(InvTestCase):
    def test_corporate_actions_page_records_and_applies(self):
        self.client.force_login(self.user)
        self.buy(d(2023, 1, 1), 10, 1000)
        r = self.client.post(reverse("investments_corporate_actions"), {"action": "record", "instrument": self.reliance.pk, "ex_date": "2024-01-01", "kind": "split",
                                                                        "ratio_old": "1", "ratio_new": "5", "apply_now": "on"})
        self.assertRedirects(r, reverse("investments_corporate_actions"))
        self.assertEqual(holdings.compute(self.profile)[0][0].units, D(50))
        r = self.client.get(reverse("investments_corporate_actions"))
        self.assertContains(r, "Split: 1 becomes 5")
        self.assertContains(r, "Applied")
        self.assertEqual(Instrument.objects.get(pk=self.reliance.pk).pk, self.reliance.pk)


class AlertEmailTests(InvTestCase):
    def test_new_alerts_are_emailed_once(self):
        from django.core import mail
        from django.test import override_settings
        from investments.services import alert_mail
        self.user.email = "owner@example.test"
        self.user.save()
        today = d.today()
        self.buy(today - timedelta(days=100), 10, 100)
        Price.objects.create(instrument=self.reliance, date=today, close=D(50), source="api")
        masters.update_settings(self.profile, self.user, alert_email=True)
        with override_settings(EMAIL_HOST="smtp.test", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            self.assertEqual(alert_mail.send_all()[0], 1)
            self.assertIn("below cost", mail.outbox[0].body)
            self.assertEqual(alert_mail.send_all()[0], 0)
