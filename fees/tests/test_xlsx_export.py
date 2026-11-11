"""Excel export tests (T5.3, R-EX-3): exact headers, totals, number formats and file names.

Workbooks are produced by ``fees.exports.xlsx`` and read back with ``openpyxl`` in read-only mode. The data
comes from ``xlsx_support.seed_web_data`` (drafts, a custom total, a write-off, single, split and
unaccounted payments), so the figures are checked against known memo totals as well as the services.
"""

from django.test import TestCase

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.errors import FeesError
from fees.exports import xlsx
from fees.exports.filenames import content_disposition
from fees.services import memos
from fees.tests import xlsx_support as xs

EM_DASH = "\u2014"


def fees_profile(name="Xlsx-Fees"):
    return Profile.objects.create(program=KEY_FEES, name=name)


def open_cells(result):
    """``(file_name, {sheet: [[cell, ...], ...]})`` with real read-only cells (style visible)."""
    from openpyxl import load_workbook

    name, fileobj = result
    with fileobj:
        workbook = load_workbook(fileobj, read_only=True)
        try:
            out = {}
            for sheet in workbook.worksheets:
                sheet.reset_dimensions()
                out[sheet.title] = [list(row) for row in sheet.iter_rows()]
            return name, out
        finally:
            workbook.close()


def values(result):
    name, sheets = open_cells(result)
    return name, {t: [[c.value for c in row] for row in rows] for t, rows in sheets.items()}


