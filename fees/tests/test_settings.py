"""Settings and Bank Account service tests (T2.7, R-SET-1, R-SET-2, R-SET-4, R-SET-7).

Ports ``settingsService.test.ts`` (defaults, partial update, the per-key
validation cases, and the bank-account add / list-order / rename / delete /
duplicate flow) and adds the web-specific cases the brief and spec call for:

* ``get_settings`` returns the model defaults on a first read (TDS 10, money unit
  "full", ``export_owner_name`` "Ziyad Madon", the five memo text defaults blank,
  the two switches ``True``);
* a partial update merges ONLY the provided keys and leaves the rest, and a
  ``None`` resets a field to its default (R-SET-1);
* the validation family raises the 422 ``INVALID_SETTINGS`` error (the port's
  replacement for the original ``UNKNOWN`` / 500): TDS out of range, overdue
  days, default tab, financial-year format and the consecutive-year rule, money
  unit, suffix length, default payment amount, details length;
* R-SET-7: the five memo text defaults save; address / bank-details keep their
  newlines (multi-line TextFields); over-length name / designation / pan -> 422;
  a ``None`` on any of them resets to the blank default;
* Electron-only keys in the input are ignored (no error, not stored);
* bank accounts: add / list (``Lower(name)`` order) / rename / delete, a
  case-insensitive duplicate -> error, the 50 cap -> error, delete-in-use ->
  ``BANK_IN_USE`` (409) refused, and ``BANK_ACCOUNT_NOT_FOUND``;
* ``data_version`` is bumped exactly once per mutating op and not at all by the
  reads.

These tests use the ORM, so Django ``TestCase`` is used and everything is scoped
to a ``Profile(program="fees")``.
"""
import datetime
from decimal import Decimal

from django.test import TestCase

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.errors import FeesError
from fees.models import BankAccount, FeesSettings, Payment
from fees.services.settings import (
    MAX_BANK_ACCOUNTS,
    add_bank_account,
    delete_bank_account,
    get_settings,
    list_bank_accounts,
    update_bank_account,
    update_settings,
)


def fees_profile(name="Ziyad-Fees"):
    return Profile.objects.create(program=KEY_FEES, name=name)


def data_version(profile):
    return (
        FeesSettings.objects.filter(profile=profile)
        .values_list("data_version", flat=True)
        .first()
    )


# ---------------------------------------------------------------------------
# Defaults (R-SET-1)
# ---------------------------------------------------------------------------


class SettingsDefaultsTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()

    def test_first_read_creates_row_with_model_defaults(self):
        self.assertFalse(FeesSettings.objects.filter(profile=self.profile).exists())
        s = get_settings(self.profile)
        self.assertTrue(FeesSettings.objects.filter(profile=self.profile).exists())
        self.assertEqual(s["default_tds_rate"], Decimal("10"))
        self.assertEqual(s["money_unit"], "full")
        self.assertEqual(s["initial_financial_year"], "2026-27")
        self.assertEqual(s["default_payment_amount"], "zero")
        self.assertTrue(s["default_lines_enabled"])
        self.assertEqual(s["export_owner_name"], "Ziyad Madon")
        self.assertTrue(s["statistics_enabled"])
        self.assertTrue(s["dashboard_kpis_enabled"])
        self.assertEqual(s["memo_default_name"], "")
        self.assertEqual(s["memo_default_designation"], "")
        self.assertEqual(s["memo_default_address"], "")
        self.assertEqual(s["memo_default_bank_details"], "")
        self.assertEqual(s["memo_default_pan"], "")

    def test_first_read_does_not_bump_data_version(self):
        get_settings(self.profile)
        self.assertEqual(data_version(self.profile), 0)
        get_settings(self.profile)
        self.assertEqual(data_version(self.profile), 0)


# ---------------------------------------------------------------------------
# Partial update + None resets (R-SET-1)
# ---------------------------------------------------------------------------


class UpdateSettingsTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()

    def test_updates_defaults(self):
        s = update_settings(
            self.profile,
            {"default_fees_per_appearance": 5000, "default_tds_rate": 12},
        )
        self.assertEqual(s["default_fees_per_appearance"], Decimal("5000"))
        self.assertEqual(s["default_tds_rate"], Decimal("12"))

    def test_partial_update_leaves_other_keys(self):
        update_settings(self.profile, {"default_tds_rate": 12})
        update_settings(self.profile, {"overdue_days": 45})
        s = get_settings(self.profile)
        self.assertEqual(s["default_tds_rate"], Decimal("12"))
        self.assertEqual(s["overdue_days"], 45)
        # Untouched keys keep their defaults.
        self.assertEqual(s["money_unit"], "full")

    def test_none_resets_field_to_default(self):
        update_settings(self.profile, {"default_tds_rate": 50})
        update_settings(self.profile, {"money_unit": "truncated"})
        s = update_settings(
            self.profile, {"default_tds_rate": None, "money_unit": None}
        )
        self.assertEqual(s["default_tds_rate"], Decimal("10"))
        self.assertEqual(s["money_unit"], "full")

    def test_valid_financial_year_persists(self):
        self.assertEqual(get_settings(self.profile)["initial_financial_year"], "2026-27")
        s = update_settings(self.profile, {"initial_financial_year": "2027-28"})
        self.assertEqual(s["initial_financial_year"], "2027-28")
        self.assertEqual(
            get_settings(self.profile)["initial_financial_year"], "2027-28"
        )

    def test_update_bumps_data_version_once(self):
        get_settings(self.profile)
        before = data_version(self.profile)
        update_settings(self.profile, {"default_tds_rate": 11})
        self.assertEqual(data_version(self.profile), before + 1)


# ---------------------------------------------------------------------------
# Per-key validation (422 INVALID_SETTINGS, replacing the original UNKNOWN/500)
# ---------------------------------------------------------------------------


class ValidationTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()

    def _expect_invalid(self, data):
        with self.assertRaises(FeesError) as ctx:
            update_settings(self.profile, data)
        self.assertEqual(ctx.exception.code, "INVALID_SETTINGS")
        self.assertEqual(ctx.exception.status, 422)
        return ctx.exception

    def test_tds_rate_out_of_range(self):
        self._expect_invalid({"default_tds_rate": 150})
        self._expect_invalid({"default_tds_rate": -1})

    def test_overdue_days(self):
        self._expect_invalid({"overdue_days": -1})
        self._expect_invalid({"overdue_days": 4000})
        self._expect_invalid({"overdue_days": 1.5})

    def test_items_per_page(self):
        self.assertEqual(get_settings(self.profile)["items_per_page"], 50)
        for value, expected in ((25, 25), ("30", 30), (0, 0), ("All", 0), (" all ", 0), (1000, 1000)):
            self.assertEqual(update_settings(self.profile, {"items_per_page": value})["items_per_page"], expected)
        self._expect_invalid({"items_per_page": -1})
        self._expect_invalid({"items_per_page": 1001})
        self._expect_invalid({"items_per_page": 2.5})
        self._expect_invalid({"items_per_page": "many"})
        self.assertEqual(update_settings(self.profile, {"items_per_page": None})["items_per_page"], 50)

    def test_default_tab(self):
        self._expect_invalid({"default_tab": "nope"})
        # A valid tab is accepted.
        s = update_settings(self.profile, {"default_tab": "dashboard"})
        self.assertEqual(s["default_tab"], "dashboard")

    def test_financial_year_format(self):
        self._expect_invalid({"initial_financial_year": "2026"})

    def test_financial_year_consecutive_years_rule(self):
        # "2026-28" is well-formed but the years are not consecutive.
        self._expect_invalid({"initial_financial_year": "2026-28"})
        self._expect_invalid({"memos_start_year": "2026-28"})
        self._expect_invalid({"feebook_start_year": "2026-99"})

    def test_money_unit(self):
        self._expect_invalid({"money_unit": "lacs"})

    def test_money_suffix_length(self):
        self._expect_invalid({"money_suffix_lac": "x" * 13})
        # 12 is allowed.
        s = update_settings(self.profile, {"money_suffix_lac": "x" * 12})
        self.assertEqual(s["money_suffix_lac"], "x" * 12)

    def test_default_payment_amount(self):
        self._expect_invalid({"default_payment_amount": "half"})
        s = update_settings(self.profile, {"default_payment_amount": "netOfTds"})
        self.assertEqual(s["default_payment_amount"], "netOfTds")

    def test_additional_details_length(self):
        self._expect_invalid({"default_additional_details_left": "x" * 501})
        s = update_settings(
            self.profile, {"default_additional_details_left": "x" * 500}
        )
        self.assertEqual(len(s["default_additional_details_left"]), 500)

    def test_export_owner_name_length(self):
        self._expect_invalid({"export_owner_name": "x" * 81})

    def test_memo_filename_pattern_length(self):
        self._expect_invalid({"memo_filename_pattern": "x" * 201})
        s = update_settings(self.profile, {"memo_filename_pattern": "{memo_no} {matter}"})
        self.assertEqual(s["memo_filename_pattern"], "{memo_no} {matter}")

    def test_memo_filename_pattern_validated(self):
        self._expect_invalid({"memo_filename_pattern": "{number}"})
        self._expect_invalid({"memo_filename_pattern": "Memo {memo_no"})
        self._expect_invalid({"memo_filename_pattern": "Memo [ of {fy}"})
        s = update_settings(self.profile, {"memo_filename_pattern": ""})
        self.assertEqual(s["memo_filename_pattern"], "")


