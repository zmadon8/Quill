"""Clear-all tests (T4.4, R-SET-5, ports ``clearAllData``).

Typed confirmation (the profile name), a ``pre_clear`` suite backup first, the heavy lock, deleting
only this profile's rows child first, the settings row reset, ``data_version`` bump and cache purge,
and that the Word template and every other profile are left alone.
"""
import base64
import contextlib
import gzip
import json
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from accounts.models import Profile
from accounts.suite import KEY_FEES
from backups.models import BackupFile
from fees.errors import FeesError, status_for
from fees.models import (
    Allocation,
    BankAccount,
    FeesSettings,
    Firm,
    Group,
    Matter,
    Memo,
    NumberSequence,
    Payment,
    PeriodAdjustment,
    SavedView,
    StatsCache,
    WordTemplate,
)
from fees.services import clear_all as clear_module
from fees.services import integrity
from fees.services.clear_all import clear_all
from fees.services.heavy import Busy
from fees.tests.xlsx_support import MEMO_TEXT_DEFAULTS, SIGNATURE_BYTES, no_backup, seed_web_data, snapshot

DATA_MODELS = (
    Firm, Group, Matter, Memo, Payment, Allocation, PeriodAdjustment, SavedView, BankAccount, NumberSequence,
)


def fees_profile(name):
    return Profile.objects.create(program=KEY_FEES, name=name)


def counts(profile):
    return {model.__name__: model.objects.filter(profile=profile).count() for model in DATA_MODELS}


