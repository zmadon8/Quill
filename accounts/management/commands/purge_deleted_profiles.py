from django.core.management.base import BaseCommand, CommandError

from accounts.purge import purge_expired_profiles


class Command(BaseCommand):
    help = (
        "Permanently remove deleted profiles (and all their data) once the retention period has "
        "passed. Only runs after a successful backup taken today."
    )

    def handle(self, *args, **options):
        log = purge_expired_profiles()
        if log is None:
            self.stdout.write("No deleted profiles are past the retention period.")
        elif not log.success:
            raise CommandError(log.message)
        else:
            self.stdout.write(self.style.SUCCESS(log.message + " " + str(log.counts)))
