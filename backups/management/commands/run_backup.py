from django.core.management.base import BaseCommand, CommandError

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
        self.stdout.write(
            self.style.SUCCESS(
                f"Daily backup OK: {backup.filename} ({backup.size_bytes} bytes). "
                f"Old backups removed: {removed}."
            )
        )
