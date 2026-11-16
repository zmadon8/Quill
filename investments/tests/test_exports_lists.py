"""Excel exports of the transaction history (all, per investment) and of the holdings list."""
import io
from datetime import date as d
from decimal import Decimal as D
from types import SimpleNamespace

from django.test import SimpleTestCase
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


class HoldingsSheetColumnTests(SimpleTestCase):
    """The Holdings sheet's Index XIRR and Alpha columns sit straight after XIRR and are written the way the XIRR column is."""

    def row(self, **over):
        inst = SimpleNamespace(name="Fund A", code="A1", isin="", lump_sum=False, get_kind_display=lambda: "Mutual fund")
        base = dict(instrument=inst, is_held=True, unpriced=False, blocked=False, empty=False, units=D("10"), avg_cost=D("100"),
                    cost=D("1000"), price=D("120"), price_date=d(2024, 1, 1), value=D("1200"), gain=D("200"), gain_pct=D("0.2"), xirr=D("0.15"),
                    index_xirr=D("0.11"), alpha=D("0.04"), first_date=d(2022, 1, 1), realised=D("0"), interest_income=D("0"), dividends=D("0"))
        return SimpleNamespace(**{**base, **over})

    def lines(self, *rows):
        from investments.exports import HOLDINGS_HEADER, holdings_sheet

        (_title, header, out), = holdings_sheet(rows)
        self.assertEqual(header, HOLDINGS_HEADER)
        return header, out

    def test_columns_follow_xirr_in_order(self):
        header, out = self.lines(self.row())
        at = header.index("XIRR % (a year)")
        self.assertEqual(header[at:at + 3], ["XIRR % (a year)", "Index XIRR %", "Alpha (XIRR \u2212 Index XIRR) %"])
        self.assertEqual(out[0][at:at + 3], [D("0.15"), D("0.11"), D("0.04")])
        self.assertEqual(len(out[0]), len(header))

    def test_not_available_and_blocked_rows_leave_the_cells_empty(self):
        header, out = self.lines(self.row(index_xirr=None, alpha=None), self.row(blocked=True))
        at = header.index("Index XIRR %")
        self.assertEqual(out[0][at - 1:at + 2], [D("0.15"), None, None])
        self.assertEqual(out[1][at - 1:at + 2], [None, None, None])

    def test_the_three_columns_are_written_alike(self):
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            self.skipTest("openpyxl is not installed in this environment; CI runs it")
        from openpyxl import load_workbook

        from investments.exports import holdings_sheet, workbook

        header, _out = self.lines(self.row())
        handle = workbook(holdings_sheet([self.row()]))
        ws = load_workbook(handle).active
        at = header.index("XIRR % (a year)")
        cells = [ws.cell(row=2, column=at + 1 + n) for n in range(3)]
        self.assertEqual([c.value for c in cells], [0.15, 0.11, 0.04])
        self.assertEqual(len({c.number_format for c in cells}), 1)
