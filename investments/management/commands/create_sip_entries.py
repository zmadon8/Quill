"""Create each due SIP entry from the NAVs just stored (plan 15.4, step 2 of the nightly job).

SIP schedules arrive with a later release; until then this command does nothing and exits 0, so the cron line can already be in place.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = __doc__.split("\n\n")[0]

    def handle(self, *args, **options):
        from django.conf import settings

        if not getattr(settings, "INVESTMENTS_ENABLED", True):
            self.stdout.write("create_sip_entries: Investments is switched off; nothing to do.")
            return
        try:
            from investments.services import sip
        except ImportError:
            self.stdout.write("create_sip_entries: SIP schedules are not set up yet; nothing to do.")
            return
        made = sip.create_due_entries()
        self.stdout.write(f"create_sip_entries: {made} entr{'y' if made == 1 else 'ies'} created.")
