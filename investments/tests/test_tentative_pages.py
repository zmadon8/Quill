"""Tentative entries on the Transactions page: tag, dashes, filter, export, the To complete page; plus the data conventions around them."""
import io
import re
from datetime import date as d
from decimal import Decimal as D

from django.urls import reverse
from openpyxl import load_workbook

from investments.models import Transaction
from investments.services import core, transactions as tx
from investments.tests.base import InvTestCase


class TentativePagesTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.final = self.buy(d(2024, 1, 1), 10, 100)
        self.tent = tx.add_transaction(self.profile, self.user, side="buy", instrument=self.fund, portfolio=self.portfolio, broker=self.zerodha,
                                       date=d(2024, 2, 1), tentative=True)
        self.priced = tx.add_transaction(self.profile, self.user, side="buy", instrument=self.fund, portfolio=self.portfolio, broker=self.zerodha,
                                         date=d(2024, 2, 2), tentative=True, amount=D(700))
        self.url = reverse("investments_transactions")

    def test_a_tentative_row_has_the_tag_beside_the_action_the_class_and_dashes(self):
        html = self.client.get(self.url).content.decode()
        row = html[html.index(f'id="txn-{self.tent.pk}"'):]
        row = row[:row.index("</tr>")]
        self.assertIn('class="hi tn"', row)
        self.assertIn('<td>Buy<span class="tag amb">Tentative</span></td>', row)
        self.assertGreaterEqual(row.count("&mdash;"), 3)          # units, price, amount
        self.assertIn(reverse("investments_txn_edit", args=[self.tent.pk]), row)
        self.assertIn(">Finalise</a>", row)
        final_row = html[html.index(f'id="txn-{self.final.pk}"'):]
        final_row = final_row[:final_row.index("</tr>")]
        self.assertNotIn("Tentative", final_row)
        self.assertNotIn("Finalise", final_row)

    def test_finalise_goes_to_the_complete_page_only_when_there_is_an_amount(self):
        html = self.client.get(self.url).content.decode()
        priced = html[html.index(f'id="txn-{self.priced.pk}"'):]
        self.assertIn(reverse("investments_txn_complete", args=[self.priced.pk]), priced[:priced.index("</tr>")])
        plain = html[html.index(f'id="txn-{self.tent.pk}"'):]
        self.assertNotIn(reverse("investments_txn_complete", args=[self.tent.pk]), plain[:plain.index("</tr>")])
        r = self.client.get(reverse("investments_txn_complete", args=[self.tent.pk]))
        self.assertRedirects(r, reverse("investments_txn_edit", args=[self.tent.pk]), fetch_redirect_response=False)

    def test_the_more_menu_no_longer_has_awaiting_allotment(self):
        html = self.client.get(self.url).content.decode()
        self.assertNotIn("Awaiting allotment", html)
        self.assertNotIn("transactions/awaiting/", html)

    def test_the_tentative_tick_box_filters_and_is_kept_in_the_links(self):
        html = self.client.get(self.url + "?tentative=1").content.decode()
        self.assertIn(f'id="txn-{self.tent.pk}"', html)
        self.assertIn(f'id="txn-{self.priced.pk}"', html)
        self.assertNotIn(f'id="txn-{self.final.pk}"', html)
        self.assertIn("checked", re.search(r'<input[^>]*name="tentative"[^>]*>', html).group(0))
        self.assertIn("tentative=1", html[html.index("Export to Excel") - 120:html.index("Export to Excel")])
        self.assertNotIn(f'id="txn-{self.tent.pk}"', self.client.get(self.url + "?side=sell").content.decode())

    def test_without_the_tick_everything_shows(self):
        html = self.client.get(self.url).content.decode()
        for t in (self.final, self.tent, self.priced):
            self.assertIn(f'id="txn-{t.pk}"', html)

    def test_the_selector_posts_the_tick_back_into_the_query(self):
        r = self.client.post(reverse("investments_set_selection"), {"txn_filters": "1", "tentative": "1", "next": self.url})
        self.assertIn("tentative=1", r["Location"])
        r = self.client.post(reverse("investments_set_selection"), {"txn_filters": "1", "next": self.url + "?tentative=1"})
        self.assertNotIn("tentative", r["Location"])

    def test_export_with_the_filter_has_only_tentative_transactions_and_no_other_sheets(self):
        r = self.client.get(self.url + "?export=xlsx&tentative=1")
        book = load_workbook(io.BytesIO(b"".join(r.streaming_content)))
        self.assertEqual(book.sheetnames, ["Transactions"])
        rows = list(book["Transactions"].iter_rows(min_row=2, values_only=True))
        header = [c.value for c in book["Transactions"][1]]
        self.assertEqual(len(rows), 2)
        self.assertEqual({r[header.index("Status")] for r in rows}, {"Tentative"})

    def test_the_to_complete_page_lists_them_with_finalise(self):
        html = self.client.get(reverse("investments_txn_to_confirm")).content.decode()
        self.assertIn("Tentative (buy)", html)
        self.assertIn("Finalise", html)
        self.assertNotIn("Awaiting", html)

    def test_the_investment_page_and_holdings_say_tentative(self):
        html = self.client.get(reverse("investments_investment", args=[self.fund.pk])).content.decode()
        self.assertIn("Tentative", html)
        self.assertNotIn("Awaiting", html)
        self.assertIn("Tentative", self.client.get(reverse("investments_holdings")).content.decode())

    def test_the_settings_label_says_tentative(self):
        html = self.client.get(reverse("investments_settings")).content.decode()
        self.assertIn("Tentative purchases", html)
        self.assertIn("Leave out until finalised", html)
        self.assertNotIn("Awaiting allotment", html)


class TentativeCostTests(InvTestCase):
    def make(self, **kw):
        return Transaction(side="buy", status="tentative", charges=D(0), **kw)

    def test_cost_is_the_amount_else_units_times_price_plus_charges_else_nothing(self):
        self.assertEqual(core.tentative_cost(self.make(amount=D(500), units=D(2), price=D(10))), D(500))
        self.assertEqual(core.tentative_cost(self.make(units=D(2), price=D(10), charges=D(3))), D(23))
        self.assertIsNone(core.tentative_cost(self.make(units=D(2))))
        self.assertIsNone(core.tentative_cost(self.make(price=D(10))))
        self.assertIsNone(core.tentative_cost(self.make()))

    def test_status_and_labels(self):
        from investments import models

        self.assertEqual(models.STATUS_TENTATIVE, "tentative")
        self.assertEqual(dict(models.STATUSES)["tentative"], "Tentative")
