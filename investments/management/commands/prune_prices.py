"""Thin old daily prices to one per month (plan 17.3). Off unless an Admin switched it on (Catalogue > Price history).

The last link of the nightly `&&` chain after `run_backup`, so it runs only after a good backup (it also checks today's backup itself).
Exits 0 when pruning is off, when it declines (a required pin is missing, or no backup today) and when nothing is due; non-zero only on
a real error."""
from django.core.management.base import BaseCommand

from investments.services import pruning


class Command(BaseCommand):
    help = __doc__.split("\n\n")[0]

    def handle(self, *args, **options):
        status, removed = pruning.prune_prices()
        self.stdout.write(f"prune_prices: {status}, {removed} rows removed")
