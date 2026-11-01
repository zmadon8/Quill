import gzip
import hashlib
import json
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from backups import services
from backups.management.commands import migrate_with_backup
from backups.models import BackupFile, BackupLog

User = get_user_model()
PASSWORD = "correct-horse-battery-9"
MAX = 10 * 1024 * 1024


def gunzip_json(raw):
    return json.loads(gzip.decompress(bytes(raw)).decode("utf-8"))


def set_age(backup, days):
    BackupFile.objects.filter(pk=backup.pk).update(created_at=timezone.now() - timedelta(days=days))


@override_settings(SECURE_SSL_REDIRECT=False)
class BackupBase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("boss", password=PASSWORD, is_superuser=True, is_staff=True)
        self.alice = User.objects.create_user("alice", password=PASSWORD)
        self.bob = User.objects.create_user("bob", password=PASSWORD)

    def usernames(self):
        return set(User.objects.values_list("username", flat=True))

    def login_admin(self):
        self.client.login(username="boss", password=PASSWORD)


class CreateBackupTests(BackupBase):
    def test_create_backup_contents_and_log(self):
        backup = services.create_backup("manual", self.admin)
        doc = gunzip_json(backup.data)
        self.assertEqual(doc["format"], "judgment-diary-backup")
        self.assertEqual(doc["format_version"], 1)
        self.assertEqual(doc["counts"], {"accounts.User": 3})
        names = {r["fields"]["username"] for r in doc["models"]["accounts.User"]}
        self.assertEqual(names, {"boss", "alice", "bob"})
        self.assertTrue(backup.filename.startswith("judgment-diary-backup-"))
        self.assertTrue(backup.filename.endswith("-manual.json.gz"))
        self.assertEqual(backup.sha256, hashlib.sha256(bytes(backup.data)).hexdigest())
        self.assertEqual(backup.size_bytes, len(bytes(backup.data)))
        log = BackupLog.objects.get()
        self.assertTrue(log.success)
        self.assertEqual(log.kind, "manual")
        self.assertEqual(log.backup, backup)

    def test_backup_excludes_its_own_tables(self):
        services.create_backup("daily")
        second = services.create_backup("daily")
        doc = gunzip_json(second.data)
        self.assertEqual(list(doc["models"]), ["accounts.User"])

    def test_failure_writes_failed_log_and_reraises(self):
        with mock.patch("backups.services.serializers.serialize", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                services.create_backup("manual", self.admin)
        self.assertEqual(BackupFile.objects.count(), 0)
        log = BackupLog.objects.get()
        self.assertFalse(log.success)
        self.assertIn("boom", log.message)


class RunBackupCommandTests(BackupBase):
    def test_run_backup_creates_daily_backup(self):
        out = StringIO()
        call_command("run_backup", stdout=out)
        self.assertEqual(BackupFile.objects.filter(kind="daily").count(), 1)
        self.assertIn("Daily backup OK", out.getvalue())
        self.assertTrue(BackupLog.objects.filter(kind="prune", success=True).exists())

    def test_run_backup_failure_raises_command_error(self):
        with mock.patch("backups.services.serializers.serialize", side_effect=RuntimeError("boom")):
            with self.assertRaises(CommandError):
                call_command("run_backup", stdout=StringIO())
        self.assertTrue(BackupLog.objects.filter(kind="daily", success=False).exists())


class RetentionTests(BackupBase):
    def test_prune_keeps_recent_and_newest(self):
        ages = {10: None, 29: None, 31: None, 40: None, 100: None}
        for days in ages:
            ages[days] = services.create_backup("daily")
            set_age(ages[days], days)
        removed = services.prune_old_backups()
        self.assertEqual(removed, 2)
        remaining = set(BackupFile.objects.values_list("pk", flat=True))
        self.assertEqual(remaining, {ages[10].pk, ages[29].pk, ages[31].pk})
        self.assertTrue(BackupLog.objects.filter(kind="prune", success=True).exists())

    def test_prune_never_leaves_zero_backups(self):
        only = services.create_backup("daily")
        set_age(only, 500)
        self.assertEqual(services.prune_old_backups(), 0)
        self.assertEqual(BackupFile.objects.count(), 1)

    def test_prune_failure_is_logged_not_raised(self):
        services.create_backup("daily")
        with mock.patch("backups.services.policy.select_expired", side_effect=RuntimeError("bad")):
            self.assertEqual(services.prune_old_backups(), 0)
        self.assertTrue(BackupLog.objects.filter(kind="prune", success=False).exists())


class ParseTests(BackupBase):
    def test_rejects_garbage(self):
        with self.assertRaises(services.BackupError):
            services.parse_backup(b"not a gzip file", MAX)

    def test_rejects_wrong_json(self):
        with self.assertRaises(services.BackupError):
            services.parse_backup(gzip.compress(b'{"hello": 1}'), MAX)

    def test_rejects_unknown_model(self):
        doc = gunzip_json(services.create_backup("daily").data)
        doc["models"]["auth.Group"] = []
        with self.assertRaises(services.BackupError):
            services.parse_backup(gzip.compress(json.dumps(doc).encode()), MAX)

    def test_rejects_too_large_when_decompressed(self):
        raw = services.create_backup("daily").data
        with self.assertRaises(services.BackupError):
            services.parse_backup(raw, 50)

    def test_accepts_valid_backup(self):
        raw = services.create_backup("daily").data
        self.assertEqual(services.parse_backup(raw, MAX)["format_version"], 1)


class RestoreServiceTests(BackupBase):
    def test_preview_counts(self):
        raw = services.create_backup("daily").data
        doc = services.parse_backup(raw, MAX)
        User.objects.create_user("carol", password=PASSWORD)
        User.objects.filter(pk=self.bob.pk).delete()
        (row,) = services.preview_restore(doc)
        self.assertEqual(row["label"], "accounts.User")
        self.assertEqual(row["in_file"], 3)
        self.assertEqual(row["in_database_now"], 3)
        self.assertEqual(row["would_be_added"], 1)
        self.assertEqual(row["would_be_removed"], 1)
        self.assertEqual(row["unchanged_or_overwritten"], 2)
        self.assertEqual(row["added_names"], ["bob"])
        self.assertEqual(row["removed_names"], ["carol"])

    def test_round_trip(self):
        self.alice.is_active = False
        self.alice.save()
        original = {u.username: (u.password, u.is_superuser, u.is_active) for u in User.objects.all()}
        doc = services.parse_backup(services.create_backup("manual").data, MAX)

        User.objects.create_user("carol", password=PASSWORD)
        self.bob.set_password("a-different-password-77")
        self.bob.save()
        User.objects.filter(pk=self.alice.pk).delete()

        services.restore_backup(doc, self.admin)

        restored = {u.username: (u.password, u.is_superuser, u.is_active) for u in User.objects.all()}
        self.assertEqual(restored, original)
        self.assertNotIn("carol", self.usernames())
        self.assertEqual(BackupFile.objects.filter(kind="pre_restore").count(), 1)
        self.assertTrue(BackupLog.objects.filter(kind="restore", success=True).exists())
        # The safety backup holds the data as it was just before the restore.
        safety = gunzip_json(BackupFile.objects.get(kind="pre_restore").data)
        safety_names = {r["fields"]["username"] for r in safety["models"]["accounts.User"]}
        self.assertEqual(safety_names, {"boss", "bob", "carol"})

    def test_restore_refused_without_active_admin(self):
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        for record in doc["models"]["accounts.User"]:
            record["fields"]["is_superuser"] = False
        User.objects.create_user("carol", password=PASSWORD)
        before = self.usernames()
        with self.assertRaises(services.BackupError):
            services.restore_backup(doc, self.admin)
        self.assertEqual(self.usernames(), before)
        self.assertFalse(BackupFile.objects.filter(kind="pre_restore").exists())

    def test_restore_failure_rolls_back(self):
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        User.objects.create_user("carol", password=PASSWORD)
        before = self.usernames()
        with mock.patch("backups.services.connection.ops.sequence_reset_sql", side_effect=RuntimeError("oops")):
            with self.assertRaises(services.BackupError):
                services.restore_backup(doc, self.admin)
        self.assertEqual(self.usernames(), before)
        self.assertTrue(BackupLog.objects.filter(kind="restore", success=False).exists())


class ViewTests(BackupBase):
    def test_non_admin_gets_403_everywhere(self):
        backup = services.create_backup("daily")
        self.client.login(username="alice", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("backup_list")).status_code, 403)
        self.assertEqual(self.client.post(reverse("backup_now")).status_code, 403)
        self.assertEqual(self.client.get(reverse("restore_upload")).status_code, 403)
        self.assertEqual(self.client.post(reverse("restore_upload")).status_code, 403)
        self.assertEqual(self.client.get(reverse("backup_download", args=[backup.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("restore_preview", args=[backup.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("restore_preview", args=[backup.pk]), {"confirm": "RESTORE"}).status_code, 403)
        self.assertEqual(BackupFile.objects.count(), 1)

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(reverse("backup_list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp["Location"])

    def test_list_and_backup_now(self):
        self.login_admin()
        resp = self.client.post(reverse("backup_now"))
        self.assertRedirects(resp, reverse("backup_list"))
        self.assertEqual(BackupFile.objects.filter(kind="manual", created_by=self.admin).count(), 1)
        page = self.client.get(reverse("backup_list"))
        self.assertContains(page, "Download")
        self.assertContains(page, "accounts.User: 3")

    def test_backup_now_requires_post(self):
        self.login_admin()
        self.assertEqual(self.client.get(reverse("backup_now")).status_code, 405)

    def test_download_returns_exact_bytes(self):
        backup = services.create_backup("daily")
        self.login_admin()
        resp = self.client.get(reverse("backup_download", args=[backup.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/gzip")
        self.assertIn("attachment", resp["Content-Disposition"])
        self.assertEqual(b"".join(resp.streaming_content), bytes(backup.data))

    def test_preview_page_shows_counts(self):
        backup = services.create_backup("daily")
        User.objects.create_user("carol", password=PASSWORD)
        self.login_admin()
        resp = self.client.get(reverse("restore_preview", args=[backup.pk]))
        self.assertContains(resp, "safety backup")
        self.assertContains(resp, "carol")

    def test_restore_requires_confirmation_word(self):
        backup = services.create_backup("daily")
        User.objects.create_user("carol", password=PASSWORD)
        before = self.usernames()
        self.login_admin()
        for body in ({}, {"confirm": "restore"}, {"confirm": "yes"}):
            resp = self.client.post(reverse("restore_preview", args=[backup.pk]), body)
            self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.usernames(), before)
        self.assertFalse(BackupFile.objects.filter(kind="pre_restore").exists())

    def test_restore_with_confirmation_word(self):
        backup = services.create_backup("daily")
        User.objects.create_user("carol", password=PASSWORD)
        self.login_admin()
        resp = self.client.post(reverse("restore_preview", args=[backup.pk]), {"confirm": "RESTORE"})
        self.assertRedirects(resp, reverse("backup_list"))
        self.assertEqual(self.usernames(), {"boss", "alice", "bob"})
        self.assertTrue(BackupFile.objects.filter(kind="pre_restore").exists())

    def test_upload_valid_file_goes_to_preview(self):
        raw = bytes(services.create_backup("daily").data)
        self.login_admin()
        upload = SimpleUploadedFile("my backup.json.gz", raw, content_type="application/gzip")
        resp = self.client.post(reverse("restore_upload"), {"backup_file": upload})
        uploaded = BackupFile.objects.get(kind="uploaded")
        self.assertRedirects(resp, reverse("restore_preview", args=[uploaded.pk]))
        self.assertEqual(bytes(uploaded.data), raw)
        self.assertNotIn(" ", uploaded.filename)

    def test_upload_corrupted_file_rejected_without_changes(self):
        User.objects.create_user("carol", password=PASSWORD)
        before = self.usernames()
        self.login_admin()
        upload = SimpleUploadedFile("bad.json.gz", b"this is not a backup", content_type="application/gzip")
        resp = self.client.post(reverse("restore_upload"), {"backup_file": upload}, follow=True)
        self.assertContains(resp, "not a backup file")
        self.assertFalse(BackupFile.objects.filter(kind="uploaded").exists())
        self.assertEqual(self.usernames(), before)

    @override_settings(MAX_BACKUP_UPLOAD_MB=1)
    def test_upload_over_limit_rejected(self):
        self.login_admin()
        upload = SimpleUploadedFile("big.json.gz", b"x" * (1024 * 1024 + 1))
        self.client.post(reverse("restore_upload"), {"backup_file": upload})
        self.assertFalse(BackupFile.objects.filter(kind="uploaded").exists())


class BannerTests(BackupBase):
    def test_banner_after_failure(self):
        with mock.patch("backups.services.serializers.serialize", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                services.create_backup("daily")
        self.login_admin()
        self.assertContains(self.client.get(reverse("home")), "The last backup FAILED")

    def test_banner_when_stale(self):
        backup = services.create_backup("daily")
        BackupLog.objects.filter(backup=backup).update(started_at=timezone.now() - timedelta(hours=50))
        self.login_admin()
        self.assertContains(self.client.get(reverse("home")), "No successful backup in the last 36 hours.")

    def test_banner_when_no_backup_ever(self):
        self.login_admin()
        self.assertContains(self.client.get(reverse("home")), "No successful backup")

    def test_no_banner_after_fresh_success(self):
        services.create_backup("daily")
        self.login_admin()
        resp = self.client.get(reverse("home"))
        self.assertNotContains(resp, "FAILED")
        self.assertNotContains(resp, "No successful backup")

    def test_no_banner_for_non_admin(self):
        self.client.login(username="alice", password=PASSWORD)
        resp = self.client.get(reverse("home"))
        self.assertNotContains(resp, "No successful backup")


class MigrateWithBackupTests(BackupBase):
    CMD = "backups.management.commands.migrate_with_backup"

    def test_backup_taken_when_migrations_pending(self):
        with mock.patch(f"{self.CMD}.has_pending_migrations", return_value=True), mock.patch(
            f"{self.CMD}.call_command"
        ) as migrate:
            call_command("migrate_with_backup", stdout=StringIO())
        self.assertEqual(BackupFile.objects.filter(kind="pre_migration").count(), 1)
        migrate.assert_called_once_with("migrate", interactive=False)

    def test_no_backup_when_nothing_pending(self):
        with mock.patch(f"{self.CMD}.has_pending_migrations", return_value=False), mock.patch(
            f"{self.CMD}.call_command"
        ) as migrate:
            call_command("migrate_with_backup", stdout=StringIO())
        self.assertFalse(BackupFile.objects.exists())
        migrate.assert_called_once()

    def test_no_backup_when_no_users(self):
        User.objects.all().delete()
        with mock.patch(f"{self.CMD}.has_pending_migrations", return_value=True), mock.patch(
            f"{self.CMD}.call_command"
        ):
            call_command("migrate_with_backup", stdout=StringIO())
        self.assertFalse(BackupFile.objects.exists())

    def test_failed_backup_aborts_migrate(self):
        with mock.patch(f"{self.CMD}.has_pending_migrations", return_value=True), mock.patch(
            f"{self.CMD}.call_command"
        ) as migrate, mock.patch("backups.services.serializers.serialize", side_effect=RuntimeError("boom")):
            with self.assertRaises(CommandError):
                call_command("migrate_with_backup", stdout=StringIO())
        migrate.assert_not_called()

    def test_real_pending_check_runs(self):
        # Test database is fully migrated, so nothing is pending.
        self.assertFalse(migrate_with_backup.has_pending_migrations())
