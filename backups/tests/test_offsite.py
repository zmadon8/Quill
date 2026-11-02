from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from unittest import mock

from backups import services, storage
from backups.context_processors import backup_banner
from backups.models import BackupLog

PASSWORD = "correct-horse-battery-9"
SECRET = "do-not-log-this-secret"


class FakeStorage:
    configured = True
    destination = "fake.example/bucket"

    def __init__(self, fail=False):
        self.items = {}
        self.fail = fail

    def put(self, key, data):
        if self.fail:
            raise storage.StorageError("The storage service refused the request (HTTP 403).")
        self.items[key] = (data, timezone.now())

    def list(self):
        return [storage.StoredObject(k, len(v[0]), v[1]) for k, v in self.items.items()]

    def get(self, key):
        return self.items[key][0]

    def delete(self, key):
        del self.items[key]


@override_settings(SECURE_SSL_REDIRECT=False)
class OffsiteTests(TestCase):
    def test_unconfigured_does_nothing(self):
        backup = services.create_backup("daily")
        self.assertIsNone(services.upload_offsite(backup, storage.NoOpStorage()))
        self.assertFalse(BackupLog.objects.filter(kind="offsite").exists())
        self.assertFalse(services.offsite_status()["configured"])

    def test_upload_after_success_is_logged(self):
        backup = services.create_backup("daily")
        fake = FakeStorage()
        self.assertTrue(services.upload_offsite(backup, fake))
        self.assertEqual(fake.get(backup.filename), bytes(backup.data))
        log = BackupLog.objects.get(kind="offsite")
        self.assertTrue(log.success)
        self.assertEqual(log.size_bytes, backup.size_bytes)
        self.assertIn("fake.example/bucket", log.message)

    def test_failure_is_logged_not_raised_and_secret_absent(self):
        backup = services.create_backup("daily")
        with self.assertLogs("backups.services", level="WARNING") as captured:
            self.assertFalse(services.upload_offsite(backup, FakeStorage(fail=True)))
        log = BackupLog.objects.get(kind="offsite")
        self.assertFalse(log.success)
        self.assertIn("FAILED", log.message)
        self.assertNotIn(SECRET, log.message + "".join(captured.output))

    def test_unexpected_error_reduced_to_class_name(self):
        backup = services.create_backup("daily")
        fake = FakeStorage()
        fake.put = mock.Mock(side_effect=RuntimeError(SECRET))
        services.upload_offsite(backup, fake)
        self.assertNotIn(SECRET, BackupLog.objects.get(kind="offsite").message)

    def test_retention_keeps_newest_and_recent(self):
        fake = FakeStorage()
        now = timezone.now()
        for name, age in (("old", 200), ("older", 300), ("new", 1)):
            fake.items[name] = (b"x", now - timedelta(days=age))
        self.assertEqual(services.prune_offsite(fake, now=now, retention_days=90), 2)
        self.assertEqual([o.key for o in fake.list()], ["new"])

    def test_retention_never_removes_the_only_copy(self):
        fake = FakeStorage()
        fake.items["only"] = (b"x", timezone.now() - timedelta(days=500))
        self.assertEqual(services.prune_offsite(fake, retention_days=90), 0)

    def test_run_backup_uploads_and_unconfigured_is_unchanged(self):
        with mock.patch("backups.storage.get_storage", return_value=storage.NoOpStorage()):
            call_command("run_backup", stdout=StringIO())
        self.assertFalse(BackupLog.objects.filter(kind="offsite").exists())
        fake = FakeStorage()
        with mock.patch("backups.storage.get_storage", return_value=fake):
            call_command("run_backup", stdout=StringIO())
        self.assertEqual(len(fake.items), 1)

    def test_run_backup_survives_offsite_failure(self):
        with mock.patch("backups.storage.get_storage", return_value=FakeStorage(fail=True)):
            call_command("run_backup", stdout=StringIO())
        self.assertTrue(BackupLog.objects.filter(kind="daily", success=True).exists())
        self.assertTrue(BackupLog.objects.filter(kind="offsite", success=False).exists())

    def test_backup_offsite_command(self):
        with self.assertRaises(CommandError):
            call_command("backup_offsite", stdout=StringIO())
        services.create_backup("daily")
        out = StringIO()
        with mock.patch("backups.storage.get_storage", return_value=storage.NoOpStorage()):
            call_command("backup_offsite", stdout=out)
        self.assertIn("not set up", out.getvalue())
        fake = FakeStorage()
        with mock.patch("backups.storage.get_storage", return_value=fake):
            call_command("backup_offsite", stdout=out)
        self.assertEqual(len(fake.items), 1)
        with mock.patch("backups.storage.get_storage", return_value=FakeStorage(fail=True)):
            with self.assertRaises(CommandError):
                call_command("backup_offsite", stdout=out)

    def test_failure_shown_in_banner_and_status_on_screen(self):
        admin = get_user_model().objects.create_user("boss", password=PASSWORD, is_superuser=True, is_staff=True)
        backup = services.create_backup("daily")
        services.upload_offsite(backup, FakeStorage(fail=True))
        request = RequestFactory().get("/")
        request.user = admin
        self.assertIn("off-site backup copy FAILED", backup_banner(request)["backup_warning"])
        self.client.login(username="boss", password=PASSWORD)
        fake = FakeStorage()
        with mock.patch("backups.storage.get_storage", return_value=fake):
            page = self.client.get(reverse("backup_list"))
        self.assertContains(page, "fake.example/bucket")
        self.assertContains(page, "FAILED")
