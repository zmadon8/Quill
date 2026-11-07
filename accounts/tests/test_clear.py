"""Delete all data in a profile (Admin only), and IST display of stored times."""
import datetime
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts import clear
from accounts.models import Profile, ProfileMembership, PurgeLog
from backups import services
from backups.models import BackupFile, BackupLog
from diary.importer import service
from diary.models import Case, Item, Note, NoteLink, Section, Subject, Topic, VersionHistory
from diary.tests.docx_builder import SMALL, make_docx
from diary.tests.helpers import main_profile

User = get_user_model()
PASSWORD = "correct-horse-battery-9"


def fill(profile, tag):
    """One record of every profile-scoped type, plus a trashed Subject and an imported one."""
    kw = {"profile": profile}
    subject = Subject.objects.create(name=f"S-{tag}", **kw)
    topic = Topic.objects.create(subject=subject, name=f"T-{tag}", **kw)
    Subject.objects.create(name=f"Trashed-{tag}", deleted_at=timezone.now(), **kw)
    Subject.objects.create(name=f"Imported-{tag}", import_ref=f"para-{tag}", **kw)
    section = Section.objects.create(topic=topic, name=f"Sec-{tag}", **kw)
    item = Item.objects.create(topic=topic, text="<p>x</p>", **kw)
    Case.objects.create(item=item, citation="c", **kw)
    note = Note.objects.create(item=item, text="n", **kw)
    NoteLink.objects.create(note=note, section=section, **kw)
    VersionHistory.objects.create(record_type="item", record_id=item.pk, version=1, profile=profile,
                                  change_kind="import")


