"""Fee Register in the suite backup, the pre-fees restore guard and program-aware purge/clear (T1.9).

Covers design 7.4 and requirements R-BK-4 and R-BK-5:

* fee rows survive a suite backup then restore (round trip through the real streaming writer);
* restoring a file that lacks the fee models while the database holds fee rows shows the "will be
  emptied" warning, is refused when only the confirm word is given, and proceeds with the extra tick;
* purge of a fees profile deletes only that profile's fee rows (and the profile), leaving diary data;
* clear of a fees profile deletes only that profile's fee rows and keeps the profile and diary data;
* a diary profile's purge/clear is unchanged;
* a memory gate: a suite backup carrying a planning-size fee dataset stays under 15 MB.
"""
import datetime
import gzip
import hashlib
import json
import tracemalloc
from contextlib import contextmanager

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings, tag
from django.urls import reverse
from django.utils import timezone

from accounts import clear, purge
from accounts.models import Profile, ProfileMembership
from accounts.suite import KEY_FEES
from backups import services
from backups.models import BackupFile, BackupLog
from diary.models import Subject
from diary.tests.helpers import main_profile
from fees.models import (
    Allocation,
    BankAccount,
    Firm,
    Group,
    Matter,
    Memo,
    Payment,
)

User = get_user_model()
PASSWORD = "correct-horse-battery-9"
MAX = 30 * 1024 * 1024
FEE_LABELS = [
    "fees.FeesSettings",
    "fees.WordTemplate",
    "fees.BankAccount",
    "fees.Firm",
    "fees.Group",
    "fees.Matter",
    "fees.Memo",
    "fees.NumberSequence",
    "fees.Payment",
    "fees.Allocation",
    "fees.PeriodAdjustment",
    "fees.SavedView",
]


def gunzip_json(raw):
    return json.loads(gzip.decompress(bytes(raw)).decode("utf-8"))


def make_fee_data(profile):
    """Build a small, fully linked fee dataset in ``profile`` and return the created objects."""
    firm = Firm.objects.create(profile=profile, name="Acme LLP")
    group = Group.objects.create(profile=profile, firm=firm, name="Litigation")
    matter = Matter.objects.create(profile=profile, firm=firm, group=group, name="Suit 42")
    bank = BankAccount.objects.create(profile=profile, name="Current account")
    memo = Memo.objects.create(
        profile=profile,
        financial_year="2026-27",
        date=datetime.date(2026, 5, 1),
        matter=matter,
        firm=firm,
        group=group,
        addressee_line1="Acme LLP",
        total_fees=1000,
    )
    payment = Payment.objects.create(
        profile=profile, amount=500, date_of_payment=datetime.date(2026, 5, 10), bank_account=bank
    )
    allocation = Allocation.objects.create(
        payment=payment, memo=memo, profile=profile, amount=500
    )
    return {
        "firm": firm,
        "group": group,
        "matter": matter,
        "bank": bank,
        "memo": memo,
        "payment": payment,
        "allocation": allocation,
    }


@override_settings(SECURE_SSL_REDIRECT=False)
class FeeRowsSurviveBackupRestoreTests(TestCase):
    """R-BK-4: fee rows are written to the backup and come back on restore with the same data."""

    def setUp(self):
        self.admin = User.objects.create_user("boss", password=PASSWORD, is_superuser=True, is_staff=True)
        self.fees_profile = Profile.objects.create(program=KEY_FEES, name="Chambers")
        ProfileMembership.objects.create(user=self.admin, profile=self.fees_profile, role="editor")
        self.objects = make_fee_data(self.fees_profile)

    def test_fees_models_are_written_to_the_backup(self):
        backup = services.create_backup("manual", self.admin)
        document = gunzip_json(backup.data)
        for label in FEE_LABELS:
            self.assertIn(label, document["models"])
        self.assertEqual(backup.record_counts["fees.Firm"], 1)
        self.assertEqual(backup.record_counts["fees.Memo"], 1)
        self.assertEqual(backup.record_counts["fees.Allocation"], 1)
        # StatsCache is derived data and is never in a backup.
        self.assertNotIn("fees.StatsCache", document["models"])

    def test_fee_rows_round_trip_through_a_restore(self):
        backup = services.create_backup("manual", self.admin)
        document = services.parse_backup(backup.data, MAX)
        Allocation.objects.all().delete()
        Payment.objects.all().delete()
        Memo.objects.all().delete()
        Matter.objects.all().delete()
        Group.objects.all().delete()
        Firm.objects.all().delete()
        BankAccount.objects.all().delete()
        self.assertEqual(Firm.objects.count(), 0)
        services.restore_backup(document, self.admin)
        self.assertEqual(Firm.objects.count(), 1)
        self.assertEqual(Memo.objects.count(), 1)
        self.assertEqual(Allocation.objects.count(), 1)
        memo = Memo.objects.get()
        self.assertEqual(memo.total_fees, self.objects["memo"].total_fees)
        self.assertEqual(memo.addressee_line1, "Acme LLP")
        allocation = Allocation.objects.get()
        self.assertEqual(allocation.amount, 500)
        self.assertEqual(allocation.memo_id, memo.pk)


