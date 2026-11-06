"""Excel restore tests (T4.2, T4.3, T4.5, R-BK-2, R-BK-3, design 7.2 and 7.3).

Covers: web to web round trip; a desktop-shaped workbook generated here (legacy ``payments.memo_id``,
no ``PaymentAllocations`` sheet, older ``Settings`` and ``Payments`` columns); the empty sample
``.xlsx`` shipped in ``fees/tests/fixtures`` (no client data); NOT NULL defaults for missing columns;
cell coercion; id remapping and foreign keys; sequences, stored totals and paid totals; the five memo
text defaults through ``WebSettings``; the signature image through the suite backup only; typed
confirmation, pre-restore backup order, heavy lock, size/extension/damage checks, rollback on failure;
a seeded property loop ported from ``backupService.property.test.ts``; query-count bounds; and the
memory gate (restore under 40 MB on the planning dataset).
"""
import base64
import contextlib
import datetime
import gzip
import io
import json
import os
import random
import tempfile
import zipfile
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, tag
from django.test.utils import CaptureQueriesContext

from accounts.models import Profile
from accounts.suite import KEY_FEES
from backups import services as backup_services
from backups.models import BackupFile
from fees.errors import FeesError
from fees.models import (
    Allocation,
    FeesSettings,
    Firm,
    Group,
    Matter,
    Memo,
    NumberSequence,
    Payment,
    StatsCache,
    WordTemplate,
)
from fees.services import excel_restore, integrity, matters, memos, payments, firms
from fees.services.excel_backup import export_workbook
from fees.services.excel_restore import RESTORE_CONFIRMATION, preview_workbook, restore_workbook
from fees.services.heavy import Busy
from fees.tests.datasets import build_planning_dataset
from fees.tests.memory import assert_peak_under
from fees.tests.xlsx_support import (
    MEMO_TEXT_DEFAULTS,
    PAYMENT_DETAILS_SENTINEL,
    SIGNATURE_BYTES,
    build_workbook,
    memo_input,
    no_backup,
    read_workbook,
    rows_as_dicts,
    seed_web_data,
    snapshot,
)

User = get_user_model()
FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE = os.path.join(FIXTURES, "fee_register_empty_reset_backup.xlsx")


def fees_profile(name):
    return Profile.objects.create(program=KEY_FEES, name=name)


def restore(profile, source, **kwargs):
    kwargs.setdefault("backup_func", no_backup)
    return restore_workbook(profile, source, RESTORE_CONFIRMATION, **kwargs)


def export_of(profile):
    return export_workbook(profile)


def row(header, values):
    """A row in ``header`` order from a ``{column: value}`` dict (missing columns are empty)."""
    return [values.get(name) for name in header]


# ---------------------------------------------------------------------------
# A desktop-shaped workbook: legacy payments.memo_id, no PaymentAllocations or SavedViews sheet,
# older Payments (no payment_mode) and Settings (first columns only).
# ---------------------------------------------------------------------------
FIRMS_H = ["id", "name", "status", "notes", "created_at", "updated_at"]
PARTNERS_H = ["id", "firm_id", "name", "created_at"]
MATTERS_H = [
    "id", "firm_id", "partner_id", "name", "is_archived", "is_custom", "addressee_line1",
    "addressee_line2", "addressee_use_firm_name", "court_name", "client", "additional_details_left",
    "additional_details_right", "plaintiff_name", "plaintiff_type", "defendant_name", "defendant_type",
    "notes", "short_name", "created_at", "updated_at",
]
BANKS_H = ["id", "name", "created_at"]
MEMOS_H = [
    "id", "memo_number", "financial_year", "seq", "date", "matter_id", "firm_id", "partner_id",
    "addressee_line1", "addressee_line2", "court_name", "additional_details_left",
    "additional_details_right", "plaintiff_name", "plaintiff_type", "defendant_name", "defendant_type",
    "client", "num_appearances", "dates_of_appearances", "fees_per_appearance", "num_conferences",
    "dates_of_conferences", "fees_per_conference", "misc_drafting_description", "fees_misc_drafting",
    "num_drafts", "tds_rate", "written_off", "is_draft", "custom_fees_appearances",
    "custom_fees_conferences", "custom_fees_misc", "custom_total_fees", "created_at", "updated_at",
]
PAYMENTS_OLD_H = [
    "id", "memo_id", "amount", "tds_rate", "auto_tds", "tds_amount", "memo_amount", "date_of_payment",
    "payee", "bank_account_id", "payment_details", "created_at", "updated_at",
]
ADJUSTMENTS_H = [
    "id", "financial_year", "month", "working_days", "extra_appearances", "extra_conferences",
    "extra_drafts", "ov_appearances", "ov_conferences", "ov_drafts", "ov_billed", "ov_received",
    "ov_received_plus_tds", "updated_at",
]
SETTINGS_OLD_H = [
    "id", "default_fees_per_appearance", "default_fees_per_conference", "default_fees_misc_drafting",
    "default_additional_details_left", "default_additional_details_right", "default_court_name",
    "default_tds_rate", "overdue_days", "default_tab", "auto_backup_frequency", "auto_backup_dir",
    "last_auto_backup", "word_template_path", "updated_at",
]
STAMP = "2025-04-01 10:00:00"


