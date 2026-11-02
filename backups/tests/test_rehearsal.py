import gzip
import json
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from accounts.models import Profile
from backups import registry, services
from backups.management.commands.backup_rehearsal import rehearse
from backups.models import BackupFile
from backups.tests.test_backups import MAX, BackupBase
from diary.models import Subject
from diary.tests.helpers import main_profile


class RehearsalCommandTests(BackupBase):
    def test_counts_match_and_nothing_is_restored(self):
        Subject.objects.create(profile=main_profile(), name="Rehearsal Subject")
        out = StringIO()
        call_command("backup_rehearsal", stdout=out)
        text = out.getvalue()
        self.assertIn("Backup rehearsal OK", text)
        self.assertIn("diary.Subject", text)
        self.assertEqual(BackupFile.objects.filter(kind="manual").count(), 1)
        self.assertEqual(Subject.objects.count(), 1)

    def test_rows_cover_every_model(self):
        backup, rows, problems = rehearse()
        self.assertEqual(problems, [])
        self.assertEqual([r[0] for r in rows], [m._meta.label for m in registry.get_models()])
        self.assertEqual(dict((r[0], r[1]) for r in rows)["accounts.User"], 3)

    def test_difference_is_reported_as_failure(self):
        real = services.parse_backup

        def short(raw, max_bytes):
            document = real(raw, max_bytes)
            document["models"]["accounts.User"] = document["models"]["accounts.User"][:1]
            return document

        services.parse_backup = short
        try:
            with self.assertRaises(CommandError):
                call_command("backup_rehearsal", stdout=StringIO())
        finally:
            services.parse_backup = real


class OldFormatBackupTests(BackupBase):
    def minimal_old_file(self):
        """The smallest old-format file: required sections only, a user with an old ``role``, no profiles."""
        stamp = timezone.now().isoformat()
        models = {label: [] for label in registry.BACKUP_MODELS if label not in registry.OPTIONAL_MODELS}
        models["accounts.User"] = [{
            "model": "accounts.user", "pk": 1,
            "fields": {"username": "oldadmin", "password": "!", "role": "admin", "is_active": True,
                       "date_joined": stamp},
        }]
        models["diary.Subject"] = [{
            "model": "diary.subject", "pk": 1,
            "fields": {"name": "Old Subject", "created_at": stamp, "updated_at": stamp, "version": 1},
        }]
        document = {"format": services.FORMAT_MARKER, "format_version": 1, "created_at": stamp,
                    "models": models, "counts": {}}
        return gzip.compress(json.dumps(document).encode("utf-8"))

    def test_minimal_old_file_is_upgraded_on_parse(self):
        document = services.parse_backup(self.minimal_old_file(), MAX)
        user = document["models"]["accounts.User"][0]["fields"]
        self.assertNotIn("role", user)
        self.assertTrue(user["is_superuser"])
        self.assertEqual(len(document["models"]["accounts.Profile"]), 1)
        self.assertEqual(document["models"]["diary.Subject"][0]["fields"]["profile"], 1)

    def test_minimal_old_file_restores(self):
        document = services.parse_backup(self.minimal_old_file(), MAX)
        services.restore_backup(document, self.admin)
        self.assertEqual(self.usernames(), {"oldadmin"})
        self.assertEqual(Subject.objects.get().name, "Old Subject")
        self.assertEqual(Subject.objects.get().profile, Profile.objects.get())