@override_settings(SECURE_SSL_REDIRECT=False)
class ClearProfileTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("boss", password=PASSWORD, is_superuser=True, is_staff=True)
        self.profile = main_profile()
        self.other = Profile.objects.create(program="diary", name="Junior")
        fill(self.profile, "a")
        fill(self.other, "b")
        self.client.login(username="boss", password=PASSWORD)
        self.url = reverse("profile_clear", args=[self.profile.pk])

    def count(self, profile):
        return {name: n for name, n in clear.clear_preview(profile)}

    def test_preview_counts_every_type_including_trashed_and_imported(self):
        counts = self.count(self.profile)
        self.assertEqual(counts["Subjects"], 3)
        self.assertEqual(counts["Topics"], 1)
        self.assertEqual(counts["Items"], 1)
        resp = self.client.get(self.url)
        self.assertContains(resp, "Subjects")
        self.assertContains(resp, "Type the profile name")

    def test_admin_only(self):
        User.objects.create_user("alice", password=PASSWORD)
        self.client.logout()
        self.client.login(username="alice", password=PASSWORD)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {"confirm": self.profile.name}).status_code, 403)
        self.assertTrue(Subject.objects.filter(profile=self.profile).exists())

    def test_wrong_confirmation_deletes_nothing(self):
        before = BackupFile.objects.count()
        for typed in ("", "main", "Junior"):
            self.client.post(self.url, {"confirm": typed})
        self.assertEqual(Subject.objects.filter(profile=self.profile).count(), 3)
        self.assertEqual(BackupFile.objects.count(), before)

    def test_clear_deletes_everything_of_the_profile_and_only_that(self):
        other_before = self.count(self.other)
        resp = self.client.post(self.url, {"confirm": self.profile.name})
        self.assertRedirects(resp, reverse("profile_list"))
        self.assertTrue(all(n == 0 for n in self.count(self.profile).values()))
        self.assertEqual(self.count(self.other), other_before)
        self.assertTrue(Profile.objects.filter(pk=self.profile.pk, deleted_at__isnull=True).exists())

    def test_profile_and_memberships_are_kept(self):
        member = User.objects.create_user("carol", password=PASSWORD)
        ProfileMembership.objects.create(user=member, profile=self.profile, program="diary", role="reader")
        self.profile.export_name = "My Diary"
        self.profile.save()
        self.client.post(self.url, {"confirm": self.profile.name})
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.export_name, "My Diary")
        self.assertTrue(ProfileMembership.objects.filter(profile=self.profile, user=member).exists())

    def test_backup_is_made_first_kept_from_pruning_and_logged(self):
        self.client.post(self.url, {"confirm": self.profile.name})
        backup = BackupFile.objects.get(kind="pre_clear")
        self.assertEqual(backup.get_kind_display(), "Before clearing profile")
        self.assertEqual(backup.record_counts["diary.Subject"], 6)
        services.create_backup("daily")
        services.prune_old_backups()
        self.assertTrue(BackupFile.objects.filter(pk=backup.pk).exists())
        log = PurgeLog.objects.get()
        self.assertTrue(log.success)
        self.assertEqual(log.counts["diary.Subject"], 3)
        self.assertTrue(BackupLog.objects.filter(kind="pre_clear", success=True).exists())

    def test_failed_backup_aborts_with_nothing_deleted(self):
        with mock.patch("accounts.clear.services.create_backup", side_effect=RuntimeError("disk full")):
            resp = self.client.post(self.url, {"confirm": self.profile.name}, follow=True)
        self.assertContains(resp, "nothing was deleted")
        self.assertEqual(Subject.objects.filter(profile=self.profile).count(), 3)
        self.assertEqual(PurgeLog.objects.count(), 0)

    def test_change_between_backup_and_delete_aborts_with_nothing_deleted(self):
        real = services.create_backup

        def backup_then_write(*args, **kwargs):
            result = real(*args, **kwargs)
            Subject.objects.create(name="Late arrival", profile=self.profile)
            return result

        with mock.patch("accounts.clear.services.create_backup", side_effect=backup_then_write):
            with self.assertRaises(clear.ClearRefused) as caught:
                clear.clear_profile(self.profile, self.admin)
        self.assertIn("changed while the backup was being taken", str(caught.exception))
        self.assertEqual(Subject.objects.filter(profile=self.profile).count(), 4)
        self.assertEqual(Item.objects.filter(profile=self.profile).count(), 1)
        self.assertEqual(PurgeLog.objects.count(), 0)

    def test_blocked_while_an_import_holds_the_profile(self):
        with mock.patch("accounts.clear.Profile.objects.select_for_update", side_effect=DatabaseError("locked")):
            with self.assertRaises(clear.ClearRefused) as caught:
                clear.clear_profile(self.profile, self.admin)
        self.assertIn("import", str(caught.exception))
        self.assertEqual(Subject.objects.filter(profile=self.profile).count(), 3)

    def test_import_is_possible_afterwards(self):
        data = make_docx(SMALL)
        with self.assertRaises(service.ImportRefused):
            service.run_import(data, "small.docx", self.profile)
        self.client.post(self.url, {"confirm": self.profile.name})
        service.run_import(data, "small.docx", self.profile)
        self.assertEqual(Subject.objects.filter(profile=self.profile, import_ref__gt="").count(), 4)

    def test_import_ref_rows_do_not_block_a_second_import_after_clear(self):
        data = make_docx(SMALL)
        clear.clear_profile(self.profile, self.admin)
        service.run_import(data, "small.docx", self.profile)
        Subject.objects.filter(profile=self.profile).update(deleted_at=timezone.now())
        clear.clear_profile(self.profile, self.admin)
        service.run_import(data, "small.docx", self.profile)


@override_settings(SECURE_SSL_REDIRECT=False)
class IstDisplayTests(TestCase):
    def test_stored_utc_time_shows_as_ist_wall_clock(self):
        admin = User.objects.create_user("boss", password=PASSWORD, is_superuser=True, is_staff=True)
        self.client.login(username="boss", password=PASSWORD)
        stamp = datetime.datetime(2026, 1, 5, 20, 0, tzinfo=datetime.timezone.utc)  # 01:30 next day in IST
        backup = services.create_backup("manual", admin)
        BackupFile.objects.filter(pk=backup.pk).update(created_at=stamp)
        BackupLog.objects.filter(backup=backup).update(started_at=stamp)
        resp = self.client.get(reverse("backup_list"))
        self.assertContains(resp, "2026-01-06 01:30")
        self.assertNotContains(resp, "2026-01-05 20:00")
        self.assertContains(resp, "Time (IST)")
        self.assertNotContains(resp, "UTC")
        self.assertContains(self.client.get(reverse("restore_preview", args=[backup.pk])), "2026-01-06 01:30 IST")

    def test_file_names_and_reports_use_ist(self):
        stamp = datetime.datetime(2026, 1, 5, 20, 0, tzinfo=datetime.timezone.utc)
        with mock.patch("django.utils.timezone.now", return_value=stamp):
            backup = services.create_backup("manual")
            self.assertIn("20260106-013000", backup.filename)
            self.assertIn("2026-01-06 01:30:00 IST", service._now())