def desktop_sheets():
    return {
        "Firms": [
            FIRMS_H,
            row(FIRMS_H, dict(id=1, name="Alpha & Co", status="active", notes="first", created_at=STAMP, updated_at=STAMP)),
            row(FIRMS_H, dict(id=2, name="Beta", status="archived", created_at=STAMP, updated_at=STAMP)),
        ],
        "Partners": [
            PARTNERS_H,
            row(PARTNERS_H, dict(id=10, firm_id=1, name="Alpha & Co", created_at=STAMP)),
            row(PARTNERS_H, dict(id=11, firm_id=1, name="Second", created_at=STAMP)),
            row(PARTNERS_H, dict(id=12, firm_id=2, name="Beta", created_at=STAMP)),
        ],
        "Matters": [
            MATTERS_H,
            row(MATTERS_H, dict(id=100, firm_id=1, partner_id=10, name="M1", is_archived=0, is_custom=0,
                                addressee_line1="To Alpha", created_at=STAMP, updated_at=STAMP)),
            row(MATTERS_H, dict(id=101, firm_id=2, partner_id=12, name="M2", is_archived=1, is_custom=0,
                                created_at=STAMP, updated_at=STAMP)),
        ],
        "BankAccounts": [BANKS_H, row(BANKS_H, dict(id=5, name="HDFC", created_at=STAMP))],
        "Memos": [
            MEMOS_H,
            row(MEMOS_H, dict(id=1000, memo_number="2025-26/1", financial_year="2025-26", seq=1,
                              date="2025-06-10", matter_id=100, firm_id=1, partner_id=10,
                              addressee_line1="Addr", num_appearances=2, fees_per_appearance=5000,
                              num_conferences=1, fees_per_conference=2000, fees_misc_drafting=500,
                              tds_rate=10, written_off=0, is_draft=0)),
            row(MEMOS_H, dict(id=1001, memo_number="2025-26/2", financial_year="2025-26", seq=2,
                              date="2025-07-11", matter_id=100, firm_id=1, partner_id=10,
                              addressee_line1="Addr", num_appearances=1, fees_per_appearance=1000,
                              custom_total_fees=9999, written_off=0, is_draft=0)),
            row(MEMOS_H, dict(id=1002, memo_number=None, seq=99, matter_id=101, firm_id=2, partner_id=12,
                              addressee_line1="Draft", is_draft=1)),
            # firm/group on the row disagree with the matter: the matter wins (R-DATA-5).
            row(MEMOS_H, dict(id=1003, memo_number="2026-27/4", financial_year="2026-27", seq=4,
                              date="2026-04-05", matter_id=101, firm_id=1, partner_id=10,
                              addressee_line1="Addr", num_appearances=1, fees_per_appearance=3000,
                              fees_misc_drafting=700, custom_fees_misc=0, custom_total_fees=0)),
        ],
        "Payments": [
            PAYMENTS_OLD_H,
            row(PAYMENTS_OLD_H, dict(id=1, memo_id=1000, amount=9000, tds_rate=10, auto_tds=1,
                                     tds_amount=1000, memo_amount=0, date_of_payment="2025-08-01",
                                     payee="Payer", bank_account_id=5, payment_details="LEGACY-DETAIL")),
            row(PAYMENTS_OLD_H, dict(id=2, amount=500, tds_rate=0, auto_tds=0, tds_amount=0, memo_amount=0,
                                     date_of_payment="2025-09-01", payee="Loose")),
            row(PAYMENTS_OLD_H, dict(id=3, memo_id=1001, amount=100, tds_rate=0, auto_tds=1, tds_amount=0,
                                     memo_amount=0, date_of_payment="2025-09-02", payee="Small")),
            row(PAYMENTS_OLD_H, dict(id=4, memo_id=9999, amount=50, tds_rate=0, auto_tds=1, tds_amount=0,
                                     memo_amount=0, date_of_payment="2025-09-03", payee="Orphan link")),
        ],
        "PeriodAdjustments": [
            ADJUSTMENTS_H,
            row(ADJUSTMENTS_H, dict(id=1, financial_year="2025-26", month=4, working_days=21, ov_billed=1000.5,
                                    updated_at=STAMP)),
        ],
        "Settings": [
            SETTINGS_OLD_H,
            row(SETTINGS_OLD_H, dict(id=1, default_fees_per_appearance=7000, default_tds_rate=12,
                                     overdue_days=30, default_tab="dashboard", auto_backup_frequency="off",
                                     updated_at=STAMP)),
        ],
    }


def minimal_sheets(memo_count=1):
    """The smallest valid workbook: key columns only, one firm, group and matter, ``memo_count`` memos."""
    return {
        "Firms": [["id", "name"], [1, "F"]],
        "Partners": [["id", "firm_id", "name"], [1, 1, "G"]],
        "Matters": [["id", "firm_id", "partner_id", "name"], [1, 1, 1, "M"]],
        "BankAccounts": [["id", "name"]],
        "Memos": [["id", "matter_id", "date"]] + [[i, 1, "2026-05-17"] for i in range(1, memo_count + 1)],
        "Payments": [["id", "amount", "date_of_payment"]],
        "Settings": [["id"], [1]],
    }


