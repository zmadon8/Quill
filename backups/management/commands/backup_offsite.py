from django.core.management.base import BaseCommand, CommandError

from backups import services
from backups.models import BackupFile


class Command(BaseCommand):
    help = "Copy the newest stored backup to the off-site storage (does nothing if off-site backup is not set up)."

    def handle(self, *args, **options):
        backup = BackupFile.objects.order_by("-created_at", "-id").first()
        if backup is None:
            raise CommandError("There is no backup to copy yet.")
        result = services.upload_offsite(backup)
        if result is None:
            self.stdout.write("Off-site backup is not set up; nothing was copied.")
            return
        if result is False:
            raise CommandError("The off-site copy FAILED. See the Backups screen for details.")
        removed = services.prune_offsite()
        self.stdout.write(self.style.SUCCESS(f"Off-site copy OK: {backup.filename}. Old copies removed: {removed}."))
