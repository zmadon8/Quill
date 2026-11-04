from django.core.management.base import BaseCommand, CommandError

from accounts.models import OfflineLink
from diary.offline_link import refresh_all


class Command(BaseCommand):
    help = "Remake the saved Offline copy of every profile whose secret link is switched on. Run nightly, after run_backup."

    def handle(self, *args, **options):
        if not OfflineLink.objects.filter(enabled=True, profile__deleted_at__isnull=True).exists():
            self.stdout.write("No offline links are switched on.")
            return
        made, failed = refresh_all()
        if failed:
            ids = ", ".join(str(pk) for pk in failed)
            raise CommandError(f"Offline copy refresh FAILED for profile id(s) {ids}. Made: {made}. See Profiles > Offline link.")
        self.stdout.write(self.style.SUCCESS(f"Offline copies refreshed: {made}."))