class WebToWebRoundTripTests(TestCase):
    def setUp(self):
        self.source = fees_profile("RT-Source")
        self.objs = seed_web_data(self.source)

    def test_restore_into_another_profile_gives_the_same_data_after_id_remapping(self):
        target = fees_profile("RT-Target")
        out = export_of(self.source)
        result = restore(target, out)
        out.close()
        self.assertEqual(snapshot(target), snapshot(self.source))
        self.assertTrue(result["fees_check"]["ok"])
        self.assertEqual(result["fees_check"]["memos_checked"], 4)
        counts = result["counts"]
        self.assertEqual(
            (counts["firms"], counts["groups"], counts["matters"], counts["memos"], counts["payments"],
             counts["allocations"], counts["allocations_backfilled"]),
            (2, 3, 3, 4, 3, 3, 0),
        )
        # New ids are the target's own, and every foreign key points inside the target.
        self.assertFalse(set(Firm.objects.filter(profile=target).values_list("pk", flat=True))
                         & set(Firm.objects.filter(profile=self.source).values_list("pk", flat=True)))
        self.assertEqual(Allocation.objects.filter(profile=target, memo__profile=target,
                                                   payment__profile=target).count(), 3)

    def test_restore_over_the_same_profile_replaces_everything(self):
        before = snapshot(self.source)
        out = export_of(self.source)
        matters.create_matter(self.source, self.objs["firm_a"].pk,
                              Group.objects.filter(firm=self.objs["firm_a"]).first().pk, "Noise Matter")
        firms.create_firm(self.source, "Noise Firm")
        self.assertNotEqual(snapshot(self.source), before)
        restore(self.source, out)
        out.close()
        self.assertEqual(snapshot(self.source), before)

    def test_stored_totals_are_recomputed_from_fee_rule_and_allocations(self):
        target = fees_profile("RT-Totals")
        out = export_of(self.source)
        restore(target, out)
        out.close()
        a = Memo.objects.get(profile=target, memo_number=self.objs["memo_a"].memo_number)
        original = Memo.objects.get(pk=self.objs["memo_a"].pk)
        self.assertEqual((a.total_fees, a.amount_paid, a.amount_received, a.amount_tds),
                         (original.total_fees, original.amount_paid, original.amount_received,
                          original.amount_tds))
        self.assertGreater(a.amount_paid, 0)
        b = Memo.objects.get(profile=target, memo_number=self.objs["memo_b"].memo_number)
        self.assertEqual(b.total_fees, Decimal("777.00"))  # the custom total override

    def test_payment_details_survive_the_full_backup(self):
        target = fees_profile("RT-Details")
        out = export_of(self.source)
        restore(target, out)
        out.close()
        self.assertTrue(Payment.objects.filter(profile=target, payment_details=PAYMENT_DETAILS_SENTINEL).exists())

    def test_five_memo_text_defaults_and_web_only_settings_round_trip_via_websettings(self):
        target = fees_profile("RT-Settings")
        out = export_of(self.source)
        restore(target, out)
        out.close()
        saved = FeesSettings.objects.get(profile=target)
        for key, expected in MEMO_TEXT_DEFAULTS.items():
            self.assertEqual(getattr(saved, key), expected, key)
        self.assertEqual(saved.export_owner_name, "Test Owner")
        self.assertEqual(saved.memo_filename_pattern, "pattern-x")
        self.assertFalse(saved.statistics_enabled)
        self.assertFalse(saved.dashboard_kpis_enabled)
        self.assertEqual(saved.default_tds_rate, Decimal("12.50"))

    def test_signature_is_not_in_the_xlsx_and_round_trips_via_the_suite_backup_only(self):
        out = export_of(self.source)
        with zipfile.ZipFile(out) as archive:
            for name in archive.namelist():
                self.assertNotIn(b"FAKE-SIGNATURE-IMAGE-BYTES", archive.read(name))
        # Restoring the .xlsx into a profile creates no template and no signature.
        target = fees_profile("RT-NoSig")
        restore(target, out)
        out.close()
        self.assertFalse(WordTemplate.objects.filter(profile=target).exists())
        # The suite backup carries the signature bytes and brings them back.
        admin = User.objects.create_user("boss", password="correct-horse-battery-9", is_superuser=True, is_staff=True)
        backup = backup_services.create_backup("manual", admin)
        document = json.loads(gzip.decompress(bytes(backup.data)).decode("utf-8"))
        records = [r for r in document["models"]["fees.WordTemplate"] if r["fields"]["profile"] == self.source.pk]
        self.assertEqual(len(records), 1)
        self.assertEqual(base64.b64decode(records[0]["fields"]["signature_data"]), SIGNATURE_BYTES)
        WordTemplate.objects.filter(profile=self.source).delete()
        backup_services.restore_backup(backup_services.parse_backup(backup.data, 30 * 1024 * 1024), admin)
        template = WordTemplate.objects.get(profile=self.source)
        self.assertEqual(bytes(template.signature_data), SIGNATURE_BYTES)
        self.assertEqual(template.signature_filename, "sig.png")

    def test_restore_leaves_the_word_template_and_other_profiles_alone(self):
        other = fees_profile("RT-Other")
        seed_web_data(other)
        other_before = snapshot(other)
        out = export_of(self.source)
        restore(self.source, out)
        out.close()
        template = WordTemplate.objects.get(profile=self.source)
        self.assertEqual(bytes(template.signature_data), SIGNATURE_BYTES)
        self.assertEqual(snapshot(other), other_before)

    def test_data_version_is_bumped_and_stats_cache_purged(self):
        StatsCache.objects.create(profile=self.source, kind="x", params_hash="h", data_version=0, payload={})
        before = FeesSettings.objects.get(profile=self.source).data_version
        out = export_of(self.source)
        restore(self.source, out)
        out.close()
        self.assertGreater(FeesSettings.objects.get(profile=self.source).data_version, before)
        self.assertFalse(StatsCache.objects.filter(profile=self.source).exists())

    def test_new_memo_numbers_continue_from_the_restored_max_seq(self):
        profile = fees_profile("RT-Seq")
        _firm = firms.create_firm(profile, "Firm")
        group = Group.objects.get(firm=_firm)
        matter = matters.create_matter(profile, _firm.pk, group.pk, "M")
        memos.create_memo(profile, memo_input(matter.pk, date="2026-07-15"))
        memos.create_memo(profile, memo_input(matter.pk, date="2026-07-16"))
        out = export_of(profile)
        restore(profile, out)
        out.close()
        matter = Matter.objects.get(profile=profile)
        nxt = memos.create_memo(profile, memo_input(matter.pk, date="2026-07-17"))
        self.assertEqual(nxt.memo_number, "2026-27/3")


