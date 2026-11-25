"""A Lump Sum shows money only: no Units or price per unit anywhere, an Amount and a Value after on its records (docs/DESIGN.md D192)."""
from datetime import date as d
from decimal import Decimal as D

from django.urls import reverse

from investments import exports, lump_display
from investments.models import Transaction
from investments.services import history, holdings_page, masters
from investments.tests.base import InvTestCase


class LumpDisplayTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.chit = masters.create_instrument(self.profile, self.user, kind="alternative", name="Chit fund", asset_class="debt", lump_sum=True)
        self.plain = masters.create_instrument(self.profile, self.user, kind="alternative", name="Gold coin", asset_class="gold")
        card = {"portfolio": self.portfolio.pk, "broker": self.zerodha.pk, "charges": "0"}
        self.client.post(reverse("investments_txn_new_buy"), {**card, "date": "2024-01-01", "instrument": self.chit.pk, "lump_amount": "100"})
        self.client.post(reverse("investments_txn_new_sell"), {**card, "date": "2024-03-01", "instrument": self.chit.pk, "lump_amount": "20",
                                                                "remaining": "90"})
        self.buy(d(2024, 1, 1), "10", "50", instrument=self.plain)
        self.buy(d(2024, 1, 1), "5", "100")
        self.buy(d(2024, 1, 1), "5", "10", instrument=self.fund)

    def test_lump_sum_investment_page_has_no_unit_columns(self):
        html = self.client.get(reverse("investments_investment", args=[self.chit.pk])).content.decode()
        for head in ("<th class=\"r\">Units</th>", "<th class=\"r\">Price</th>", "<th class=\"r\">Charges</th>", "Units held"):
            self.assertNotIn(head, html)
        self.assertIn("Amount invested", html)
        self.assertIn("Value after", html)

    def test_other_investments_keep_their_unit_columns(self):
        for inst in (self.plain, self.reliance, self.fund):
            html = self.client.get(reverse("investments_investment", args=[inst.pk])).content.decode()
            self.assertIn('<th class="r">Units</th>', html, inst.name)
            self.assertNotIn("Value after", html)

    def test_records_have_amount_and_value_after(self):
        rows = lump_display.annotate(self.profile, list(Transaction.objects.filter(instrument=self.chit).select_related("instrument").order_by("date")))
        self.assertEqual([r.lump_amount for r in rows], [D("100.00"), D("20.00")])
        self.assertEqual(rows[1].value_after, D("90"))
        plain = lump_display.annotate(self.profile, list(Transaction.objects.filter(instrument=self.plain).select_related("instrument")))
        self.assertEqual((plain[0].lump_amount, plain[0].value_after), (None, None))

    def test_value_after_falls_back_to_the_running_cost(self):
        self.client.post(reverse("investments_txn_new_buy"), {"portfolio": self.portfolio.pk, "broker": self.zerodha.pk, "charges": "0",
                                                              "date": "2024-05-01", "instrument": self.chit.pk, "lump_amount": "50"})
        from investments.models import AltValue
        AltValue.objects.filter(instrument=self.chit, date=d(2024, 1, 1)).delete()
        AltValue.objects.filter(instrument=self.chit, date=d(2024, 5, 1)).delete()
        rows = lump_display.annotate(self.profile, list(Transaction.objects.filter(instrument=self.chit).select_related("instrument").order_by("date")))
        self.assertEqual(rows[0].value_after, D("100"))
        self.assertEqual(rows[1].value_after, D("90"))   # the sale's own entry wins
        # The 20 sold leaves 90, so it sold 20 / (20 + 90) of the 100 units held: 18.1818 units, leaving a cost of 81.8182; plus the 50 bought.
        self.assertEqual(rows[2].value_after, D("81.8182") + D("50"))

    def test_transactions_list_has_value_after_and_no_lump_units(self):
        html = self.client.get(reverse("investments_transactions")).content.decode()
        self.assertIn('<th class="r">Value after</th>', html)
        self.assertEqual(html.count('<th class="r">Units</th>'), 1)

    def test_holdings_dash_and_cache_version(self):
        self.assertEqual(holdings_page.PAYLOAD_VERSION, 5)   # 5: CAGR, Index CAGR and CAGR Alpha
        self.assertEqual(self.client.get(reverse("investments_holdings")).status_code, 200)

    def test_history_describes_a_lump_sale_in_money(self):
        for kind in ("transaction",):
            self.assertIn(kind, history.TYPE_LABELS)
        html = self.client.get(reverse("investments_history")).content.decode()
        self.assertIn("Sold \u20b920.00 of Chit fund, leaving \u20b990.00", html)
        self.assertIn("Bought \u20b9100.00 of Chit fund", html)

    def test_investment_page_recent_changes_and_header_in_money(self):
        html = self.client.get(reverse("investments_investment", args=[self.chit.pk])).content.decode()
        self.assertIn("Sold \u20b920.00 of Chit fund, leaving \u20b990.00", html)
        self.assertIn("Bought \u20b9100.00 of Chit fund", html)
        self.assertNotIn("Sold 20.0000", html)
        self.assertNotIn('<div class="lab">Price</div>', html)
        self.assertNotIn('<div class="lab">Average cost</div>', html)
        self.assertIn("Amount held", html)

    def test_other_investment_pages_keep_units_and_price_figures(self):
        for inst in (self.plain, self.reliance, self.fund):
            html = self.client.get(reverse("investments_investment", args=[inst.pk])).content.decode()
            self.assertIn('<div class="lab">Price</div>', html, inst.name)
            self.assertIn('<div class="lab">Units</div>', html, inst.name)

    def test_home_recent_activity_describes_a_lump_sale_in_money(self):
        from accounts import home_cards

        what = [r["what"] for r in home_cards._investments_recent(self.profile)]
        self.assertIn("Sold \u20b920.00 of Chit fund, leaving \u20b990.00", what)

    def test_exports_leave_units_and_price_blank_for_a_lump_sum(self):
        t = Transaction.objects.filter(instrument=self.chit).select_related("instrument", "portfolio", "broker", "folio").first()
        line = dict(zip(exports.TXN_HEADER, exports._txn_line(t)))
        self.assertEqual((line["Units"], line["Price"], line["Charges"]), (None, None, None))
        rows = holdings_page.load(self.profile)[0]
        sheet = exports.holdings_sheet(rows)[0][2]
        mine = next(r for r in sheet if r[0] == "Chit fund")
        self.assertIsNone(mine[exports.HOLDINGS_HEADER.index("Units")])
