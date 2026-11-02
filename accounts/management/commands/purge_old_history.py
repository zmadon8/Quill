from django.core.management.base import BaseCommand, CommandError

from accounts.purge import purge_old_history


class Command(BaseCommand):
    help = (
        "Remove edit history older than HISTORY_RETENTION_DAYS (default 30), always keeping the newest version "
        "of every record. Only runs after a successful backup taken today."
    )

    def handle(self, *args, **options):
        log = purge_old_history()
        if log is None:
            self.stdout.write("No edit history is past the retention period.")
        elif not log.success:
            raise CommandError(log.message)
        else:
            self.stdout.write(self.style.SUCCESS(log.message + " " + str(log.counts)))
