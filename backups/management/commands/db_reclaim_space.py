from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from .db_storage_report import _mb


class Command(BaseCommand):
    help = (
        "Give disk space left behind by deleted rows back to the operating system with VACUUM (FULL, ANALYZE). "
        "By default it only reports what it would do; add --confirm to run it. VACUUM FULL locks each table "
        "while it rewrites it, for seconds to minutes, so run it when nobody is using the site. PostgreSQL only. "
        "The backup table is always included; add more with --tables name1 name2."
    )

    def add_arguments(self, parser):
        parser.add_argument("--tables", nargs="*", default=[], help="Extra table names to vacuum.")
        parser.add_argument("--dry-run", action="store_true", help="Only report (this is the default).")
        parser.add_argument("--confirm", action="store_true", help="Really run VACUUM FULL.")

    def handle(self, *args, **options):
        from backups.models import BackupFile

        if connection.vendor != "postgresql":
            raise CommandError("VACUUM FULL is only available on PostgreSQL. Nothing to do on this database.")
        if options["confirm"] and options["dry_run"]:
            raise CommandError("Use either --dry-run or --confirm, not both.")
        existing = set(connection.introspection.table_names())
        tables = [BackupFile._meta.db_table]
        for name in options["tables"]:
            if name not in existing:
                raise CommandError(f"Unknown table: {name!r}. Nothing was changed.")
            if name not in tables:
                tables.append(name)
        quote = connection.ops.quote_name
        for name in tables:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_total_relation_size(%s::regclass)", [quote(name)])
                before = cursor.fetchone()[0]
            self.stdout.write(f"{name}: {_mb(before)} now")
        if not options["confirm"]:
            self.stdout.write("Dry run: nothing changed. Add --confirm to run VACUUM (FULL, ANALYZE) on the tables above.")
            return
        # VACUUM cannot run inside a transaction block, so use autocommit and never call this inside atomic().
        if connection.in_atomic_block:
            raise CommandError("Cannot run VACUUM inside a transaction.")
        for name in tables:
            with connection.cursor() as cursor:
                cursor.execute(f"VACUUM (FULL, ANALYZE) {quote(name)}")
                cursor.execute("SELECT pg_total_relation_size(%s::regclass)", [quote(name)])
                after = cursor.fetchone()[0]
            self.stdout.write(self.style.SUCCESS(f"{name}: vacuumed, now {_mb(after)}"))