class DesktopShapedFileTests(TestCase):
    def setUp(self):
        self.profile = fees_profile("Desktop")
        # Existing data that the restore must replace.
        seed_web_data(self.profile)

    def _restore(self):
        source = build_workbook(desktop_sheets())
        return restore(self.profile, source)

    def test_counts_after_restore(self):
        result = self._restore()
        counts = result["counts"]
        self.assertEqual(counts["firms"], 2)
        self.assertEqual(counts["groups"], 3)
        self.assertEqual(counts["matters"], 2)
        self.assertEqual(counts["bank_accounts"], 1)
        self.assertEqual(counts["memos"], 4)
        self.assertEqual(counts["payments"], 4)
        self.assertEqual(counts["allocations"], 0)
        self.assertEqual(counts["allocations_backfilled"], 2)
        self.assertEqual(counts["period_adjustments"], 1)
        self.assertEqual(counts["saved_views"], 0)
        self.assertEqual(Firm.objects.filter(profile=self.profile).count(), 2)
        self.assertEqual(Payment.objects.filter(profile=self.profile).count(), 4)

    def test_legacy_payment_memo_id_creates_allocations_when_no_allocations_sheet(self):
        result = self._restore()
        allocations = {
            a.payment.payee: a
            for a in Allocation.objects.filter(profile=self.profile).select_related("payment", "memo")
        }
        self.assertEqual(sorted(allocations), ["Payer", "Small"])
        payer = allocations["Payer"]
        self.assertEqual((payer.amount, payer.tds_amount), (Decimal("9000.00"), Decimal("1000.00")))
        self.assertEqual(payer.memo.memo_number, "2025-26/1")
        self.assertEqual(allocations["Small"].memo.memo_number, "2025-26/2")
        # A payment that points at a memo not in the file stays unassigned, with a warning.
        self.assertFalse(Allocation.objects.filter(payment__payee="Orphan link").exists())
        self.assertFalse(Allocation.objects.filter(payment__payee="Loose").exists())
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("1 payment", result["warnings"][0])

    def test_stored_totals_follow_the_single_fee_rule_and_the_allocations(self):
        self._restore()
        by_number = {m.memo_number: m for m in Memo.objects.filter(profile=self.profile)}
        first = by_number["2025-26/1"]
        self.assertEqual(first.total_fees, Decimal("12500.00"))
        self.assertEqual((first.amount_paid, first.amount_received, first.amount_tds),
                         (Decimal("10000.00"), Decimal("9000.00"), Decimal("1000.00")))
        second = by_number["2025-26/2"]
        self.assertEqual(second.total_fees, Decimal("9999.00"))  # a real custom total
        self.assertEqual(second.amount_paid, Decimal("100.00"))
        # custom total 0 means no override (D3); a line custom of 0 IS an override.
        fourth = by_number["2026-27/4"]
        self.assertEqual(fourth.total_fees, Decimal("3000.00"))
        self.assertTrue(integrity.check_profile(self.profile).ok)

    def test_ids_are_remapped_and_firm_and_group_come_from_the_matter(self):
        self._restore()
        fourth = Memo.objects.get(profile=self.profile, memo_number="2026-27/4")
        self.assertEqual(fourth.matter.name, "M2")
        self.assertEqual(fourth.firm.name, "Beta")
        self.assertEqual(fourth.group.name, "Beta")
        self.assertEqual(fourth.matter.firm_id, fourth.firm_id)
        self.assertTrue(fourth.matter.is_archived)
        firm_a = Firm.objects.get(profile=self.profile, name="Alpha & Co")
        self.assertEqual(sorted(Group.objects.filter(firm=firm_a).values_list("name", flat=True)),
                         ["Alpha & Co", "Second"])
        payer = Payment.objects.get(profile=self.profile, payee="Payer")
        self.assertEqual(payer.bank_account.name, "HDFC")
        self.assertEqual(payer.payment_details, "LEGACY-DETAIL")
        self.assertEqual(payer.payment_mode, "")  # column absent in the older file
        loose = Payment.objects.get(profile=self.profile, payee="Loose")
        self.assertFalse(loose.auto_tds)
        firm_b = Firm.objects.get(profile=self.profile, name="Beta")
        self.assertEqual(firm_b.status, "archived")

    def test_sequences_are_max_seq_per_fy_over_non_draft_memos(self):
        self._restore()
        sequences = dict(NumberSequence.objects.filter(profile=self.profile).values_list("financial_year", "last_seq"))
        self.assertEqual(sequences, {"2025-26": 2, "2026-27": 4})  # the draft's seq 99 does not count
        draft = Memo.objects.get(profile=self.profile, is_draft=True)
        self.assertIsNone(draft.memo_number)
        self.assertIsNone(draft.date)

    def test_settings_from_the_older_file_with_defaults_for_missing_columns(self):
        self._restore()
        saved = FeesSettings.objects.get(profile=self.profile)
        self.assertEqual(saved.default_fees_per_appearance, Decimal("7000.00"))
        self.assertEqual(saved.default_tds_rate, Decimal("12.00"))
        self.assertEqual(saved.overdue_days, 30)
        self.assertEqual(saved.default_tab, "dashboard")
        # Columns the file lacks take the desktop defaults (NOT NULL defaults), not NULL.
        self.assertTrue(saved.default_lines_enabled)
        self.assertTrue(saved.show_status_dots)
        self.assertFalse(saved.hide_payment_when_paid)
        self.assertEqual(saved.money_unit, "full")
        self.assertEqual(saved.money_suffix_lac, "lac")
        self.assertEqual(saved.default_payment_amount, "zero")
        # No WebSettings sheet: web-only settings go back to defaults, memo text defaults to blank.
        self.assertEqual(saved.export_owner_name, "Ziyad Madon")
        for key in MEMO_TEXT_DEFAULTS:
            self.assertEqual(getattr(saved, key), "")
        self.assertTrue(saved.statistics_enabled)

    def test_preview_describes_the_file_without_writing(self):
        before = snapshot(self.profile)
        with mock.patch.object(excel_restore, "_load", side_effect=AssertionError("must not load")):
            info = preview_workbook(build_workbook(desktop_sheets()), self.profile)
        self.assertEqual(snapshot(self.profile), before)
        self.assertEqual(info["sheets"]["Memos"], 4)
        self.assertEqual(info["sheets"]["Payments"], 4)
        self.assertEqual(info["sheets"]["Settings"], 1)
        self.assertNotIn("PaymentAllocations", info["sheets"])
        self.assertEqual(info["missing_optional"], ["PaymentAllocations", "SavedViews", "WebSettings"])
        self.assertEqual((info["memo_date_min"], info["memo_date_max"]), ("2025-06-10", "2026-04-05"))
        self.assertEqual(info["total_fees"], Decimal("25499.00"))  # drafts are not counted
        self.assertEqual(info["payments_total"], Decimal("9650.00"))
        self.assertEqual(info["payments_with_memo_id"], 3)
        self.assertFalse(info["has_web_settings"])
        self.assertEqual(info["confirmation_phrase"], RESTORE_CONFIRMATION)
        self.assertEqual(info["replaces"]["memos"], 4)  # what the seed put there


