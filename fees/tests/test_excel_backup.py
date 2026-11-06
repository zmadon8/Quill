"""Excel backup export tests (T4.1, T4.5, R-BK-1, design 7.1).

The contract test keeps its OWN copy of the desktop ``TABLES`` and settings catalogue (copied from
``backupService.ts`` and ``settingsColumns.ts``), so a change to the export columns in
``fees.services.excel_backup`` cannot silently change the contract. The tests read the exported file
back with ``openpyxl`` and assert sheet order, header rows, vestigial NOT NULL columns, timestamps,
number and date formats, ``payments.memo_id``, the ``WebSettings`` sheet (five memo text defaults), and
that the signature image and Word template bytes are absent from the ``.xlsx`` while
``payment_details`` is present.
"""
import re
import zipfile

from django.test import TestCase, tag
from django.db import connection
from django.test.utils import CaptureQueriesContext

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.models import FeesSettings, Firm, Matter, Memo, Payment
from fees.services.excel_backup import export_workbook
from fees.tests.datasets import build_planning_dataset
from fees.tests.memory import assert_peak_under
from fees.tests.xlsx_support import (
    MEMO_TEXT_DEFAULTS,
    PAYMENT_DETAILS_SENTINEL,
    read_workbook,
    rows_as_dicts,
    seed_web_data,
)

# ---------------------------------------------------------------------------
# The desktop contract: this test's OWN copy of backupService.ts TABLES (do not import it).
# ---------------------------------------------------------------------------
DESKTOP_SETTINGS_COLUMNS = [
    "default_fees_per_appearance", "default_fees_per_conference", "default_fees_misc_drafting",
    "default_additional_details_left", "default_additional_details_right", "default_court_name",
    "default_tds_rate", "overdue_days", "default_tab", "auto_backup_frequency", "auto_backup_dir",
    "last_auto_backup", "word_template_path", "initial_financial_year", "memos_start_year",
    "feebook_start_year", "money_unit", "money_suffix_thousands", "money_suffix_lac",
    "money_suffix_crore", "hide_payment_when_paid", "default_lines_enabled", "default_payment_amount",
    "show_status_dots", "zoom_factor", "dashboard_kpis", "backup_close_enabled", "backup_close_dir",
    "backup_daily_enabled", "backup_daily_dir", "last_backup_daily", "backup_weekly_enabled",
    "backup_weekly_dir", "last_backup_weekly", "backup_monthly_enabled", "backup_monthly_dir",
    "last_backup_monthly", "backup_retention", "backup_migrated",
]
DESKTOP_TABLES = [
    ("Firms", ["id", "name", "status", "notes", "created_at", "updated_at"]),
    ("Partners", ["id", "firm_id", "name", "created_at"]),
    ("Matters", [
        "id", "firm_id", "partner_id", "name", "is_archived", "is_custom",
        "addressee_line1", "addressee_line2", "addressee_use_firm_name", "court_name", "client",
        "additional_details_left", "additional_details_right", "plaintiff_name", "plaintiff_type",
        "defendant_name", "defendant_type", "notes", "short_name", "created_at", "updated_at",
    ]),
    ("BankAccounts", ["id", "name", "created_at"]),
    ("Memos", [
        "id", "memo_number", "financial_year", "seq", "date", "matter_id", "firm_id", "partner_id",
        "addressee_line1", "addressee_line2", "court_name", "additional_details_left",
        "additional_details_right", "plaintiff_name", "plaintiff_type", "defendant_name",
        "defendant_type", "client", "num_appearances", "dates_of_appearances", "fees_per_appearance",
        "num_conferences", "dates_of_conferences", "fees_per_conference", "misc_drafting_description",
        "fees_misc_drafting", "num_drafts", "tds_rate", "written_off", "is_draft",
        "custom_fees_appearances", "custom_fees_conferences", "custom_fees_misc", "custom_total_fees",
        "created_at", "updated_at",
    ]),
    ("Payments", [
        "id", "memo_id", "amount", "tds_rate", "auto_tds", "tds_amount", "memo_amount",
        "date_of_payment", "payee", "bank_account_id", "payment_details", "payment_mode",
        "created_at", "updated_at",
    ]),
    ("PaymentAllocations", ["id", "payment_id", "memo_id", "amount", "tds_amount", "created_at"]),
    ("PeriodAdjustments", [
        "id", "financial_year", "month", "working_days", "extra_appearances", "extra_conferences",
        "extra_drafts", "ov_appearances", "ov_conferences", "ov_drafts", "ov_billed", "ov_received",
        "ov_received_plus_tds", "updated_at",
    ]),
    ("SavedViews", [
        "id", "name", "measure", "row_dim", "col_dim", "firm_id", "from_fy", "to_fy", "created_at",
    ]),
    ("Settings", ["id"] + DESKTOP_SETTINGS_COLUMNS + ["updated_at"]),
]
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONEY_COLUMNS = {
    "Memos": ["fees_per_appearance", "fees_per_conference", "fees_misc_drafting", "custom_total_fees"],
    "Payments": ["amount", "tds_rate", "tds_amount", "memo_amount"],
    "PaymentAllocations": ["amount", "tds_amount"],
}