@override_settings(SECURE_SSL_REDIRECT=False)
class PreFeesRestoreGuardTests(TestCase):
    """A file taken before the Fee Register existed lacks the fee sections (R-BK-4)."""

    def setUp(self):
        self.admin = User.objects.create_user("boss", password=PASSWORD, is_superuser=True, is_staff=True)
        self.fees_profile = Profile.objects.create(program=KEY_FEES, name="Chambers")
        ProfileMembership.objects.create(user=self.admin, profile=self.fees_profile, role="editor")
        self.objects = make_fee_data(self.fees_profile)
        self.client.login(username="boss", password=PASSWORD)

    def _store_pre_fees_backup(self):
        """Take a real backup, strip every fee section (as an older file would be), and store it."""
        document = gunzip_json(services.create_backup("manual", self.admin).data)
        for label in FEE_LABELS:
            document["models"].pop(label, None)
            document.get("counts", {}).pop(label, None)
        raw = gzip.compress(json.dumps(document).encode("utf-8"))
        return BackupFile.objects.create(
            kind="uploaded",
            filename="pre-fees-backup.json.gz",
            data=raw,
            size_bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            record_counts=document.get("counts", {}),
            created_by=self.admin,
        )

    def test_will_empty_lists_the_fee_record_types(self):
        document = services.parse_backup(self._store_pre_fees_backup().data, MAX)
        warnings = services.models_that_would_empty(document)
        labels = {w["label"] for w in warnings}
        # Only the fee types that currently have rows are listed.
        self.assertIn("fees.Firm", labels)
        self.assertIn("fees.Memo", labels)
        self.assertIn("fees.Allocation", labels)
        for w in warnings:
            self.assertEqual(w["program"], "Fee Register")
            self.assertGreater(w["count_now"], 0)

    def test_preview_page_shows_the_warning_box(self):
        backup = self._store_pre_fees_backup()
        response = self.client.get(reverse("restore_preview", args=[backup.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["will_empty"])
        self.assertContains(response, "will be emptied")
        self.assertContains(response, 'name="empty_confirm"')

    def test_restore_is_refused_without_the_extra_tick(self):
        backup = self._store_pre_fees_backup()
        response = self.client.post(
            reverse("restore_preview", args=[backup.pk]), {"confirm": "RESTORE"}
        )
        self.assertEqual(response.status_code, 302)
        # Nothing was emptied: the fee rows are all still present.
        self.assertEqual(Firm.objects.count(), 1)
        self.assertEqual(Memo.objects.count(), 1)
        self.assertEqual(Allocation.objects.count(), 1)
        # No restore ran.
        self.assertFalse(BackupLog.objects.filter(kind="restore").exists())

    def test_restore_proceeds_with_the_extra_tick(self):
        backup = self._store_pre_fees_backup()
        response = self.client.post(
            reverse("restore_preview", args=[backup.pk]),
            {"confirm": "RESTORE", "empty_confirm": "yes"},
        )
        self.assertEqual(response.status_code, 302)
        # The file had no fee rows, so after the restore the fee tables are empty, and the diary is intact.
        self.assertEqual(Firm.objects.count(), 0)
        self.assertEqual(Memo.objects.count(), 0)
        self.assertEqual(Allocation.objects.count(), 0)
        self.assertTrue(BackupLog.objects.filter(kind="restore", success=True).exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class ProgramAwarePurgeClearTests(TestCase):
    """R-BK-5: purge and clear of a fees profile touch only fee rows; the diary is unchanged."""

    def setUp(self):
        self.admin = User.objects.create_user("boss", password=PASSWORD, is_superuser=True, is_staff=True)
        self.diary_profile = main_profile()
        self.fees_profile = Profile.objects.create(program=KEY_FEES, name="Chambers")
        ProfileMembership.objects.create(user=self.admin, profile=self.fees_profile, role="editor")
        Subject.objects.create(profile=self.diary_profile, name="Keep me")
        self.objects = make_fee_data(self.fees_profile)

    def test_clearing_a_fees_profile_deletes_only_fee_rows(self):
        counts = clear.clear_profile(self.fees_profile, self.admin)
        self.assertEqual(Firm.objects.filter(profile=self.fees_profile).count(), 0)
        self.assertEqual(Memo.objects.filter(profile=self.fees_profile).count(), 0)
        self.assertEqual(Allocation.objects.filter(profile=self.fees_profile).count(), 0)
        # The clear reports fee rows removed.
        self.assertEqual(counts.get("fees.Firm"), 1)
        self.assertEqual(counts.get("fees.Memo"), 1)
        # The profile row and the diary are untouched.
        self.assertTrue(Profile.objects.filter(pk=self.fees_profile.pk).exists())
        self.assertEqual(Subject.objects.filter(profile=self.diary_profile).count(), 1)

    def test_purging_a_fees_profile_deletes_its_fee_rows_and_the_profile(self):
        self.fees_profile.deleted_at = timezone.now() - datetime.timedelta(days=400)
        self.fees_profile.save(update_fields=["deleted_at"])
        # The profile purge refuses unless a backup succeeded today; take one.
        services.create_backup("manual", self.admin)
        log = purge.purge_expired_profiles()
        self.assertTrue(log.success)
        self.assertFalse(Profile.objects.filter(pk=self.fees_profile.pk).exists())
        self.assertEqual(Firm.objects.count(), 0)
        self.assertEqual(Memo.objects.count(), 0)
        self.assertEqual(Allocation.objects.count(), 0)
        # The diary profile and its data are untouched.
        self.assertEqual(Subject.objects.filter(profile=self.diary_profile).count(), 1)

    def test_clearing_a_diary_profile_is_unchanged(self):
        counts = clear.clear_profile(self.diary_profile, self.admin)
        # The diary profile's own Subject is gone; the fee profile's rows are untouched.
        self.assertEqual(Subject.objects.filter(profile=self.diary_profile).count(), 0)
        self.assertEqual(counts.get("diary.Subject"), 1)
        self.assertEqual(Firm.objects.filter(profile=self.fees_profile).count(), 1)
        self.assertEqual(Memo.objects.filter(profile=self.fees_profile).count(), 1)


@contextmanager
def assert_peak_under(testcase, mb):
    """Assert peak Python allocations inside the block stay under ``mb`` megabytes (tracemalloc)."""
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        yield
        _current, peak = tracemalloc.get_traced_memory()
        snapshot = tracemalloc.take_snapshot()
    finally:
        tracemalloc.stop()
    limit = mb * 1024 * 1024
    if peak > limit:
        top = snapshot.statistics("lineno")[:10]
        report = "\n".join(str(line) for line in top)
        testcase.fail(
            f"peak {peak / 1024 / 1024:.1f} MB exceeded the {mb} MB cap.\nTop allocations:\n{report}"
        )


@tag("memory")
@override_settings(SECURE_SSL_REDIRECT=False)
class FeesBackupMemoryTests(TestCase):
    """Peak Python allocations during a suite backup carrying a planning-size fee dataset stay under 15 MB.

    Tagged ``memory``: excluded locally with ``--exclude-tag=memory`` and run in CI. The threshold
    carries the RAM budget margin; the authoritative number is measured by CI on Postgres.
    """

    def setUp(self):
        self.admin = User.objects.create_user("boss", password=PASSWORD, is_superuser=True, is_staff=True)
        self.profile = Profile.objects.create(program=KEY_FEES, name="Bulk")
        ProfileMembership.objects.create(user=self.admin, profile=self.profile, role="editor")
        firm = Firm.objects.create(profile=self.profile, name="Bulk firm")
        group = Group.objects.create(profile=self.profile, firm=firm, name="Bulk group")
        matter = Matter.objects.create(profile=self.profile, firm=firm, group=group, name="Bulk matter")
        memos = [
            Memo(
                profile=self.profile,
                financial_year="2026-27",
                date=datetime.date(2026, 5, 1),
                matter=matter,
                firm=firm,
                group=group,
                addressee_line1=f"Addressee {n}",
                total_fees=1000,
            )
            for n in range(4000)
        ]
        Memo.objects.bulk_create(memos, batch_size=500)

    def test_suite_backup_with_fees_peak_under_15mb(self):
        with assert_peak_under(self, 15):
            backup = services.create_backup("manual", self.admin)
        self.assertEqual(backup.record_counts["fees.Memo"], 4000)