class SampleFileTests(TestCase):
    def test_empty_sample_backup_restores_and_clears_the_data(self):
        profile = fees_profile("Sample")
        seed_web_data(profile)
        info = preview_workbook(SAMPLE, profile)
        self.assertEqual(info["sheets"]["Memos"], 0)
        self.assertEqual(info["sheets"]["Settings"], 1)
        self.assertEqual(info["missing_optional"], ["WebSettings"])
        self.assertIsNone(info["memo_date_min"])
        result = restore(profile, SAMPLE)
        self.assertEqual(result["rows_imported"], 0)
        for model in (Firm, Group, Matter, Memo, Payment, Allocation, NumberSequence):
            self.assertEqual(model.objects.filter(profile=profile).count(), 0, model.__name__)
        self.assertTrue(result["fees_check"]["ok"])
        # The Settings row of the sample is applied (older file: missing columns use defaults).
        book = read_workbook(SAMPLE)
        sample = rows_as_dicts(book["Settings"])[0]
        saved = FeesSettings.objects.get(profile=profile)
        self.assertEqual(saved.default_tds_rate, Decimal(str(sample["default_tds_rate"])).quantize(Decimal("0.01")))
        self.assertEqual(saved.default_tab, sample["default_tab"])
        self.assertEqual(saved.overdue_days, int(sample["overdue_days"]))
        self.assertTrue(saved.default_lines_enabled)

    def test_sample_file_is_empty_of_client_data(self):
        book = read_workbook(SAMPLE)
        for sheet, rows in book.items():
            if sheet != "Settings":
                self.assertEqual(len(rows), 1, sheet)