def fees_profile(name="Ziyad-Backup"):
    return Profile.objects.create(program=KEY_FEES, name=name)


def export_rows(profile):
    out = export_workbook(profile)
    try:
        return read_workbook(out)
    finally:
        out.close()


class ExportContractTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.profile = fees_profile()
        cls.objs = seed_web_data(cls.profile)
        cls.book = export_rows(cls.profile)
        cls.sheets = {name: rows_as_dicts(rows) for name, rows in cls.book.items()}

    def test_sheet_names_and_order(self):
        self.assertEqual(
            list(self.book.keys()), [sheet for sheet, _cols in DESKTOP_TABLES] + ["WebSettings", "WebMemoFlags"]
        )

    def test_header_rows_equal_the_desktop_columns(self):
        for sheet, columns in DESKTOP_TABLES:
            with self.subTest(sheet=sheet):
                self.assertEqual(self.book[sheet][0], columns)

    def test_settings_row_has_electron_only_defaults_and_model_values(self):
        rows = self.sheets["Settings"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["id"], 1)
        self.assertEqual(row["backup_migrated"], 1)
        self.assertEqual(row["zoom_factor"], 1)
        self.assertEqual(row["backup_retention"], 30)
        self.assertEqual(row["auto_backup_frequency"], "off")
        for name in ("backup_close_enabled", "backup_daily_enabled", "backup_weekly_enabled",
                     "backup_monthly_enabled"):
            self.assertEqual(row[name], 0)
        for name in ("auto_backup_dir", "last_auto_backup", "word_template_path", "backup_close_dir",
                     "last_backup_daily", "last_backup_weekly", "last_backup_monthly"):
            self.assertIn(row[name], (None, ""))
        # Live settings come from the model.
        self.assertEqual(row["default_tds_rate"], 12.5)
        self.assertEqual(row["overdue_days"], 45)
        self.assertEqual(row["default_tab"], "firms")
        self.assertEqual(row["default_fees_per_appearance"], 1500)
        self.assertEqual(row["hide_payment_when_paid"], 1)
        self.assertEqual(row["show_status_dots"], 0)
        self.assertEqual(row["dashboard_kpis"], "a,b")
        self.assertRegex(row["updated_at"], TIMESTAMP_RE)

    def test_vestigial_not_null_columns_are_zero_and_never_blank(self):
        for row in self.sheets["Matters"]:
            self.assertEqual(row["is_custom"], 0)
        for row in self.sheets["Memos"]:
            self.assertEqual(row["tds_rate"], 0)
        for row in self.sheets["Payments"]:
            self.assertEqual(row["memo_amount"], 0)

    def test_payment_tds_rate_is_the_real_rate(self):
        rates = {row["payee"]: row["tds_rate"] for row in self.sheets["Payments"]}
        self.assertEqual(rates["Alpha payer"], 10)
        self.assertEqual(rates["Split payer"], 0)

    def test_timestamps_are_never_empty_and_formatted(self):
        for sheet, columns in DESKTOP_TABLES:
            for name in ("created_at", "updated_at"):
                if name not in columns:
                    continue
                for row in self.sheets[sheet]:
                    with self.subTest(sheet=sheet, column=name):
                        self.assertRegex(str(row[name]), TIMESTAMP_RE)

    def test_booleans_dates_and_money_formats(self):
        for row in self.sheets["Memos"]:
            self.assertIn(row["written_off"], (0, 1))
            self.assertIn(row["is_draft"], (0, 1))
            if row["date"] is not None:
                self.assertRegex(row["date"], DATE_RE)
        for row in self.sheets["Matters"]:
            self.assertIn(row["is_archived"], (0, 1))
            self.assertIn(row["addressee_use_firm_name"], (0, 1))
        for row in self.sheets["Payments"]:
            self.assertIn(row["auto_tds"], (0, 1))
            self.assertRegex(row["date_of_payment"], DATE_RE)
        for sheet, columns in MONEY_COLUMNS.items():
            for row in self.sheets[sheet]:
                for name in columns:
                    value = row[name]
                    if value is None:
                        continue
                    with self.subTest(sheet=sheet, column=name):
                        self.assertIsInstance(value, (int, float))
                        self.assertEqual(round(value, 2), value)

    def test_custom_total_and_draft_rows(self):
        by_number = {row["memo_number"]: row for row in self.sheets["Memos"]}
        self.assertEqual(by_number[self.objs["memo_b"].memo_number]["custom_total_fees"], 777)
        draft = [row for row in self.sheets["Memos"] if row["is_draft"] == 1]
        self.assertEqual(len(draft), 1)
        self.assertIsNone(draft[0]["memo_number"])

    def test_foreign_keys_are_web_ids_consistent_within_the_file(self):
        ids = {
            sheet: {row["id"] for row in self.sheets[sheet]}
            for sheet in ("Firms", "Partners", "Matters", "Memos", "Payments")
        }
        self.assertEqual(
            ids["Firms"], set(Firm.objects.filter(profile=self.profile).values_list("pk", flat=True))
        )
        self.assertEqual(
            ids["Memos"], set(Memo.objects.filter(profile=self.profile).values_list("pk", flat=True))
        )
        for row in self.sheets["Partners"]:
            self.assertIn(row["firm_id"], ids["Firms"])
        for row in self.sheets["Matters"]:
            self.assertIn(row["firm_id"], ids["Firms"])
            self.assertIn(row["partner_id"], ids["Partners"])
        for row in self.sheets["Memos"]:
            self.assertIn(row["matter_id"], ids["Matters"])
            self.assertIn(row["firm_id"], ids["Firms"])
            self.assertIn(row["partner_id"], ids["Partners"])
        for row in self.sheets["PaymentAllocations"]:
            self.assertIn(row["payment_id"], ids["Payments"])
            self.assertIn(row["memo_id"], ids["Memos"])

    def test_payments_memo_id_only_for_single_allocation(self):
        by_payee = {row["payee"]: row for row in self.sheets["Payments"]}
        self.assertEqual(by_payee["Alpha payer"]["memo_id"], self.objs["memo_a"].pk)
        self.assertIsNone(by_payee["Split payer"]["memo_id"])
        self.assertIsNone(by_payee["Unknown payer"]["memo_id"])
        self.assertEqual(len(self.sheets["PaymentAllocations"]), 3)

    def test_payment_details_is_in_the_backup(self):
        details = [row["payment_details"] for row in self.sheets["Payments"]]
        self.assertIn(PAYMENT_DETAILS_SENTINEL, details)

    def test_web_settings_sheet_carries_web_only_keys_and_memo_text_defaults(self):
        rows = self.book["WebSettings"]
        self.assertEqual(rows[0], ["key", "value"])
        values = {row[0]: (row[1] if len(row) > 1 else None) for row in rows[1:]}
        self.assertEqual(
            list(values.keys()),
            ["export_owner_name", "memo_filename_pattern", "statistics_enabled",
             "dashboard_kpis_enabled", "memo_default_name", "memo_default_designation",
             "memo_default_address", "memo_default_bank_details", "memo_default_pan",
             "memo_signature_default", "list_default_filter"],
        )
        self.assertEqual(values["export_owner_name"], "Test Owner")
        self.assertEqual(values["memo_filename_pattern"], "pattern-x")
        self.assertEqual(values["statistics_enabled"], 0)
        self.assertEqual(values["dashboard_kpis_enabled"], 0)
        for key, expected in MEMO_TEXT_DEFAULTS.items():
            self.assertEqual(values[key], expected)  # multi-line values keep their line breaks

    def test_signature_and_template_bytes_are_not_in_the_xlsx(self):
        out = export_workbook(self.profile)
        try:
            with zipfile.ZipFile(out) as archive:
                names = archive.namelist()
                self.assertFalse([n for n in names if "media" in n or n.endswith(".png")])
                for name in names:
                    data = archive.read(name)
                    self.assertNotIn(b"FAKE-SIGNATURE-IMAGE-BYTES", data)
                    self.assertNotIn(b"DOCX-BYTES", data)
                    self.assertNotIn(b"PREPARED-BYTES", data)
        finally:
            out.close()
        for rows in self.book.values():
            for row in rows:
                for cell in row:
                    self.assertNotIn("sig.png", str(cell))
                    # Only two names mention the signature: the WebSettings key and the WebMemoFlags
                    # column header. Both carry a tick, never the image, its filename or content type.
                    text = str(cell).lower()
                    if text in ("memo_signature_default", "include_signature"):
                        continue
                    self.assertNotIn("signature", text)
                    self.assertNotIn("image/png", text)
                    self.assertNotIn("fake-signature-image-bytes", text)


