"""Owner round 2026-11: the Profit / Loss report, Alerts as a Reports tab, Home, New Investment and the Dividends third row, the
"Alerts Present" insight, and Sell all without trailing zeros."""
from datetime import date as d
from decimal import Decimal as D
from unittest import mock

from django.urls import reverse

from investments.models import Instrument
from investments.services import insights, masters, profit_loss
from investments.tests.base import InvTestCase


class ProfitLossServiceTests(InvTestCase):
    def setUp(self):
        super().setUp()
        # FY 2024-25: one sale of 15 Reliance using the first purchase (held over a year: long-term) and part of the second (short-term).
        self.buy(d(2023, 1, 1), 10, 100)
        self.buy(d(2024, 3, 1), 10, 200)
        self.sell(d(2024, 6, 1), 15, 300)
        # FY 2023-24: the fund's Capital Gains is off, so its profit is Other income.
        Instrument.objects.filter(pk=self.fund.pk).update(capital_gains=False)
        self.buy(d(2023, 1, 1), 10, 10, instrument=self.fund)
        self.sell(d(2023, 9, 1), 10, 15, instrument=self.fund)

    def test_sales_year_by_year_with_the_split(self):
        r = profit_loss.build(self.profile)
        self.assertEqual([y.label for y in r.years], ["2024-25", "2023-24"])
        newer = r.years[0]
        self.assertEqual(len(newer.sales), 1)
        sale = newer.sales[0]
        self.assertEqual((sale["cost"], sale["proceeds"], sale["profit"]), (D("2000.00"), D("4500.00"), D("2500.00")))
        self.assertAlmostEqual(sale["pct"], 1.25)
        self.assertEqual((sale["long_gain"], sale["short_gain"], sale["other_income"]), (D("2000.00"), D("500.00"), D("0.00")))
        self.assertIsNotNone(sale["xirr"])
        self.assertGreater(sale["xirr"], 0)
        self.assertEqual(sale["units"], D(15))
        older = r.years[1].sales[0]
        self.assertEqual((older["profit"], older["other_income"], older["long_gain"], older["short_gain"]),
                         (D("50.00"), D("50.00"), D("0.00"), D("0.00")))
        self.assertEqual(r.totals.profit, D("2550.00"))
        self.assertEqual(r.totals.count, 2)

    def test_the_page_and_its_export(self):
        self.client.force_login(self.user)
        page = self.client.get(reverse("investments_profit_loss"))
        self.assertContains(page, '<h1 class="visually-hidden">Profit / Loss</h1>')
        for text in ("Long-term capital gains", "Short-term capital gains", "Other income", "Profit / Loss %", "2024-25", "2023-24"):
            self.assertContains(page, text)
        export = self.client.get(reverse("investments_profit_loss") + "?export=xlsx")
        self.assertEqual(export.status_code, 200)


class NavigationTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def nav(self, name):
        html = self.client.get(reverse(name)).content.decode()
        return html, html.split('<span class="nav-links">')[1].split("</span>")[0]

    def test_top_entries(self):
        _html, top = self.nav("investments_dashboard")
        self.assertIn(">Home</a>", top)
        self.assertNotIn(">Overview", top)
        self.assertNotIn(">Alerts", top)

    def test_reports_tabs_in_order(self):
        html, _top = self.nav("investments_profit_loss")
        sub = html.split('<nav class="sub" aria-label="Section">')[1].split("</nav>")[0]
        order = [sub.index(">%s</a>" % t) for t in ("Annual Report", "Profit / Loss", "Alerts", "Other Reports")]
        self.assertEqual(order, sorted(order))
        alerts, _ = self.nav("investments_alerts")
        self.assertIn('class="on" aria-current="page">Alerts</a>', alerts)

    def test_holdings_tabs_and_dividends_inside_corporate_actions(self):
        html, _top = self.nav("investments_holdings")
        sub = html.split('<nav class="sub" aria-label="Section">')[1].split("</nav>")[0]
        order = [sub.index(">%s</a>" % t) for t in ("Investments", "Transactions", "New Investment", "Corporate Actions")]
        self.assertEqual(order, sorted(order))
        self.assertNotIn(">Dividends</a>", sub)
        self.assertNotIn(">Add investment</a>", html)
        for name, on in (("investments_corporate_actions", "Actions"), ("investments_dividends", "Dividends")):
            page = self.client.get(reverse(name)).content.decode()
            self.assertIn('class="on" aria-current="page">Corporate Actions</a>', page)
            third = page.split('<nav class="sub third"')[1].split("</nav>")[0]
            self.assertIn('class="on" aria-current="page">%s</a>' % on, third)
        add = self.client.get(reverse("investments_add_1")).content.decode()
        self.assertIn('class="on" aria-current="page">New Investment</a>', add)


class AlertsPresentInsightTests(InvTestCase):
    def test_first_when_there_are_alerts_and_never_works_them_out(self):
        with mock.patch("investments.services.alerts.peek_count", return_value=2) as peek, \
                mock.patch("investments.services.alerts.visible", side_effect=AssertionError("worked out")):
            items = insights.compute(self.profile)
        peek.assert_called()
        self.assertEqual(items[0]["text"], "Alerts Present")
        self.assertEqual(items[0]["url"], reverse("investments_alerts"))

    def test_absent_without_alerts_or_when_switched_off(self):
        with mock.patch("investments.services.alerts.peek_count", return_value=0):
            self.assertNotIn("Alerts Present", [i["text"] for i in insights.compute(self.profile)])
        masters.update_settings(self.profile, self.user, insights_off=["alerts"])
        with mock.patch("investments.services.alerts.peek_count", return_value=3):
            self.assertNotIn("Alerts Present", [i["text"] for i in insights.compute(self.profile)])


class SellAllTests(InvTestCase):
    def test_units_have_no_trailing_zeros_and_at_most_four_decimals(self):
        from investments.views import _units_text

        self.assertEqual(_units_text(D("10.0000000000")), "10")
        self.assertEqual(_units_text(D("12.3450000")), "12.345")
        self.assertEqual(_units_text(D("1.234567")), "1.2345")       # rounded down: never more than is held
        self.assertEqual(_units_text(D(0)), "0")