class XlsxBase(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        self.seed = xs.seed_web_data(self.profile)


class MemosExportTests(XlsxBase):
    HEADERS = [
        "Memo Number", "Date", "Firm", "Matter Name", "Total Fees", "Net of TDS", "Amount Paid",
        "Date of Last Payment", "Status",
    ]

    def test_headers_rows_and_formats(self):
        name, sheets = open_cells(xlsx.export_memos(self.profile))
        self.assertEqual(name, "Memos All Years.xlsx")
        self.assertEqual(list(sheets), ["Memos"])
        rows = sheets["Memos"]
        self.assertEqual([c.value for c in rows[0]], self.HEADERS)
        self.assertTrue(all(c.font.b for c in rows[0]))
        # Three non-draft memos; the draft is not listed.
        self.assertEqual(len(rows), 4)
        by_number = {r[0].value: r for r in rows[1:]}
        memo_a = by_number[self.seed["memo_a"].memo_number]
        self.assertEqual(memo_a[1].value, "15.07.2026")
        self.assertEqual(memo_a[2].value, "Alpha & Co")
        self.assertEqual(memo_a[3].value, "Matter One")
        self.assertEqual(memo_a[4].value, 14000)
        self.assertEqual(memo_a[6].value, 9000 + 1000 + 2000)
        self.assertEqual(memo_a[7].value, "05.08.2026")
        for index in (4, 5, 6):
            self.assertEqual(memo_a[index].number_format, "#,##0")
        self.assertEqual(memo_a[8].value, "Unpaid")
        memo_b = by_number[self.seed["memo_b"].memo_number]
        self.assertEqual(memo_b[4].value, 777)
        memo_c = by_number[self.seed["memo_c"].memo_number]
        self.assertIn(memo_c[7].value, (None, ""))

    def test_no_totals_row(self):
        _name, sheets = values(xlsx.export_memos(self.profile))
        self.assertNotIn("TOTAL", [r[0] for r in sheets["Memos"]])

    def test_financial_year_in_file_name_and_filter(self):
        fy = self.seed["memo_a"].financial_year
        name, sheets = values(xlsx.export_memos(self.profile, {"financial_year": fy}))
        self.assertEqual(name, f"Memos {fy}.xlsx")
        self.assertEqual(len(sheets["Memos"]), 3)

    def test_zero_rows_is_export_failed(self):
        empty = fees_profile("Empty")
        with self.assertRaises(FeesError) as ctx:
            xlsx.export_memos(empty)
        self.assertEqual(ctx.exception.code, "EXPORT_FAILED")
        self.assertEqual(ctx.exception.status, 400)
        with self.assertRaises(FeesError):
            xlsx.export_memos(self.profile, {"financial_year": "1999-00"})

    def test_returns_rewound_temp_file(self):
        _name, fileobj = xlsx.export_memos(self.profile)
        with fileobj:
            self.assertEqual(fileobj.tell(), 0)
            self.assertEqual(fileobj.read(2), b"PK")

    def test_query_count_does_not_grow_with_rows(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as small:
            xlsx.export_memos(self.profile)[1].close()
        extra_firm = fees_profile("More")
        more = xs.seed_web_data(extra_firm)
        for i in range(15):
            memos.create_memo(extra_firm, xs.memo_input(more["matter_1"].pk, date="2026-09-%02d" % (i + 1)))
        with CaptureQueriesContext(connection) as large:
            xlsx.export_memos(extra_firm)[1].close()
        self.assertLessEqual(len(large), len(small) + 2)


class StatementLedgerTests(XlsxBase):
    def test_statement_columns_totals_and_status(self):
        name, sheets = open_cells(xlsx.export_statement(self.profile))
        self.assertEqual(name, "Statement.xlsx")
        rows = sheets["Statement"]
        self.assertEqual(
            [c.value for c in rows[0]],
            ["Date", "Particulars", "Matter Name", "Memo Amount", "Payment Amount", "TDS", "Balance Payable"],
        )
        _n, ledger_sheets = open_cells(xlsx.export_ledger(self.profile))
        self.assertEqual(
            [[c.value for c in r] for r in rows],
            [[c.value for c in r] for r in ledger_sheets["Ledger"]],
        )
        self.assertEqual(rows[1][6].number_format, "#,##0")

    def test_statement_named_by_scope(self):
        name, sheets = values(xlsx.export_statement(self.profile, {"matter_id": self.seed["matter_1"].pk}))
        self.assertEqual(name, "Statement - Matter One.xlsx")
        ledger = values(xlsx.export_ledger(self.profile, {"matter_id": self.seed["matter_1"].pk}))[1]
        self.assertEqual(sheets["Statement"], ledger["Ledger"])

    def test_ledger_columns_and_balance(self):
        name, sheets = open_cells(xlsx.export_ledger(self.profile))
        self.assertEqual(name, "Ledger.xlsx")
        rows = sheets["Ledger"]
        self.assertEqual(
            [c.value for c in rows[0]],
            ["Date", "Particulars", "Matter Name", "Memo Amount", "Payment Amount", "TDS", "Balance Payable"],
        )
        self.assertNotIn("TOTAL", [r[0].value for r in rows])
        memo_row = next(r for r in rows[1:] if r[3].value not in (None, ""))
        self.assertIn(memo_row[4].value, (None, ""))
        self.assertTrue(memo_row[1].value.startswith("Memo "))
        self.assertEqual(memo_row[6].number_format, "#,##0")
        payment_row = next(r for r in rows[1:] if r[4].value not in (None, ""))
        self.assertIn(payment_row[3].value, (None, ""))

    def test_ledger_scope_name(self):
        name, _sheets = values(xlsx.export_ledger(self.profile, {"matter_id": self.seed["matter_1"].pk}))
        self.assertEqual(name, "Ledger - Matter One.xlsx")


class FeebookTests(XlsxBase):
    ALL = ["Date", "Memo No.", "Matter Name", "Payee", "Paid", "TDS", "Paid + TDS", "Bank", "Mode", "Type"]

    def test_all_columns_and_rows(self):
        name, sheets = open_cells(xlsx.export_feebook(self.profile))
        self.assertEqual(name, "Feebook All Years.xlsx")
        rows = sheets["Feebook"]
        self.assertEqual([c.value for c in rows[0]], self.ALL)
        # single payment (1) + split (2 allocations) + unaccounted (1)
        self.assertEqual(len(rows), 5)
        for index in (4, 5, 6):
            self.assertEqual(rows[1][index].number_format, "#,##0")
        types = {r[9].value for r in rows[1:]}
        self.assertEqual(types, {"Single", "Multiple"})
        unaccounted = next(r for r in rows[1:] if r[3].value == "Unknown payer")
        self.assertEqual(unaccounted[1].value, "Unaccounted")
        # Every other row carries a real memo number, never the word.
        others = [r[1].value for r in rows[1:] if r is not unaccounted]
        self.assertTrue(others)
        self.assertNotIn("Unaccounted", others)
        self.assertTrue(all(others))
        self.assertEqual(unaccounted[0].value, "09.08.2026")

    def test_visible_columns_keep_date_and_memo(self):
        _name, sheets = values(xlsx.export_feebook(self.profile, visible_keys=["paid", "bank"]))
        self.assertEqual(sheets["Feebook"][0], ["Date", "Memo No.", "Paid", "Bank"])
        _name, sheets = values(xlsx.export_feebook(self.profile, visible_keys=[]))
        self.assertEqual(sheets["Feebook"][0], ["Date", "Memo No."])

    def test_empty_feebook_still_exports(self):
        _name, sheets = values(xlsx.export_feebook(fees_profile("Nobody")))
        self.assertEqual(len(sheets["Feebook"]), 1)

    def test_financial_year_name(self):
        name, _sheets = values(xlsx.export_feebook(self.profile, {"financial_year": "2026-27"}))
        self.assertEqual(name, "Feebook 2026-27.xlsx")


class OutstandingTests(XlsxBase):
    ALL = [
        "Firm", "Group", "Date", "Memo Number", "Matter Name", "Total Memo Amount", "Net of TDS",
        "Already Paid", "Due",
    ]

    def test_all_columns_and_total_row(self):
        name, sheets = open_cells(xlsx.export_outstanding(self.profile))
        self.assertEqual(name, "All Outstanding Memos.xlsx")
        rows = sheets["Outstanding"]
        self.assertEqual([c.value for c in rows[0]], self.ALL)
        body, total = rows[1:-1], rows[-1]
        self.assertTrue(body)
        self.assertEqual(total[4].value, "TOTAL")
        self.assertTrue(all(c.font.b for c in total))
        for index, label in ((5, "total"), (6, "net"), (7, "paid"), (8, "due")):
            self.assertEqual(total[index].value, sum(r[index].value for r in body), label)
            self.assertEqual(total[index].number_format, "#,##0")
        self.assertEqual(body[0][2].value[2], ".")

    def test_visible_columns_and_total_label_position(self):
        _n, sheets = values(xlsx.export_outstanding(self.profile, visible_keys=["firm", "paid"]))
        rows = sheets["Outstanding"]
        self.assertEqual(rows[0], ["Firm", "Date", "Memo Number", "Already Paid", "Due"])
        self.assertEqual(rows[-1][2], "TOTAL")
        _n, sheets = values(xlsx.export_outstanding(self.profile, visible_keys=["matter"]))
        self.assertEqual(sheets["Outstanding"][0], ["Date", "Memo Number", "Matter Name", "Due"])
        self.assertEqual(sheets["Outstanding"][-1][2], "TOTAL")

    def test_custom_file_name(self):
        name, _s = values(xlsx.export_outstanding(self.profile, file_name="Outstanding - Alpha"))
        self.assertEqual(name, "Outstanding - Alpha.xlsx")
        name, _s = values(xlsx.export_outstanding(self.profile, file_name="  "))
        self.assertEqual(name, "All Outstanding Memos.xlsx")

    def test_by_firm(self):
        name, sheets = open_cells(xlsx.export_outstanding_by_firm(self.profile))
        self.assertEqual(name, "Outstanding " + EM_DASH + " Firm Summary.xlsx")
        self.assertEqual(name, xlsx.OUTSTANDING_FIRM_SUMMARY_FILENAME)
        rows = sheets["Outstanding by Firm"]
        self.assertEqual([c.value for c in rows[0]], ["Firm", "Memos Outstanding", "Outstanding"])
        body, total = rows[1:-1], rows[-1]
        self.assertEqual(total[0].value, "TOTAL")
        self.assertEqual(total[2].value, sum(r[2].value for r in body))
        self.assertTrue(all(c.font.b for c in total))
        self.assertEqual(body[0][2].number_format, "#,##0")

    def test_em_dash_file_name_header_is_rfc5987(self):
        header = content_disposition(xlsx.OUTSTANDING_FIRM_SUMMARY_FILENAME)
        self.assertIn("filename*=UTF-8''Outstanding%20%E2%80%94%20Firm%20Summary.xlsx", header)
        self.assertTrue(header.isascii())


class StatisticsTests(XlsxBase):
    LABELS = [
        "Appearances", "Conferences", "Drafts", "Amount Billed", "Amount Recovered", "% Recovered",
        "Amount Received", "Received + TDS", "Fees / Day", "Appearances / Week", "Conferences / Week",
        "Drafts / Week", "Fees / Week",
    ]

    def test_month_table(self):
        name, sheets = open_cells(xlsx.export_statistics(self.profile, "month", "2026-27"))
        self.assertEqual(name, "Statistics 2026-27.xlsx")
        rows = sheets["Statistics"]
        self.assertEqual(rows[0][0].value, "Metric")
        self.assertEqual(len(rows[0]), 13)
        self.assertEqual([r[0].value for r in rows[1:]], self.LABELS)
        self.assertTrue(all(c.font.b for c in rows[0]))
        billed = rows[4]
        self.assertEqual(billed[1].number_format, "#,##0")
        self.assertNotEqual(rows[1][1].number_format, "#,##0")

    def test_financial_year_table_name(self):
        name, sheets = values(xlsx.export_statistics(self.profile, "financialYear"))
        self.assertEqual(name, "Statistics.xlsx")
        self.assertIn("2026-27", sheets["Statistics"][0])

    def test_annual_summary_sheets(self):
        name, sheets = open_cells(xlsx.export_annual_summary(self.profile, "2026-27"))
        self.assertEqual(name, "Annual Summary 2026-27.xlsx")
        self.assertEqual(
            list(sheets),
            ["Annual", "Annual Stats", "Quarter-wise", "Month-wise", "Details by Firm", "Details by Matter"],
        )
        annual = [r for r in sheets["Annual"] if r and r[0].value is not None]
        self.assertEqual(annual[0][0].value, "Annual Summary - 2026-27")
        self.assertTrue(annual[0][0].font.b)
        labels = [r[0].value for r in annual[1:9]]
        self.assertEqual(
            labels,
            ["Appearances", "Appearances / Week", "Memos", "New Matters", "Firms Billed", "Billed",
             "Received", "TDS"],
        )
        billed = annual[6]
        self.assertEqual(billed[1].value, 14000 + 777)
        self.assertEqual(billed[1].number_format, "#,##0")
        self.assertEqual(len(sheets["Quarter-wise"][0]), 5)
        self.assertEqual(len(sheets["Month-wise"][0]), 13)
        firm = sheets["Details by Firm"]
        self.assertEqual(
            [c.value for c in firm[0]],
            ["Firm", "Memos", "Appearances", "Conferences", "Drafts", "Billed", "Received", "TDS"],
        )
        self.assertEqual(firm[-1][0].value, "TOTAL")
        self.assertTrue(all(c.font.b for c in firm[-1]))
        self.assertEqual(firm[-1][1].value, sum(r[1].value for r in firm[1:-1]))
        matter = sheets["Details by Matter"]
        self.assertEqual([c.value for c in matter[0]][:3], ["Matter", "Firm", "Memos"])
        self.assertEqual(matter[-1][0].value, "TOTAL")


class SafetyTests(TestCase):
    def test_text_is_never_a_formula_and_control_chars_are_removed(self):
        from fees.models import Firm, Group, Matter

        profile = fees_profile("Safe")
        firm = Firm.objects.create(profile=profile, name="=HYPERLINK(1)")
        group = Group.objects.create(profile=profile, firm=firm, name="G")
        matter = Matter.objects.create(profile=profile, firm=firm, group=group, name="M\x01atter")
        memos.create_memo(profile, xs.memo_input(matter.pk))
        _name, sheets = open_cells(xlsx.export_memos(profile))
        row = sheets["Memos"][1]
        self.assertEqual(row[2].value, "=HYPERLINK(1)")
        self.assertEqual(row[2].data_type, "s")
        self.assertEqual(row[3].value, "Matter")

    def test_select_columns(self):
        picked = xlsx.select_columns(xlsx.FEEBOOK_COLUMNS, xlsx.FEEBOOK_ALWAYS, ["type"])
        self.assertEqual([c[0] for c in picked], ["date", "memo", "type"])
        self.assertEqual(len(xlsx.select_columns(xlsx.FEEBOOK_COLUMNS, xlsx.FEEBOOK_ALWAYS, None)), 10)