class ExportEdgeTests(TestCase):
    def test_empty_profile_exports_headers_and_a_default_settings_row_without_writing(self):
        profile = fees_profile("Empty-Backup")
        book = export_rows(profile)
        for sheet, columns in DESKTOP_TABLES:
            self.assertEqual(book[sheet][0], columns)
            if sheet != "Settings":
                self.assertEqual(len(book[sheet]), 1, sheet)
        self.assertEqual(len(book["Settings"]), 2)
        self.assertEqual(rows_as_dicts(book["Settings"])[0]["default_tds_rate"], 10)
        self.assertFalse(FeesSettings.objects.filter(profile=profile).exists())

    def test_only_this_profiles_rows_are_exported(self):
        mine = fees_profile("Mine")
        other = fees_profile("Other")
        seed_web_data(other)
        Firm.objects.create(profile=mine, name="Only Mine")
        book = export_rows(mine)
        self.assertEqual([r["name"] for r in rows_as_dicts(book["Firms"])], ["Only Mine"])
        self.assertEqual(len(book["Memos"]), 1)
        self.assertEqual(len(book["Payments"]), 1)

    def test_text_that_looks_like_a_formula_or_has_control_characters_is_stored_as_text(self):
        profile = fees_profile("Odd-Text")
        Firm.objects.create(profile=profile, name="Firm X", notes="=1+1 is not a formula\x07 ok")
        book = export_rows(profile)
        notes = rows_as_dicts(book["Firms"])[0]["notes"]
        self.assertEqual(notes, "=1+1 is not a formula ok")

    def test_export_does_not_bump_data_version(self):
        profile = fees_profile("No-Bump")
        Firm.objects.create(profile=profile, name="F")
        FeesSettings.objects.create(profile=profile, data_version=5)
        export_rows(profile)
        self.assertEqual(FeesSettings.objects.get(profile=profile).data_version, 5)

    def test_query_count_is_bounded_not_per_row(self):
        profile = fees_profile("Few-Queries")
        seed_web_data(profile)
        with CaptureQueriesContext(connection) as small:
            out = export_workbook(profile)
            out.close()
        # More rows must not add queries: double the memos and compare.
        matter = Matter.objects.filter(profile=profile).order_by("pk").first()
        Memo.objects.bulk_create(
            [
                Memo(
                    profile=profile, financial_year="2026-27", matter=matter, firm_id=matter.firm_id,
                    group_id=matter.group_id, addressee_line1=f"A{i}", memo_number=f"X/{i}",
                )
                for i in range(30)
            ]
        )
        with CaptureQueriesContext(connection) as big:
            out = export_workbook(profile)
            out.close()
        self.assertLessEqual(len(big), len(small) + 4)  # server-side cursor fetches may add a few
        self.assertLess(len(small), 40)
        self.assertGreater(Payment.objects.filter(profile=profile).count(), 0)