class MinimalFileAndCoercionTests(TestCase):
    def test_missing_not_null_columns_take_the_desktop_defaults(self):
        profile = fees_profile("Minimal")
        restore(profile, build_workbook(minimal_sheets(2)))
        matter = Matter.objects.get(profile=profile)
        self.assertFalse(matter.is_archived)
        self.assertFalse(matter.addressee_use_firm_name)
        memo = Memo.objects.filter(profile=profile).order_by("pk").first()
        self.assertEqual((memo.num_appearances, memo.num_drafts, memo.total_fees), (0, 0, Decimal("0.00")))
        self.assertFalse(memo.is_draft)
        self.assertFalse(memo.written_off)
        self.assertEqual(memo.financial_year, "2026-27")  # derived from the date
        self.assertIsNone(memo.memo_number)

    def test_cell_types_are_coerced(self):
        sheets = minimal_sheets(0)
        sheets["Firms"] = [["id", "name", "status"], [1.0, "  Padded  ", "ARCHIVED"]]
        sheets["BankAccounts"] = [["id", "name"], [7, "Bank"]]
        sheets["Memos"] = [
            ["id", "matter_id", "date", "fees_per_appearance", "num_appearances", "is_draft", "written_off",
             "fees_misc_drafting"],
            [1, 1, datetime.datetime(2026, 5, 17), "\u20b91,234.50", "2", "false", True, "100"],
        ]
        sheets["Payments"] = [
            ["id", "amount", "date_of_payment", "bank_account_id"],
            [1, "250.5", datetime.datetime(2026, 6, 1), 7],
        ]
        sheets["Settings"] = [["id", "default_tds_rate", "overdue_days"], [1, "15", 5.0]]
        profile = fees_profile("Coerce")
        restore(profile, build_workbook(sheets))
        firm = Firm.objects.get(profile=profile)
        self.assertEqual((firm.name, firm.status), ("Padded", "archived"))
        memo = Memo.objects.get(profile=profile)
        self.assertEqual(memo.date, datetime.date(2026, 5, 17))
        self.assertEqual(memo.fees_per_appearance, Decimal("1234.50"))
        self.assertEqual(memo.num_appearances, 2)
        self.assertEqual(memo.total_fees, Decimal("2569.00"))
        self.assertFalse(memo.is_draft)
        self.assertTrue(memo.written_off)
        payment = Payment.objects.get(profile=profile)
        self.assertEqual(payment.amount, Decimal("250.50"))
        self.assertEqual(payment.date_of_payment, datetime.date(2026, 6, 1))
        self.assertTrue(payment.auto_tds)
        self.assertEqual(payment.bank_account.name, "Bank")
        saved = FeesSettings.objects.get(profile=profile)
        self.assertEqual((saved.default_tds_rate, saved.overdue_days), (Decimal("15.00"), 5))

    def test_web_settings_sheet_applies_known_keys_and_ignores_the_rest(self):
        sheets = minimal_sheets(0)
        sheets["WebSettings"] = [
            ["key", "value"],
            ["memo_default_name", "X Y"],
            ["memo_default_address", "L1\nL2"],
            ["statistics_enabled", 0],
            ["unknown_key", "z"],
            ["export_owner_name", ""],
        ]
        profile = fees_profile("WebSet")
        restore(profile, build_workbook(sheets))
        saved = FeesSettings.objects.get(profile=profile)
        self.assertEqual(saved.memo_default_name, "X Y")
        self.assertEqual(saved.memo_default_address, "L1\nL2")
        self.assertFalse(saved.statistics_enabled)
        self.assertEqual(saved.export_owner_name, "Ziyad Madon")  # a blank owner name keeps the default

    def test_allocations_sheet_present_means_no_double_backfill(self):
        sheets = minimal_sheets(2)
        sheets["Payments"] = [
            ["id", "memo_id", "amount", "tds_amount", "date_of_payment"],
            [1, 1, 100, 10, "2026-06-01"],
            [2, 2, 200, 0, "2026-06-02"],
        ]
        sheets["PaymentAllocations"] = [
            ["id", "payment_id", "memo_id", "amount", "tds_amount"],
            [1, 1, 1, 60, 6],
            [2, 1, 2, 40, 4],
        ]
        profile = fees_profile("NoDouble")
        result = restore(profile, build_workbook(sheets))
        # Payment 1 has allocation rows, so its legacy memo_id is ignored; payment 2 has none, so it is backfilled.
        self.assertEqual(result["counts"]["allocations"], 2)
        self.assertEqual(result["counts"]["allocations_backfilled"], 1)
        self.assertEqual(Allocation.objects.filter(payment__amount=100).count(), 2)
        second = Allocation.objects.get(payment__amount=200)
        self.assertEqual((second.amount, second.tds_amount), (Decimal("200.00"), Decimal("0.00")))
        paid = dict(Memo.objects.filter(profile=profile).values_list("pk", "amount_paid"))
        # Memo 1: 60 + 6 from payment 1. Memo 2: 40 + 4 from payment 1, plus the backfilled 200.
        self.assertEqual(sorted(paid.values()), [Decimal("66.00"), Decimal("244.00")])


