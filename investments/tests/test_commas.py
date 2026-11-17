"""Owner round (2026-12), D212: the Investments pages take numbers typed with commas, and number boxes are text boxes with an inputmode."""
import re
from datetime import date as d
from decimal import Decimal as D

from django.urls import reverse

from investments.models import Transaction
from investments.services import corporate
from investments.tests.base import InvTestCase


class CommaPostTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_a_buy_with_grouped_units_and_price(self):
        r = self.client.post(reverse("investments_txn_new_buy"), {
            "date": "2024-01-01", "instrument": self.reliance.pk, "portfolio": self.portfolio.pk, "broker": self.zerodha.pk,
            "units": "1,25,000", "price": "1,234.50", "charges": "1,000"})
        self.assertRedirects(r, reverse("investments_transactions"))
        row = Transaction.objects.get()
        self.assertEqual((row.units, row.price, row.charges), (D("125000"), D("1234.50"), D("1000")))

    def test_opening_balance_rows_with_commas(self):
        r = self.client.post(reverse("investments_txn_opening"), {
            "instrument": self.reliance.pk, "portfolio": self.portfolio.pk, "broker": self.zerodha.pk, "rows": "5",
            "date_0": "2019-05-01", "units_0": "1,00,000", "cost_0": "1,23,456.50",
            "date_1": "2020-05-01", "units_1": "\u20b95,000", "cost_1": "12 34"})
        self.assertRedirects(r, reverse("investments_transactions"))
        lots = {t.date: (t.units, t.price) for t in Transaction.objects.filter(is_opening=True)}
        self.assertEqual(lots[d(2019, 5, 1)], (D("100000"), D("123456.50")))
        self.assertEqual(lots[d(2020, 5, 1)], (D("5000"), D("1234")))

    def test_the_concentration_limit_with_commas(self):
        r = self.client.post(reverse("investments_settings_insights"), {"limit": "2,5"})
        self.assertEqual(r.status_code, 302)
        from investments.services import core

        self.assertEqual(core.get_settings(self.profile, create=False).concentration_limit, D("25"))

    def test_an_alert_level_with_commas(self):
        from investments.services import alerts

        state = alerts.act(self.profile, "k", "rearm", level="1,23,456.5")
        self.assertEqual(state.rearm_level, D("123456.5"))

    def test_a_demerger_override_with_commas(self):
        self.assertEqual(corporate._override_units("1,000", self.reliance), D("1000"))


class NumberBoxTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def inputs(self, html):
        return re.findall(r"<input[^>]*>", html)

    def test_no_investments_form_page_uses_type_number(self):
        for name in ("investments_txn_new_buy", "investments_txn_new_sell", "investments_txn_opening", "investments_settings",
                     "investments_settings_alerts"):
            html = self.client.get(reverse(name)).content.decode()
            self.assertNotIn('type="number"', html, name)

    def test_the_buy_form_number_boxes_are_text_with_an_inputmode(self):
        html = self.client.get(reverse("investments_txn_new_buy")).content.decode()
        for field in ("units", "price", "charges"):
            tag = next(t for t in self.inputs(html) if f'name="{field}"' in t)
            self.assertIn('type="text"', tag, field)
            self.assertIn('inputmode="decimal"', tag, field)
            self.assertNotIn("step=", tag, field)

    def test_the_opening_balance_boxes_have_an_inputmode(self):
        html = self.client.get(reverse("investments_txn_opening")).content.decode()
        for tag in self.inputs(html):
            if 'name="units_0"' in tag or 'name="cost_0"' in tag:
                self.assertIn('inputmode="decimal"', tag)
