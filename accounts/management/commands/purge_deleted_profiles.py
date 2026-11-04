from django.core.management.base import BaseCommand, CommandError

from accounts.purge import purge_expired_profiles
from accounts.user_trash import purge_expired_users


class Command(BaseCommand):
    help = (
        "Permanently remove deleted profiles (and all their data) and deleted users once their retention period has "
        "passed. Only runs after a successful backup taken today."
    )

    def handle(self, *args, **options):
        # Users first, then profiles; both are tried even if one is refused, and a refusal fails the command.
        problems = []
        for what, purge in (("users", purge_expired_users), ("profiles", purge_expired_profiles)):
            log = purge()
            if log is None:
                self.stdout.write(f"No deleted {what} are past the retention period.")
            elif not log.success:
                problems.append(log.message)
            else:
                self.stdout.write(self.style.SUCCESS(log.message + " " + str(log.counts)))
        if problems:
            raise CommandError(" ".join(problems))
