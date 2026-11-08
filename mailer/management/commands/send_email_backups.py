from django.core.management.base import BaseCommand, CommandError

from mailer import services
from mailer.models import EmailBackupSchedule


class Command(BaseCommand):
    help = ("Email each kind of backup file (regular backup, Word and HTML copies, Fee Register Excel) whose own schedule "
            "says it is due. Run nightly, after run_backup.")

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Send every kind that is switched on now, whether or not it is due (the schedule must have addresses).")

    def handle(self, *args, **options):
        schedule = EmailBackupSchedule.load()
        if not options["force"]:
            if not schedule.enabled:
                self.stdout.write("Emailed backups are switched off; nothing sent.")
                return
            if not services.is_due(schedule):
                self.stdout.write("No emailed backup is due today.")
                return
        kinds = schedule.enabled_kinds() if options["force"] else None
        ok, message = services.send_scheduled_backup(schedule, kinds=kinds)
        if not ok:
            raise CommandError(f"Emailed backup FAILED: {message}")
        self.stdout.write(self.style.SUCCESS(f"Emailed backup OK. {message}"))
