"""Load a price history file (CSV or Excel) from the command line, for files too big for the web page (plan 29.5).

    python manage.py import_prices --file prices.csv --dry-run
    python manage.py import_prices --file prices.csv --basis raw

Same rules as the web upload: a dry run report, bad rows block the whole file, unknown symbols are skipped, the uploaded row wins
over a fetched one and hand-entered prices are untouched.
"""
from django.core.management.base import BaseCommand, CommandError

from investments.errors import InvestmentsError
from investments.services import price_import


class Command(BaseCommand):
    help = __doc__.split("\n\n")[0]

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--basis", choices=["", "raw", "split_adjusted"], default="")

    def handle(self, *args, **options):
        try:
            report = price_import.dry_run(options["file"], default_basis=options["basis"])
            self.stdout.write(f"{report.rows} rows, {len(report.per_instrument)} investments matched, {len(report.unknown)} unknown symbols, "
                              f"{report.blocking_count} bad rows, {len(report.gaps)} gaps, {len(report.big_moves)} big moves")
            for line, message in report.blocking:
                self.stdout.write(f"  row {line}: {message}")
            if options["dry_run"]:
                return
            written = price_import.apply(options["file"], default_basis=options["basis"], report=report)
        except InvestmentsError as err:
            raise CommandError(err.message)
        self.stdout.write(self.style.SUCCESS(f"{written} prices written."))