@tag("memory")
class ExportMemoryTests(TestCase):
    def test_export_peaks_under_12_mb_on_planning_dataset(self):
        profile = fees_profile("mem-export")
        build_planning_dataset(profile)
        with assert_peak_under(self, 12):
            out = export_workbook(profile)
            size = out.seek(0, 2)
            out.close()
        self.assertGreater(size, 100000)


class WebMemoFlagsSheetTests(TestCase):
    """The per-memo signature flag travels in the web-only WebMemoFlags sheet, not in the Memos sheet."""

    def test_flag_sheet_has_one_row_per_memo_and_the_ticked_flag(self):
        profile = fees_profile("Flags-Backup")
        seed_web_data(profile)
        ticked = Memo.objects.filter(profile=profile, memo_number__isnull=False).order_by("pk").first()
        Memo.objects.filter(pk=ticked.pk).update(include_signature=True)
        book = export_rows(profile)
        rows = book["WebMemoFlags"]
        self.assertEqual(rows[0], ["memo_id", "memo_number", "include_signature"])
        flags = {row[0]: row[2] for row in rows[1:]}
        self.assertEqual(len(flags), Memo.objects.filter(profile=profile).count())
        self.assertEqual(flags[ticked.pk], 1)
        self.assertEqual(sum(flags.values()), 1)
        self.assertNotIn("include_signature", book["Memos"][0])
