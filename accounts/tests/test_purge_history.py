"""Edit history is kept for HISTORY_RETENTION_DAYS; the nightly purge keeps each record's newest version."""
import uuid
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, PurgeLog
from accounts.purge import purge_old_history
from backups import services
from backups.models import BackupLog
from diary.models import VersionHistory
from diary.tests.helpers import join_main, main_profile

User = get_user_model()


def vh(profile, record_id, version, days_ago, group=None, record_type="item"):
    row = VersionHistory.objects.create(
        record_type=record_type, record_id=record_id, version=version, profile=profile, change_kind="edit", group=group
    )
    VersionHistory.objects.filter(pk=row.pk).update(changed_at=timezone.now() - timedelta(days=days_ago))
    return row.pk


@override_settings(SECURE_SSL_REDIRECT=False, HISTORY_RETENTION_DAYS=30)
class PurgeOldHistoryTests(TestCase):
    def setUp(self):
        self.profile = main_profile()
        self.other = Profile.objects.create(program="diary", name="Junior")

    def versions(self, profile=None):
        return set(VersionHistory.objects.filter(profile=profile or self.profile).values_list("record_id", "version"))

    def test_old_removed_newest_and_recent_kept(self):
        vh(self.profile, 1, 1, 90)  # old, not newest: goes
        vh(self.profile, 1, 2, 60)  # old, not newest: goes
        vh(self.profile, 1, 3, 40)  # old but the newest: stays
        vh(self.profile, 2, 1, 40)  # old, goes
        vh(self.profile, 2, 2, 5)  # recent: stays
        services.create_backup("daily")
        log = purge_old_history()
        self.assertTrue(log.success)
        self.assertEqual(log.counts, {"diary.VersionHistory": 3})
        self.assertEqual(self.versions(), {(1, 3), (2, 2)})

    def test_other_profiles_are_judged_separately_and_kept_newest(self):
        vh(self.profile, 7, 1, 90)
        vh(self.other, 7, 1, 90)  # same record id in another profile: its own newest, stays
        vh(self.other, 7, 2, 40)
        services.create_backup("daily")
        purge_old_history()
        self.assertEqual(self.versions(self.profile), {(7, 1)})
        self.assertEqual(self.versions(self.other), {(7, 2)})

    def test_rows_in_a_recent_undo_group_are_kept(self):
        group = uuid.uuid4()
        vh(self.profile, 1, 1, 90)
        vh(self.profile, 1, 2, 40, group=group)  # old row of a group...
        vh(self.profile, 1, 3, 2, group=group)  # ...that has a recent row
        vh(self.profile, 4, 1, 40, group=group)
        vh(self.profile, 4, 2, 1)
        services.create_backup("daily")
        purge_old_history()
        self.assertEqual(self.versions(), {(1, 2), (1, 3), (4, 1), (4, 2)})

    def test_no_purge_when_backup_failed_or_missing(self):
        vh(self.profile, 1, 1, 90)
        vh(self.profile, 1, 2, 90)
        log = purge_old_history()
        self.assertFalse(log.success)
        BackupLog.objects.create(kind="daily", success=False, message="boom")
        self.assertFalse(purge_old_history().success)
        self.assertEqual(len(self.versions()), 2)
        with self.assertRaises(CommandError):
            call_command("purge_old_history", stdout=StringIO())

    def test_idempotent_and_quiet_when_nothing_due(self):
        vh(self.profile, 1, 1, 90)
        vh(self.profile, 1, 2, 90)
        services.create_backup("daily")
        self.assertTrue(purge_old_history().success)
        before = PurgeLog.objects.count()
        self.assertIsNone(purge_old_history())
        self.assertEqual(PurgeLog.objects.count(), before)
        out = StringIO()
        call_command("purge_old_history", stdout=out)
        self.assertIn("No edit history", out.getvalue())

    def test_window_follows_the_setting(self):
        vh(self.profile, 1, 1, 10)
        vh(self.profile, 1, 2, 10)
        services.create_backup("daily")
        self.assertIsNone(purge_old_history())
        with override_settings(HISTORY_RETENTION_DAYS=7):
            self.assertTrue(purge_old_history().success)
        self.assertEqual(self.versions(), {(1, 2)})

    def test_history_page_states_the_window(self):
        from diary.models import Subject

        user = join_main(User.objects.create_user("ed", password="correct-horse-battery-9"), "editor")
        subject = Subject.objects.create(profile=self.profile, name="S")
        vh(self.profile, subject.pk, 1, 0, record_type="subject")
        self.client.force_login(user)
        resp = self.client.get(reverse("history", args=["subject", subject.pk]))
        self.assertContains(resp, "Edit history is kept for 30 days")
