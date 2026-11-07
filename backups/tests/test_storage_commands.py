from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from backups.models import BackupFile, BackupLog


def make_backup(n):
    raw = b"x" * 100
    return BackupFile.objects.create(
        created_at=timezone.now(), kind="manual", filename=f"f{n}.json.gz", data=raw, size_bytes=len(raw), sha256="0" * 64
    )


class StorageReportTests(TestCase):
    def test_report_runs_and_counts_backups(self):
        make_backup(1)
        make_backup(2)
        BackupLog.objects.create(kind="manual", success=True)
        out = StringIO()
        call_command("db_storage_report", stdout=out)
        text = out.getvalue()
        self.assertIn("Stored backups: 2", text)
        self.assertIn("Sum of size_bytes", text)
        self.assertIn("backups.BackupLog", text)
        self.assertIn("sessions", text)
        if connection.vendor == "postgresql":
            self.assertIn("Database size:", text)

    def test_report_with_no_backups(self):
        out = StringIO()
        call_command("db_storage_report", stdout=out)
        self.assertIn("Stored backups: 0", out.getvalue())


class ReclaimDryRunTests(TestCase):
    def test_non_postgres_refuses_and_postgres_reports_only(self):
        out = StringIO()
        if connection.vendor != "postgresql":
            with self.assertRaises(CommandError):
                call_command("db_reclaim_space", stdout=out)
            return
        call_command("db_reclaim_space", stdout=out)
        self.assertIn("Dry run: nothing changed", out.getvalue())

    def test_unknown_table_is_rejected(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL only")
        with self.assertRaises(CommandError):
            call_command("db_reclaim_space", "--tables", 'x"; DROP TABLE auth_user; --', stdout=StringIO())


class ReclaimConfirmTests(TransactionTestCase):
    def test_confirm_runs_vacuum_full(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL only")
        make_backup(1)
        out = StringIO()
        call_command("db_reclaim_space", "--confirm", stdout=out)
        self.assertIn("vacuumed", out.getvalue())
        self.assertEqual(BackupFile.objects.count(), 1)
