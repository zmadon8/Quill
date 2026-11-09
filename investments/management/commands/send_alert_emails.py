"""Email the alerts that triggered overnight to the members of each profile that asked for it (plan 14, proposed; off by default).

Run nightly after the prices are fetched. Each alert is emailed once per price date (remembered in `AlertState`); one profile's failure never
stops the others, and the command exits 0."""
from django.core.management.base import BaseCommand

from investments.services import alert_mail


class Command(BaseCommand):
    help = "Email the alerts that triggered overnight to the people who asked for it (Investments > Settings > Alerts)."

    def handle(self, *args, **options):
        from django.conf import settings

        if not getattr(settings, "INVESTMENTS_ENABLED", True):
            self.stdout.write("send_alert_emails: Investments is switched off; nothing to do.")
            return
        sent, skipped = alert_mail.send_all()
        self.stdout.write(f"send_alert_emails: {sent} email(s) sent, {skipped} profile(s) with nothing new")