class FailureAndGuardTests(TestCase):
    def setUp(self):
        self.profile = fees_profile("Guards")
        seed_web_data(self.profile)
        self.before = snapshot(self.profile)

    def _assert_failed(self, source, **kwargs):
        with self.assertRaises(FeesError) as ctx:
            restore(self.profile, source, **kwargs)
        self.assertEqual(ctx.exception.code, "RESTORE_FAILED")
        self.assertEqual(ctx.exception.status, 422)
        self.assertEqual(snapshot(self.profile), self.before)
        return ctx.exception

    def test_typed_confirmation_is_required(self):
        calls = []
        for typed in ("", None, "this replaces all your data", "yes", "This replaces ALL"):
            with self.assertRaises(FeesError) as ctx:
                restore_workbook(self.profile, build_workbook(minimal_sheets()), typed,
                                 backup_func=lambda k, u: calls.append(k))
            self.assertEqual(ctx.exception.code, "INVALID_CONFIRMATION")
            self.assertEqual(ctx.exception.status, 422)
        self.assertEqual(calls, [])
        self.assertEqual(snapshot(self.profile), self.before)

    def test_confirmation_is_trimmed(self):
        restore_workbook(self.profile, build_workbook(minimal_sheets()), f"  {RESTORE_CONFIRMATION}  ",
                         backup_func=no_backup)
        self.assertEqual(Memo.objects.filter(profile=self.profile).count(), 1)

    def test_damaged_file(self):
        self._assert_failed(io.BytesIO(b"this is not a zip file"))
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("hello.txt", "not a workbook")
        buffer.seek(0)
        self._assert_failed(buffer)
        self._assert_failed(io.BytesIO(b""))

    def test_missing_required_sheet(self):
        sheets = minimal_sheets()
        del sheets["Partners"]
        error = self._assert_failed(build_workbook(sheets))
        self.assertIn('"Partners"', error.message)
        # Optional sheets may be absent (minimal_sheets has none of them).
        restore(self.profile, build_workbook(minimal_sheets()))

    def test_missing_key_column_rolls_back_everything(self):
        sheets = minimal_sheets()
        sheets["Firms"] = [["id"], [1]]
        error = self._assert_failed(build_workbook(sheets))
        self.assertIn("name", error.message)

    def test_dangling_foreign_key_rolls_back_everything(self):
        sheets = minimal_sheets()
        sheets["Matters"] = [["id", "firm_id", "partner_id", "name"], [1, 99, 1, "M"]]
        error = self._assert_failed(build_workbook(sheets))
        self.assertIn("Matters", error.message)

    def test_database_error_rolls_back_everything(self):
        sheets = minimal_sheets()
        sheets["Memos"] = [
            ["id", "matter_id", "memo_number"], [1, 1, "DUP/1"], [2, 1, "DUP/1"],
        ]
        self._assert_failed(build_workbook(sheets))
        self.assertTrue(Firm.objects.filter(profile=self.profile, name="Alpha & Co").exists())

    def test_invalid_number_and_payment_date(self):
        sheets = minimal_sheets()
        sheets["Payments"] = [["id", "amount", "date_of_payment"], [1, "abc", "2026-06-01"]]
        self._assert_failed(build_workbook(sheets))
        sheets["Payments"] = [["id", "amount", "date_of_payment"], [1, 5, "2026-13-40"]]
        self._assert_failed(build_workbook(sheets))

    def test_extension_and_size_checks_happen_before_opening(self):
        with tempfile.TemporaryDirectory() as folder:
            bad = os.path.join(folder, "backup.xls")
            with open(bad, "wb") as handle:
                handle.write(build_workbook(minimal_sheets()).getvalue())
            self._assert_failed(bad)
            good = os.path.join(folder, "backup.xlsx")
            with open(good, "wb") as handle:
                handle.write(build_workbook(minimal_sheets()).getvalue())
            with mock.patch.object(excel_restore, "MAX_RESTORE_BYTES", 100):
                self._assert_failed(good)
            restore(self.profile, good)  # the same file restores when within limits
        self.assertEqual(Memo.objects.filter(profile=self.profile).count(), 1)

    def test_decompression_bomb_guard(self):
        with mock.patch.object(excel_restore, "MAX_UNCOMPRESSED_BYTES", 1000):
            self._assert_failed(build_workbook(minimal_sheets()))

    def test_backup_runs_first_with_the_pre_restore_kind_and_failure_aborts(self):
        seen = []

        def stub(kind, user):
            seen.append((kind, user, Firm.objects.filter(profile=self.profile).count()))

        restore(self.profile, build_workbook(minimal_sheets()), backup_func=stub, user="U")
        self.assertEqual(seen, [("pre_restore", "U", 2)])  # called once, before any row was deleted

    def test_backup_failure_changes_nothing(self):
        def boom(kind, user):
            raise RuntimeError("disk full")

        error = self._assert_failed(build_workbook(minimal_sheets()), backup_func=boom)
        self.assertIn("safety backup", error.message)

    def test_real_pre_restore_suite_backup_is_stored_and_carries_the_signature(self):
        restore(self.profile, build_workbook(minimal_sheets()), backup_func=None)
        stored = BackupFile.objects.get(kind="pre_restore")
        document = json.loads(gzip.decompress(bytes(stored.data)).decode("utf-8"))
        records = [r for r in document["models"]["fees.WordTemplate"] if r["fields"]["profile"] == self.profile.pk]
        self.assertEqual(base64.b64decode(records[0]["fields"]["signature_data"]), SIGNATURE_BYTES)
        self.assertEqual(len(document["models"]["fees.Memo"]), 4)  # the data that was replaced

    def test_heavy_lock_is_taken_and_busy_propagates(self):
        names = []

        @contextlib.contextmanager
        def recording(name):
            names.append(name)
            yield

        with mock.patch.object(excel_restore, "heavy_operation", recording):
            restore(self.profile, build_workbook(minimal_sheets()))
            preview_workbook(build_workbook(minimal_sheets()))
        self.assertEqual(names, ["excel_restore", "excel_restore"])

        @contextlib.contextmanager
        def busy(name):
            raise Busy()
            yield  # pragma: no cover

        before = snapshot(self.profile)
        with mock.patch.object(excel_restore, "heavy_operation", busy):
            with self.assertRaises(Busy):
                restore(self.profile, build_workbook(minimal_sheets()))
            with self.assertRaises(Busy):
                preview_workbook(build_workbook(minimal_sheets()))
        self.assertEqual(snapshot(self.profile), before)


class QueryCountTests(TestCase):
    def _queries(self, name, sheets):
        profile = fees_profile(name)
        source = build_workbook(sheets)
        with CaptureQueriesContext(connection) as captured:
            restore(profile, source)
        return len(captured)

    def test_row_count_does_not_change_the_number_of_queries(self):
        small = self._queries("Q-small", minimal_sheets(5))
        big = self._queries("Q-big", minimal_sheets(300))
        self.assertLessEqual(big, small + 1)  # bulk_create batches of 500: one insert either way
        self.assertLess(small, 120)

    def test_desktop_shaped_restore_query_bound(self):
        profile = fees_profile("Q-desktop")
        with CaptureQueriesContext(connection) as captured:
            restore(profile, build_workbook(desktop_sheets()))
        # Per allocated memo there are 2 queries (recompute_paid); everything else is batched.
        self.assertLess(len(captured), 200)


