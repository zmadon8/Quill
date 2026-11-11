"""Work out the Overview, Holdings and Alerts figures of every Investments profile ahead of time (the last Investments step of the nightly job).

The nightly price update makes every kept figure out of date, so without this the first visit of the day pays for replaying the whole
history. Run after fetch_prices. A failure is logged and never changes the exit code of the nightly job."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = __doc__.split("\n\n")[0]

    def add_arguments(self, parser):
        parser.add_argument("--max-seconds", type=int, default=300, help="Stop starting new profiles after this many seconds (default 300).")

    def handle(self, *args, **options):
        from django.conf import settings

        from investments.services import warm

        if not getattr(settings, "INVESTMENTS_ENABLED", True):
            self.stdout.write("warm_investments_cache: Investments is switched off; nothing to do.")
            return
        summary = warm.warm_all(max_seconds=options["max_seconds"])
        self.stdout.write(f"warm_investments_cache: {summary['profiles']} profile(s) ready, {summary['kept']} result(s) kept, "
                          f"{summary['failed']} failed" + (", stopped early (time cap)" if summary["stopped"] else ""))
