"""The "Held only" tick box: the helper, the query-string handling, the transaction forms, Performance, Charts and the Other reports."""
import re
from datetime import date as d
from decimal import Decimal as D

from django.test import RequestFactory
from django.urls import reverse

from investments import forms
from investments.services import holdings, masters, reports, transactions as tx
from investments.tests.base import InvTestCase
from investments.viewutil import held_only


class HeldOnlyTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        # Reliance is held, the fund was bought and sold out, and Tata Motors is in the system but never bought.
        self.tata = masters.create_instrument(self.profile, self.user, kind="share", name="Tata Motors", code="TATAMOTORS.NS")
        self.buy(d(2023, 1, 1), 10, 100)
        self.buy(d(2023, 1, 1), 5, 50, instrument=self.fund)
        self.sell(d(2023, 6, 1), 5, 60, instrument=self.fund)

    # -- helper and query string

    def test_helper_returns_only_held_ids(self):
        ids = holdings.held_instrument_ids(self.profile)
        self.assertEqual(ids, {self.reliance.pk})

    def test_helper_counts_a_purchase_awaiting_allotment(self):
        tx.add_transaction(self.profile, self.user, side="buy", instrument=self.tata, portfolio=self.portfolio, broker=self.zerodha, date=d(2023, 7, 1),
                           awaiting=True, amount=D(1000))
        self.assertIn(self.tata.pk, holdings.held_instrument_ids(self.profile))

    def test_query_string_marker_tells_unticked_from_not_sent(self):
        rf = RequestFactory()
        self.assertTrue(held_only(rf.get("/x/")))
        self.assertFalse(held_only(rf.get("/x/"), default=False))
        self.assertTrue(held_only(rf.get("/x/?hf=1&held=1")))
        self.assertFalse(held_only(rf.get("/x/?hf=1")))

    # -- transaction forms

    def form_html(self, name):
        r = self.client.get(reverse(name))
        self.assertEqual(r.status_code, 200)
        return r.content.decode()

    def test_options_carry_data_held(self):
        html = self.form_html("investments_txn_new_buy")
        self.assertRegex(html, rf'<option value="{self.reliance.pk}" data-held="1">')
        self.assertRegex(html, rf'<option value="{self.fund.pk}">')
        self.assertRegex(html, rf'<option value="{self.tata.pk}">')

    def box(self, html, field="instrument"):
        m = re.search(rf'<input type="checkbox" class="held-only-box" data-for="{field}"([^>]*)>', html)
        self.assertIsNotNone(m, "no Held only tick box")
        return "checked" in m.group(1)

    def test_sale_form_tucks_charges_and_note_under_a_fold(self):
        html = self.form_html("investments_txn_new_sell")
        self.assertIn('<details class="more-fields">', html)
        self.assertIn("Charges and note", html)

    def test_tick_box_defaults(self):
        self.assertTrue(self.box(self.form_html("investments_txn_new_buy")))
        self.assertTrue(self.box(self.form_html("investments_txn_new_sell")))
        self.assertTrue(self.box(self.form_html("investments_txn_opening")))
        self.assertTrue(self.box(self.form_html("investments_txn_transfer")))
        self.assertTrue(self.box(self.form_html("investments_txn_switch"), "from_instrument"))

    def test_sale_of_something_not_held_starts_unticked(self):
        r = self.client.get(reverse("investments_txn_new_sell") + f"?instrument={self.fund.pk}")
        self.assertFalse(self.box(r.content.decode()))

    def test_server_still_accepts_an_investment_that_is_not_held(self):
        form = forms.TransactionForm({"date": "2024-01-01", "instrument": str(self.tata.pk), "portfolio": str(self.portfolio.pk),
                                      "broker": str(self.zerodha.pk), "units": "1", "price": "10", "charges": "0"},
                                     profile=self.profile, mode="buy")
        self.assertTrue(form.is_valid(), form.errors)

    # -- Performance

    def perf(self, query=""):
        r = self.client.get(reverse("investments_performance") + "?period=custom&from=2023-01-01&to=2024-01-01" + query)
        self.assertEqual(r.status_code, 200)
        return r.content.decode()

    def test_performance_is_held_only_by_default_and_unticking_includes_sold_out(self):
        on = self.perf()
        self.assertIn("Reliance Industries", on)
        self.assertNotIn("Parag Parikh", on)
        self.assertRegex(on, r'name="held" value="1" checked')
        off = self.perf("&hf=1")
        self.assertIn("Parag Parikh", off)
        self.assertNotRegex(off, r'name="held" value="1" checked')
        self.assertIn("Reliance Industries", self.perf("&hf=1&held=1"))
        self.assertNotIn("Parag Parikh", self.perf("&hf=1&held=1"))

    # -- Charts

    def inv_select(self, html):
        m = re.search(r'<select name="inv"[^>]*>(.*?)</select>', html, re.S)
        self.assertIsNotNone(m, "no inv select")
        return m.group(1)

    def test_charts_list_is_held_only_by_default(self):
        url = reverse("investments_charts") + "?period=1"
        on = self.inv_select(self.client.get(url).content.decode())
        self.assertIn(f'<option value="{self.reliance.pk}"', on)
        self.assertNotIn(f'<option value="{self.fund.pk}"', on)
        off = self.inv_select(self.client.get(url + "&hf=1").content.decode())
        self.assertIn(f'<option value="{self.fund.pk}"', off)

    def test_dividends_and_data_check_are_held_only_by_default_too(self):
        for slug in ("dividends", "data-check"):
            html = self.client.get(reverse("investments_report", args=[slug])).content.decode()
            self.assertRegex(html, r'name="held" value="1" checked')
            self.assertNotRegex(self.client.get(reverse("investments_report", args=[slug]) + "?hf=1").content.decode(),
                                r'name="held" value="1" checked')

    def test_charts_keep_a_picked_investment_visible(self):
        r = self.client.get(reverse("investments_charts") + f"?chart=b&period=1&inv={self.fund.pk}")
        self.assertIn(f'<option value="{self.fund.pk}" selected>', r.content.decode())

    # -- Other reports

    def test_reports_with_held_only(self):
        rows_on = reports.scoreboard(self.profile, years=3, held_only=True).rows
        rows_off = reports.scoreboard(self.profile, years=3, held_only=False).rows
        self.assertFalse(any("Parag Parikh" in str(r[0]) for r in rows_on))
        self.assertTrue(len(rows_off) >= len(rows_on))

    def test_report_page_shows_the_tick_box_only_where_it_applies(self):
        self.assertContains(self.client.get(reverse("investments_report", args=["scoreboard"])), 'name="held" value="1" checked')
        self.assertNotContains(self.client.get(reverse("investments_report", args=["yearly"])), 'name="held"')
        self.assertNotContains(self.client.get(reverse("investments_report", args=["scoreboard"]) + "?hf=1"), 'name="held" value="1" checked')
