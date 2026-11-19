from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError

from backups import registry, services
from backups.management.commands.backup_rehearsal import rehearse
from backups.models import BackupFile
from backups.tests.test_backups import BackupBase
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


