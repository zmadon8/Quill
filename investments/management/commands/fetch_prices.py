"""Fetch new prices for every tracked investment (plan 15.4, step 1 of the nightly job).

Run by the nightly cron job before the backup. It has a total run-time cap (default 10 minutes) so it can never starve the backup,
fetches only the days since the last stored price, and never overwrites hand-entered or uploaded prices. A failure of one symbol
is recorded (Investments > Catalogue > Price sources) and does not stop the others. Exit code is 0 unless the run itself broke.
"""
from django.core.management.base import BaseCommand

from investments.services import fetch


class Command(BaseCommand):
    help = __doc__.split("\n\n")[0]

    def add_arguments(self, parser):
        parser.add_argument("--max-seconds", type=int, default=600, help="Total run-time cap (default 600).")
        parser.add_argument("--max-symbols", type=int, default=200, help="Most symbols in one run (default 200).")
        parser.add_argument("--spacing", type=float, default=1.0, help="Seconds between requests (default 1).")
        parser.add_argument("--years", type=int, default=None, help="Years of history to fetch for a new investment (default: all the source has, from the first purchase).")

    def handle(self, *args, **options):
        from django.conf import settings

        from investments.services import locks

        if not getattr(settings, "INVESTMENTS_ENABLED", True):
            self.stdout.write("fetch_prices: Investments is switched off; nothing to do.")
            return
        try:
            with locks.heavy("price_update"):
                summary = fetch.fetch_prices(trigger="cron", max_seconds=options["max_seconds"], max_symbols=options["max_symbols"],
                                             spacing=options["spacing"], years=options["years"])
        except locks.Busy:
            self.stdout.write("fetch_prices: another large job is running; skipped tonight.")
            return
        self.stdout.write(f"fetch_prices: tried {summary['tried']}, updated {summary['updated']}, failed {len(summary['failures'])}"
                          + (f", stopped: {summary['stopped']}" if summary["stopped"] else ""))
        for failure in summary["failures"][:20]:
            self.stdout.write(f"  - {failure['name']}: {failure['error']}")
