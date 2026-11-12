"""The Annual Report and capital gains (plan 13, 31) and the investment page extras (plan 10)."""
from datetime import date as d, timedelta
from decimal import Decimal as D

from django.urls import reverse

from investments.models import Instrument, PinnedPrice, Price, Transaction
from investments.services import annual, corporate, dividends, investment_page, masters, pins, transactions as tx
from investments.tests.base import InvTestCase


class AnnualTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.nifty = Instrument.objects.get(code="^NSEI")
        for day, n, r in ((d(2023, 3, 31), 17000, 100), (d(2024, 3, 28), 22000, 130), (d(2025, 3, 28), 23500, 150)):
            Price.objects.create(instrument=self.nifty, date=day, close=D(n), source="api")
            Price.objects.create(instrument=self.reliance, date=day, close=D(r), source="api")
        self.buy(d(2022, 6, 1), 10, 80)            # long-term by the 2023-24 sale
        self.buy(d(2023, 6, 1), 10, 110)           # short-term
        self.sell(d(2024, 1, 15), 15, 125, charges=5)
        dividends.add(self.profile, self.user, date=d(2023, 8, 1), instrument=self.reliance, portfolio=self.portfolio, broker=self.zerodha, amount=D(40),
                      tax_deducted=D(4))

    def test_the_seven_lines_and_gains_split_by_the_cutoff(self):
        r = annual.build(self.profile, "2023-24", today=d(2026, 11, 9))
        self.assertTrue(r.completed)
        self.assertEqual((r.start, r.closing), (d(2023, 4, 1), d(2024, 3, 31)))
        self.assertEqual(r.opening_value, D(1000))                 # 10 units at the 31 March 2023 price of 100
        self.assertEqual(r.invested, D(1100))
        self.assertEqual(r.sold, D(1870))                          # 15 x 125 less 5 charges
        self.assertEqual(r.reinvested, D(-770))
        long_sale = [s for s in r.sales if s["term"] == "long"][0]
        self.assertEqual((long_sale["units"], long_sale["cost"]), (D(10), D(800)))
        self.assertEqual(r.long_gain, D(1870) * 10 / 15 - 800)
        self.assertEqual(r.short_gain, D(1870) * 5 / 15 - 550)
        self.assertEqual(r.closing_value, D(5 * 130))
        self.assertEqual((r.dividends, r.dividend_tax), (D(40), D(4)))
        self.assertAlmostEqual(r.index_return, 22000 / 17000 - 1)
        self.assertIsNotNone(r.xirr)

    def test_taxed_as_interest_sales_are_interest_income_not_capital_gains(self):
        total = D(1870) * 10 / 15 - 800 + D(1870) * 5 / 15 - 550
        Instrument.objects.filter(pk=self.reliance.pk).update(taxed_as_interest=True)
        r = annual.build(self.profile, "2023-24", today=d(2026, 11, 9))
        self.assertEqual((r.short_gain, r.long_gain), (0, 0))
        self.assertEqual(r.interest_income, total)
        self.assertTrue(all(s["interest"] for s in r.sales))
        r = self.client.get(reverse("investments_annual") + "?fy=2023-24")
        self.assertContains(r, "Interest income")

    def test_cutoff_per_year_changes_the_split(self):
        masters.update_settings(self.profile, self.user, year_cutoffs={"2023-24": 800})
        r = annual.build(self.profile, "2023-24", today=d(2026, 11, 9))
        self.assertEqual(r.long_gain, 0)
        self.assertEqual(r.cutoff, 800)
        self.assertEqual(annual.build(self.profile, "2024-25", today=d(2026, 11, 9)).cutoff, 365)

    def test_cost_override_is_used_for_gains(self):
        t = Transaction.objects.filter(side="buy").order_by("date").first()
        tx.edit_transaction(self.profile, self.user, t.pk, cost_override=D(500), cost_override_note="grandfathered")
        r = annual.build(self.profile, "2023-24", today=d(2026, 11, 9))
        self.assertEqual([s["cost"] for s in r.sales if s["term"] == "long"], [D(500)])

    def test_awaiting_on_31_march_is_at_cost_and_provisional(self):
        tx.add_transaction(self.profile, self.user, side="buy", instrument=self.fund, portfolio=self.portfolio, broker=self.zerodha, date=d(2024, 3, 20),
                           awaiting=True, amount=D(5000))
        r = annual.build(self.profile, "2023-24", today=d(2026, 11, 9))
        self.assertTrue(r.provisional)
        self.assertEqual(len(r.awaiting), 1)
        self.assertEqual(r.closing_value, D(5 * 130) + D(5000))
        self.assertEqual(r.invested, D(1100) + D(5000))

    def test_reproduces_from_pins_after_the_prices_are_gone(self):
        pins.pin_all(today=d(2026, 11, 9))
        before = annual.build(self.profile, "2023-24", today=d(2026, 11, 9))
        Price.objects.all().delete()
        after = annual.build(self.profile, "2023-24", today=d(2026, 11, 9))
        for field in ("opening_value", "closing_value", "short_gain", "long_gain", "index_return", "xirr", "invested", "sold"):
            self.assertEqual(getattr(before, field), getattr(after, field), field)
        self.assertGreater(PinnedPrice.objects.filter(reason="year_end").count(), 0)

    def test_bonus_lot_gain_and_by_portfolio(self):
        ca = corporate.record(self.profile, self.user, instrument=self.reliance, ex_date=d(2024, 2, 1), kind="bonus", ratio_old=1, ratio_new=1)
        corporate.respond(self.profile, self.user, ca.pk, "applied")
        self.sell(d(2024, 3, 1), 8, 70)
        r = annual.build(self.profile, "2023-24", today=d(2026, 11, 9))
        bonus = [s for s in r.sales if s["bonus"]]
        self.assertTrue(bonus)
        self.assertEqual(bonus[0]["cost"], 0)
        self.assertEqual(len(r.by_portfolio), 1)

    def test_page_and_label_only(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse("investments_annual") + "?fy=2023-24")
        self.assertContains(r, "Annual Report 2023-24")
        self.assertNotContains(r, "1 Apr 2023")
        self.assertContains(r, "not tax advice")
        r = self.client.post(reverse("investments_annual") + "?fy=2023-24", {"cutoff": "730"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(masters.core.get_settings(self.profile).year_cutoffs, {"2023-24": 730})


class InvestmentPageTests(InvTestCase):
    def test_purchase_rows_against_the_index_and_short_period_return(self):
        nifty = Instrument.objects.get(code="^NSEI")
        for day, n, r in ((d(2023, 1, 2), 100, 50), (d(2024, 1, 2), 110, 75), (d(2024, 6, 1), 115, 80)):
            Price.objects.create(instrument=nifty, date=day, close=D(n), source="api")
            Price.objects.create(instrument=self.reliance, date=day, close=D(r), source="api")
        self.buy(d(2023, 1, 2), 10, 50)
        self.buy(d(2024, 1, 2), 10, 75)
        from investments.services import holdings
        (h,), _ = holdings.compute(self.profile, as_of=d(2024, 6, 1))
        held, sold = investment_page.purchase_rows(self.profile, self.reliance, h, d(2024, 6, 1))
        first, second = held
        self.assertTrue(first["annual"])
        self.assertAlmostEqual(first["return"], (80 / 50) ** (365 / 516) - 1, places=6)
        self.assertAlmostEqual(first["index_return"], (115 / 100) ** (365 / 516) - 1, places=6)
        self.assertFalse(second["annual"])
        self.assertAlmostEqual(second["return"], 80 / 75 - 1, places=6)
        self.assertEqual(sold, [])
        self.assertEqual(investment_page.range_52w(self.reliance, d(2024, 6, 1)), (D(75), D(80)))

    def test_page_with_a_past_date_and_chart_markers(self):
        for n in range(60):
            Price.objects.create(instrument=self.reliance, date=d.today() - timedelta(days=n), close=D(100 + n), source="api")
        self.buy(d.today() - timedelta(days=30), 10, 120)
        self.client.force_login(self.user)
        r = self.client.get(reverse("investments_investment", args=[self.reliance.pk]))
        self.assertContains(r, "<polyline")
        self.assertContains(r, "Buy 10 at 120")
        r = self.client.get(reverse("investments_investment", args=[self.reliance.pk]) + f"?on={(d.today() - timedelta(days=40)).isoformat()}")
        self.assertEqual(r.status_code, 200)