class ClearAllTests(TestCase):
    def setUp(self):
        self.profile = fees_profile("Clear-Me")
        self.other = fees_profile("Keep-Me")
        seed_web_data(self.profile)
        seed_web_data(self.other)
        self.other_before = snapshot(self.other)

    def test_confirmation_must_be_the_profile_name(self):
        before = counts(self.profile)
        calls = []
        for typed in ("", None, "clear-me", "Keep-Me", "Clear", "yes"):
            with self.assertRaises(FeesError) as ctx:
                clear_all(self.profile, typed, backup_func=lambda k, u: calls.append(k))
            self.assertEqual(ctx.exception.code, "INVALID_CONFIRMATION")
            self.assertEqual(ctx.exception.status, 422)
        self.assertEqual(calls, [])
        self.assertEqual(counts(self.profile), before)

    def test_clears_only_this_profile_and_resets_settings(self):
        StatsCache.objects.create(profile=self.profile, kind="x", params_hash="h", data_version=0, payload={})
        version = FeesSettings.objects.get(profile=self.profile).data_version
        result = clear_all(self.profile, "  Clear-Me  ", backup_func=no_backup)
        for name, number in counts(self.profile).items():
            self.assertEqual(number, 0, name)
        self.assertEqual(result["counts"]["fees.Memo"], 4)
        self.assertEqual(result["counts"]["fees.Allocation"], 3)
        self.assertEqual(result["counts"]["fees.Firm"], 2)
        self.assertIsNone(result["backup_id"])
        # The other profile is untouched.
        self.assertEqual(snapshot(self.other), self.other_before)
        # Settings are back to defaults (even the memo text defaults), the version keeps counting up.
        saved = FeesSettings.objects.get(profile=self.profile)
        self.assertEqual(saved.export_owner_name, "Ziyad Madon")
        self.assertEqual(saved.overdue_days, 0)
        self.assertTrue(saved.statistics_enabled)
        for key in MEMO_TEXT_DEFAULTS:
            self.assertEqual(getattr(saved, key), "")
        self.assertGreater(saved.data_version, version)
        self.assertFalse(StatsCache.objects.filter(profile=self.profile).exists())
        # The profile stays, and so does the uploaded Word template with its signature.
        self.assertTrue(Profile.objects.filter(pk=self.profile.pk).exists())
        template = WordTemplate.objects.get(profile=self.profile)
        self.assertEqual(bytes(template.signature_data), SIGNATURE_BYTES)
        report = integrity.check_profile(self.profile)
        self.assertTrue(report.ok)
        self.assertEqual(report.memos_checked, 0)

    def test_pre_clear_suite_backup_is_made_first_and_holds_the_data(self):
        seen = []

        def stub(kind, user):
            seen.append((kind, user, counts(self.profile)["Memo"]))

        clear_all(self.profile, "Clear-Me", user="U", backup_func=stub)
        self.assertEqual(seen, [("pre_clear", "U", 4)])  # all rows were still there when it ran

        # With the real helper a pre_clear BackupFile is stored and carries the rows and the signature.
        self.profile2 = fees_profile("Clear-Real")
        seed_web_data(self.profile2)
        result = clear_all(self.profile2, "Clear-Real")
        stored = BackupFile.objects.get(kind="pre_clear")
        self.assertEqual(result["backup_id"], stored.pk)
        document = json.loads(gzip.decompress(bytes(stored.data)).decode("utf-8"))
        mine = [r for r in document["models"]["fees.Memo"] if r["fields"]["profile"] == self.profile2.pk]
        self.assertEqual(len(mine), 4)
        template = [r for r in document["models"]["fees.WordTemplate"] if r["fields"]["profile"] == self.profile2.pk]
        self.assertEqual(base64.b64decode(template[0]["fields"]["signature_data"]), SIGNATURE_BYTES)

    def test_failed_backup_deletes_nothing(self):
        before = counts(self.profile)

        def boom(kind, user):
            raise RuntimeError("disk full")

        with self.assertRaises(FeesError) as ctx:
            clear_all(self.profile, "Clear-Me", backup_func=boom)
        self.assertEqual(ctx.exception.code, "CLEAR_FAILED")
        self.assertEqual(ctx.exception.status, 500)
        self.assertEqual(status_for("CLEAR_FAILED"), 500)
        self.assertIn("nothing was deleted", ctx.exception.message)
        self.assertEqual(counts(self.profile), before)

    def test_failure_while_deleting_rolls_back(self):
        before = counts(self.profile)
        with mock.patch.object(clear_module, "reset_settings", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                clear_all(self.profile, "Clear-Me", backup_func=no_backup)
        self.assertEqual(counts(self.profile), before)

    def test_heavy_lock_is_taken_and_busy_propagates(self):
        names = []

        @contextlib.contextmanager
        def recording(name):
            names.append(name)
            yield

        with mock.patch.object(clear_module, "heavy_operation", recording):
            clear_all(self.profile, "Clear-Me", backup_func=no_backup)
        self.assertEqual(names, ["clear_all"])

        @contextlib.contextmanager
        def busy(name):
            raise Busy()
            yield  # pragma: no cover

        before = counts(self.other)
        with mock.patch.object(clear_module, "heavy_operation", busy):
            with self.assertRaises(Busy):
                clear_all(self.other, "Keep-Me", backup_func=no_backup)
        self.assertEqual(counts(self.other), before)

    def test_clearing_an_empty_profile_works_and_creates_the_settings_row(self):
        empty = fees_profile("Empty-Clear")
        result = clear_all(empty, "Empty-Clear", backup_func=no_backup)
        self.assertEqual(sum(result["counts"].values()), 0)
        self.assertTrue(FeesSettings.objects.filter(profile=empty).exists())


class ClearAllQueryTests(TestCase):
    def _queries(self, name, memo_count):
        profile = fees_profile(name)
        firm = Firm.objects.create(profile=profile, name="F")
        group = Group.objects.create(profile=profile, firm=firm, name="G")
        matter = Matter.objects.create(profile=profile, firm=firm, group=group, name="M")
        Memo.objects.bulk_create(
            [
                Memo(profile=profile, financial_year="2026-27", matter=matter, firm=firm, group=group,
                     addressee_line1="A", memo_number=f"{name}/{i}")
                for i in range(memo_count)
            ]
        )
        with CaptureQueriesContext(connection) as captured:
            clear_all(profile, name, backup_func=no_backup)
        return len(captured)

    def test_deleting_many_rows_does_not_add_queries(self):
        small = self._queries("Q-small", 5)
        big = self._queries("Q-big", 400)
        # Django's delete collector looks up related rows in chunks of 100
        # ids per related model, so 400 rows cost a few more queries than
        # 5 rows. That small constant growth is expected; a per-row N+1
        # would add about 400 queries.
        self.assertLessEqual(big, small + 20)
        self.assertLess(small, 80)