# ---------------------------------------------------------------------------
# R-SET-7 memo text defaults
# ---------------------------------------------------------------------------


class MemoTextDefaultsTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()

    def test_set_and_persist(self):
        s = update_settings(
            self.profile,
            {
                "memo_default_name": "Ziyad Madon",
                "memo_default_designation": "Advocate",
                "memo_default_pan": "ABCDE1234F",
            },
        )
        self.assertEqual(s["memo_default_name"], "Ziyad Madon")
        self.assertEqual(s["memo_default_designation"], "Advocate")
        self.assertEqual(s["memo_default_pan"], "ABCDE1234F")

    def test_multi_line_fields_keep_newlines(self):
        address = "12 Court Road\nMumbai 400001"
        bank = "Bank: HDFC\nA/C: 123456\nIFSC: HDFC0001"
        s = update_settings(
            self.profile,
            {"memo_default_address": address, "memo_default_bank_details": bank},
        )
        self.assertEqual(s["memo_default_address"], address)
        self.assertEqual(s["memo_default_bank_details"], bank)
        self.assertIn("\n", get_settings(self.profile)["memo_default_address"])

    def test_over_length_name_designation_pan_rejected(self):
        for data in (
            {"memo_default_name": "x" * 121},
            {"memo_default_designation": "x" * 121},
            {"memo_default_pan": "x" * 21},
        ):
            with self.assertRaises(FeesError) as ctx:
                update_settings(self.profile, data)
            self.assertEqual(ctx.exception.code, "INVALID_SETTINGS")
            self.assertEqual(ctx.exception.status, 422)

    def test_none_resets_memo_default_to_blank(self):
        update_settings(self.profile, {"memo_default_name": "Someone"})
        s = update_settings(self.profile, {"memo_default_name": None})
        self.assertEqual(s["memo_default_name"], "")


# ---------------------------------------------------------------------------
# Electron-only / unknown keys are ignored
# ---------------------------------------------------------------------------


class DroppedKeysTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()

    def test_electron_only_keys_ignored_without_error(self):
        # None of these raise, and none are stored (they are not model fields).
        s = update_settings(
            self.profile,
            {
                "zoom_factor": 1.5,
                "backup_retention": 99,
                "word_template_path": "/tmp/x.docx",
                "auto_backup_frequency": "daily",
                "default_tds_rate": 20,
            },
        )
        # The one real key took effect.
        self.assertEqual(s["default_tds_rate"], Decimal("20"))
        # The dropped keys are not exposed by get_settings.
        self.assertNotIn("zoom_factor", s)
        self.assertNotIn("backup_retention", s)
        self.assertNotIn("word_template_path", s)

    def test_unknown_key_ignored(self):
        s = update_settings(self.profile, {"totally_made_up": "x"})
        self.assertNotIn("totally_made_up", s)


# ---------------------------------------------------------------------------
# Bank accounts (R-SET-2)
# ---------------------------------------------------------------------------


class BankAccountTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()

    def test_add_list_rename_delete(self):
        add_bank_account(self.profile, "HDFC")
        add_bank_account(self.profile, "axis")
        self.assertEqual(
            [b.name for b in list_bank_accounts(self.profile)], ["axis", "HDFC"]
        )
        icici = add_bank_account(self.profile, "ICICI")
        update_bank_account(self.profile, icici.pk, "ICICI Bank")
        self.assertTrue(
            any(b.name == "ICICI Bank" for b in list_bank_accounts(self.profile))
        )
        delete_bank_account(self.profile, icici.pk)
        self.assertEqual(
            [b.name for b in list_bank_accounts(self.profile)], ["axis", "HDFC"]
        )

    def test_add_trims_name(self):
        account = add_bank_account(self.profile, "  Kotak  ")
        self.assertEqual(account.name, "Kotak")

    def test_blank_name_rejected(self):
        with self.assertRaises(FeesError) as ctx:
            add_bank_account(self.profile, "   ")
        self.assertEqual(ctx.exception.code, "INVALID_SETTINGS")
        self.assertEqual(ctx.exception.status, 422)

    def test_too_long_name_rejected(self):
        with self.assertRaises(FeesError) as ctx:
            add_bank_account(self.profile, "x" * 201)
        self.assertEqual(ctx.exception.code, "INVALID_SETTINGS")

    def test_duplicate_case_insensitive(self):
        add_bank_account(self.profile, "SBI")
        with self.assertRaises(FeesError) as ctx:
            add_bank_account(self.profile, "sbi")
        self.assertEqual(ctx.exception.code, "INVALID_SETTINGS")
        self.assertEqual(ctx.exception.status, 422)

    def test_rename_duplicate_rejected(self):
        add_bank_account(self.profile, "SBI")
        other = add_bank_account(self.profile, "Axis")
        with self.assertRaises(FeesError) as ctx:
            update_bank_account(self.profile, other.pk, "sbi")
        self.assertEqual(ctx.exception.code, "INVALID_SETTINGS")

    def test_rename_to_its_own_name_allowed(self):
        account = add_bank_account(self.profile, "SBI")
        update_bank_account(self.profile, account.pk, "SBI")
        account.refresh_from_db()
        self.assertEqual(account.name, "SBI")

    def test_max_accounts(self):
        for i in range(MAX_BANK_ACCOUNTS):
            add_bank_account(self.profile, f"Bank {i}")
        with self.assertRaises(FeesError) as ctx:
            add_bank_account(self.profile, "One too many")
        self.assertEqual(ctx.exception.code, "INVALID_SETTINGS")

    def test_rename_missing_raises_not_found(self):
        with self.assertRaises(FeesError) as ctx:
            update_bank_account(self.profile, 999999, "X")
        self.assertEqual(ctx.exception.code, "BANK_ACCOUNT_NOT_FOUND")
        self.assertEqual(ctx.exception.status, 404)

    def test_delete_missing_raises_not_found(self):
        with self.assertRaises(FeesError) as ctx:
            delete_bank_account(self.profile, 999999)
        self.assertEqual(ctx.exception.code, "BANK_ACCOUNT_NOT_FOUND")

    def test_delete_in_use_is_refused(self):
        account = add_bank_account(self.profile, "In Use")
        Payment.objects.create(
            profile=self.profile,
            amount=Decimal("100"),
            date_of_payment=datetime.date(2026, 7, 1),
            bank_account=account,
        )
        with self.assertRaises(FeesError) as ctx:
            delete_bank_account(self.profile, account.pk)
        self.assertEqual(ctx.exception.code, "BANK_IN_USE")
        self.assertEqual(ctx.exception.status, 409)
        # The guard runs before any delete.
        self.assertTrue(BankAccount.objects.filter(pk=account.pk).exists())

    def test_bank_ops_are_scoped_to_profile(self):
        other = fees_profile("Other-Fees")
        account = add_bank_account(self.profile, "SBI")
        with self.assertRaises(FeesError) as ctx:
            update_bank_account(other, account.pk, "X")
        self.assertEqual(ctx.exception.code, "BANK_ACCOUNT_NOT_FOUND")
        # The same name is free in a different profile.
        add_bank_account(other, "SBI")

    def test_bank_ops_bump_data_version_once(self):
        get_settings(self.profile)
        before = data_version(self.profile)
        account = add_bank_account(self.profile, "SBI")
        self.assertEqual(data_version(self.profile), before + 1)
        update_bank_account(self.profile, account.pk, "SBI Main")
        self.assertEqual(data_version(self.profile), before + 2)
        delete_bank_account(self.profile, account.pk)
        self.assertEqual(data_version(self.profile), before + 3)

    def test_list_does_not_bump_data_version(self):
        get_settings(self.profile)
        before = data_version(self.profile)
        list(list_bank_accounts(self.profile))
        self.assertEqual(data_version(self.profile), before)