class RoundTripPropertyTests(TestCase):
    """Ports ``backupService.property.test.ts``: backup then restore preserves all data (25 seeded cases)."""

    def _build(self, rng, profile):
        firm = firms.create_firm(profile, "Firm")
        group = Group.objects.get(firm=firm)
        extra_group = firms.add_group(profile, firm.pk, "P2") if rng.random() < 0.5 else None
        made = 0
        for index in range(rng.randint(1, 5)):
            chosen = extra_group if (extra_group and rng.random() < 0.5) else group
            matter = matters.create_matter(profile, firm.pk, chosen.pk, f"Matter {index}")
            for _ in range(rng.randint(1, 5)):
                day = datetime.date(2024, 4, 1) + datetime.timedelta(days=rng.randint(0, 800))
                if rng.random() < 0.15:
                    memos.save_draft(profile, {"matter_id": matter.pk, "addressee_line1": "Draft"})
                    continue
                extra = {}
                if rng.random() < 0.2:
                    extra["custom_total_fees"] = rng.randint(1, 9000)
                memo = memos.create_memo(
                    profile, memo_input(matter.pk, date=day.isoformat(), num_appearances=rng.randint(0, 4), **extra)
                )
                made += 1
                if rng.random() < 0.8:
                    payments.add_payment_to_memo(
                        profile, memo.pk,
                        {
                            "amount": rng.randint(100, 5000), "tds_rate": rng.choice([0, 10]),
                            "date_of_payment": (day + datetime.timedelta(days=5)).isoformat(),
                            "payee": f"Payer {made}", "payment_details": f"ref {rng.randint(1, 10**6)}",
                        },
                    )
        return firm, group

    def test_property_22_backup_then_restore_preserves_all_data(self):
        for seed in range(25):
            with self.subTest(seed=seed):
                rng = random.Random(seed)
                profile = fees_profile(f"prop-{seed}")
                firm, group = self._build(rng, profile)
                before = snapshot(profile)
                out = export_workbook(profile)
                # Mutate to prove the restore really replaces.
                matters.create_matter(profile, firm.pk, group.pk, "Noise Matter")
                restore(profile, out)
                out.close()
                self.assertEqual(snapshot(profile), before)
                self.assertTrue(integrity.check_profile(profile).ok)

    def test_export_restore_export_is_stable(self):
        for seed in range(100, 110):
            with self.subTest(seed=seed):
                rng = random.Random(seed)
                profile = fees_profile(f"stable-{seed}")
                self._build(rng, profile)
                first = export_workbook(profile)
                restore(profile, first)
                first.close()
                after_first = snapshot(profile)
                second = export_workbook(profile)
                restore(profile, second)
                second.close()
                self.assertEqual(snapshot(profile), after_first)


@tag("memory")
class RestoreMemoryTests(TestCase):
    def test_restore_peaks_under_40_mb_on_planning_dataset(self):
        profile = fees_profile("mem-restore")
        summary = build_planning_dataset(profile)
        out = export_workbook(profile)
        try:
            with assert_peak_under(self, 40):
                result = restore(profile, out)
        finally:
            out.close()
        self.assertEqual(result["counts"]["memos"], summary["memos"])
        self.assertEqual(result["counts"]["payments"], summary["payments"])
        self.assertEqual(result["counts"]["allocations"], summary["allocations"])
        self.assertEqual(Memo.objects.filter(profile=profile).count(), summary["memos"])
        self.assertTrue(result["fees_check"]["ok"])


class SignatureFlagRestoreTests(TestCase):
    """Per-memo include_signature comes from WebMemoFlags; an absent sheet uses the file's default."""

    def test_round_trip_keeps_the_flag_of_each_memo(self):
        source = fees_profile("Flag-Source")
        seed_web_data(source)
        ticked = Memo.objects.filter(profile=source, memo_number__isnull=False).order_by("pk").first()
        Memo.objects.filter(pk=ticked.pk).update(include_signature=True)
        target = fees_profile("Flag-Target")
        out = export_of(source)
        restore(target, out)
        out.close()
        restored = Memo.objects.get(profile=target, memo_number=ticked.memo_number)
        self.assertTrue(restored.include_signature)
        self.assertEqual(Memo.objects.filter(profile=target, include_signature=True).count(), 1)

    def test_file_without_the_sheet_uses_the_default_in_web_settings(self):
        sheets = minimal_sheets(2)
        sheets["WebSettings"] = [["key", "value"], ["memo_signature_default", 1], ["list_default_filter", "active"]]
        profile = fees_profile("Flag-Default-On")
        restore(profile, build_workbook(sheets))
        self.assertEqual(Memo.objects.filter(profile=profile, include_signature=True).count(), 2)
        saved = FeesSettings.objects.get(profile=profile)
        self.assertTrue(saved.memo_signature_default)
        self.assertEqual(saved.list_default_filter, "active")

    def test_file_without_any_web_sheet_leaves_everything_off(self):
        profile = fees_profile("Flag-Default-Off")
        restore(profile, build_workbook(minimal_sheets(2)))
        self.assertEqual(Memo.objects.filter(profile=profile, include_signature=True).count(), 0)
        saved = FeesSettings.objects.get(profile=profile)
        self.assertFalse(saved.memo_signature_default)
        self.assertEqual(saved.list_default_filter, "all")

    def test_flag_sheet_overrides_the_default_per_memo(self):
        sheets = minimal_sheets(2)
        sheets["WebMemoFlags"] = [["memo_id", "memo_number", "include_signature"], [1, None, 1], [2, None, 0]]
        profile = fees_profile("Flag-Sheet")
        restore(profile, build_workbook(sheets))
        self.assertEqual(Memo.objects.filter(profile=profile, include_signature=True).count(), 1)
