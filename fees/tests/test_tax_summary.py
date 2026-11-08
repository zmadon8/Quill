"""Tax Summary text file tests (T5.4, R-EX-4)."""

from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.exports import tax_summary
from fees.services.statistics import get_year_end_summary
from fees.tests import xlsx_support as xs

RUPEE = "\u20b9"


class TaxSummaryLinesTests(SimpleTestCase):
    SUMMARY = {
        "financial_year": "2026-27",
        "memo_count": 12,
        "total_billed": Decimal("1234567.40"),
        "total_received": Decimal("99999.50"),
        "total_tds": Decimal("0"),
        "total_written_off": Decimal("0"),
        "new_matters": 3,
        "active_firms": 2,
        "num_appearances": 7,
        "appearances_per_week": Decimal("2.50"),
    }

    def test_lines_in_order_with_indian_grouping(self):
        lines = tax_summary.tax_summary_lines(self.SUMMARY)
        self.assertEqual(
            lines,
            [
                "Tax Summary - 2026-27",
                "",
                "Appearances: 7",
                "Appearances / Week: 2.5",
                "Memos: 12",
                "New Matters: 3",
                "Firms Billed: 2",
                f"Billed: {RUPEE} 12,34,567",
                f"Received: {RUPEE} 1,00,000",
                f"TDS: {RUPEE} 0",
            ],
        )

    def test_whole_and_zero_per_week(self):
        for value, expected in ((Decimal("3.00"), "3"), (Decimal("0.00"), "0"), (Decimal("0.05"), "0.05")):
            summary = dict(self.SUMMARY, appearances_per_week=value)
            self.assertIn(f"Appearances / Week: {expected}", tax_summary.tax_summary_lines(summary))

    def test_no_em_dash_in_output(self):
        self.assertNotIn("\u2014", "\n".join(tax_summary.tax_summary_lines(self.SUMMARY)))


class TaxSummaryExportTests(TestCase):
    def setUp(self):
        self.profile = Profile.objects.create(program=KEY_FEES, name="Tax-Fees")
        xs.seed_web_data(self.profile)

    def test_text_matches_the_year_end_summary(self):
        text = tax_summary.tax_summary_text(self.profile, "2026-27")
        summary = get_year_end_summary(self.profile, "2026-27")
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(text.splitlines()[0], "Tax Summary - 2026-27")
        self.assertEqual(text.splitlines()[1], "")
        self.assertIn(f"Memos: {summary['memo_count']}", text)
        self.assertIn(f"Billed: {RUPEE} 14,777", text)
        self.assertEqual(len(text.splitlines()), 10)

    def test_file_is_utf8_temp_file_with_name(self):
        name, fileobj = tax_summary.export_tax_summary(self.profile, "2026-27")
        with fileobj:
            self.assertEqual(fileobj.tell(), 0)
            data = fileobj.read()
        self.assertEqual(name, "Tax Summary 2026-27.txt")
        self.assertIn(RUPEE.encode("utf-8"), data)
        self.assertEqual(data.decode("utf-8"), tax_summary.tax_summary_text(self.profile, "2026-27"))

    def test_year_with_no_data_is_all_zero(self):
        text = tax_summary.tax_summary_text(self.profile, "1999-00")
        self.assertIn("Memos: 0", text)
        self.assertIn(f"Billed: {RUPEE} 0", text)
