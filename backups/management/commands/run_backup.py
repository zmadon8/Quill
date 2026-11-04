from django.core.management.base import BaseCommand, CommandError

from accounts.models import prune_failed_logins, prune_offline_downloads
from backups import services


class Command(BaseCommand):
    help = "Create the daily backup, then remove backups older than the retention period."

    def handle(self, *args, **options):
        try:
            backup = services.create_backup("daily")
        except Exception as exc:
            # Non-zero exit so the host (Render cron job) marks the run as failed.
            raise CommandError(f"Daily backup FAILED: {exc}")
        removed = services.prune_old_backups()
        # Off-site copy: no-op unless set up; failures are logged and shown in the warning banner, not fatal here.
        services.upload_offsite(backup)
        services.prune_offsite()
        try:
            prune_failed_logins()
        except Exception as exc:  # housekeeping must not fail a successful backup
            self.stderr.write(f"Could not clean old failed-login records: {exc}")
        try:
            prune_offline_downloads()
        except Exception as exc:  # housekeeping must not fail a successful backup
            self.stderr.write(f"Could not clean old offline download records: {exc}")
        self.stdout.write(
            self.style.SUCCESS(
                f"Daily backup OK: {backup.filename} ({backup.size_bytes} bytes). "
                f"Old backups removed: {removed}."
            )
        )
