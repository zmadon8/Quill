"""Send the Investments report emails that are due (Investments > Settings > Email reports): weekly, monthly, quarterly and annual.

Run nightly. A period goes out once it has ended and is never sent twice; one profile's failure never stops the others, and the command
exits 0."""
from django.core.management.base import BaseCommand

from investments.services import periodic_mail


class Command(BaseCommand):
    help = "Email the weekly, monthly, quarterly and annual Investments reports that are due (Investments > Settings > Email reports)."

    def handle(self, *args, **options):
        from django.conf import settings

        if not getattr(settings, "INVESTMENTS_ENABLED", True):
            self.stdout.write("send_report_emails: Investments is switched off; nothing to do.")
            return
        sent, idle = periodic_mail.send_all()
        self.stdout.write(f"send_report_emails: {sent} email(s) sent, {idle} profile(s) with nothing due")
