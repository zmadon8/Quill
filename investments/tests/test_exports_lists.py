"""Excel exports of the transaction history (all, per investment) and of the holdings list."""
import io
from datetime import date as d

from django.urls import reverse

from investments.models import Transaction
from investments.services import masters
from investments.tests.base import InvTestCase


class ListExportTests(InvTestCase):
    def setUp(self):
        super().setUp()
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            self.skipTest("openpyxl is not installed in this environment; CI runs it")
        self.client.force_login(self.user)
        self.buy(d(2023, 1, 1), 10, 100)
        self.buy(d(2023, 2, 1), 5, 50, instrument=self.fund)
        self.sell(d(2023, 6, 1), 5, 60, instrument=self.fund)

    def sheet(self, response, name=None):
        from openpyxl import load_workbook

        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheetml", response["Content-Type"])
        wb = load_workbook(io.BytesIO(b"".join(response.streaming_content)))
        return wb, list(wb[name or wb.sheetnames[0]].iter_rows(values_only=True))

    def test_all_transactions(self):
        r = self.client.get(reverse("investments_transactions") + "?export=xlsx")
        self.assertIn("Transactions.xlsx", r["Content-Disposition"])
        wb, rows = self.sheet(r)
        self.assertEqual(wb.sheetnames, ["Transactions", "Transfers", "Dividends"])
        self.assertEqual(rows[0][:3], ("Date", "Allotment date", "Investment"))
        self.assertEqual(len(rows) - 1, Transaction.objects.filter(profile=self.profile).count())

    def test_all_transactions_honour_the_side_filter(self):
        r = self.client.get(reverse("investments_transactions") + "?export=xlsx&side=sell")
        _wb, rows = self.sheet(r)
        self.assertEqual(len(rows) - 1, 1)
        self.assertEqual(rows[1][6], "Sell")

    def test_one_investment_with_an_ampersand_in_its_name(self):
        inst = masters.create_instrument(self.profile, self.user, kind="share", name="Procter & Gamble", code="PG.NS")
        self.buy(d(2023, 3, 1), 3, 10, instrument=inst)
        r = self.client.get(reverse("investments_investment", args=[inst.pk]) + "?export=xlsx")
        self.assertIn("Procter", r["Content-Disposition"])
        self.assertNotIn("&", r["Content-Disposition"])
        _wb, rows = self.sheet(r)
        self.assertEqual(len(rows) - 1, 1)
        self.assertEqual(rows[1][2], "Procter & Gamble")

    def test_one_investment_has_all_its_rows_and_no_other(self):
        r = self.client.get(reverse("investments_investment", args=[self.fund.pk]) + "?export=xlsx")
        _wb, rows = self.sheet(r)
        self.assertEqual(len(rows) - 1, 2)
        self.assertEqual({row[2] for row in rows[1:]}, {self.fund.name})

    def test_holdings_export_honours_status(self):
        url = reverse("investments_holdings") + "?export=xlsx"
        r = self.client.get(url)
        self.assertIn("Holdings.xlsx", r["Content-Disposition"])
        _wb, rows = self.sheet(r)
        self.assertEqual(rows[0][:2], ("Name", "Type"))
        self.assertEqual([row[0] for row in rows[1:]], ["Reliance Industries"])
        _wb, rows = self.sheet(self.client.get(url + "&status=sold_out"))
        self.assertEqual([row[0] for row in rows[1:]], [self.fund.name])

    def test_buttons_are_on_the_pages(self):
        for url in (reverse("investments_holdings"), reverse("investments_transactions"), reverse("investments_investment", args=[self.reliance.pk])):
            self.assertContains(self.client.get(url), "Export to Excel")
