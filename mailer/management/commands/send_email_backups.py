from django.core.management.base import BaseCommand, CommandError

from mailer import services
from mailer.models import EmailBackupSchedule


class Command(BaseCommand):
    help = "Email the backup (and the Word export) if the Admin's email schedule says one is due. Run nightly, after run_backup."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Send now, whether or not one is due (the schedule must have addresses).")

    def handle(self, *args, **options):
        schedule = EmailBackupSchedule.load()
        if not options["force"]:
            if not schedule.enabled:
                self.stdout.write("Emailed backups are switched off; nothing sent.")
                return
            if not services.is_due(schedule):
                self.stdout.write("No emailed backup is due today.")
                return
        ok, message = services.send_scheduled_backup(schedule)
        if not ok:
            raise CommandError(f"Emailed backup FAILED: {message}")
        self.stdout.write(self.style.SUCCESS(f"Emailed backup OK. {message}"))
