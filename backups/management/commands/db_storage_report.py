from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection

#: Tables that grow over time, shown by name when they exist. No row contents are ever read or printed.
WATCHED = [
    "backups.BackupFile",
    "backups.BackupLog",
    "diary.VersionHistory",
    "accounts.FailedLogin",
    "accounts.ResetRequest",
    "accounts.PurgeLog",
    "accounts.OfflineLink",
    "accounts.OfflineDownload",
    "fees.StatsCache",
    "fees.WordTemplate",
]


def _mb(value):
    return f"{(value or 0) / (1024 * 1024):.1f} MB"


def watched_tables():
    """``(label, db_table)`` for the growth-prone models, plus the sessions table."""
    out = []
    for label in WATCHED:
        try:
            out.append((label, apps.get_model(label)._meta.db_table))
        except LookupError:
            continue
    out.append(("sessions", "django_session"))
    return out


class Command(BaseCommand):
    help = (
        "Read-only report of what uses the database's disk space: total size, the biggest tables, stored backups "
        "and the tables that grow over time. Prints sizes and counts only, never any diary or fee data. "
        "Full detail needs PostgreSQL; on other databases only row counts are shown."
    )

    def handle(self, *args, **options):
        existing = set(connection.introspection.table_names())
        postgres = connection.vendor == "postgresql"
        if postgres:
            self._postgres_overview()
        else:
            self.stdout.write(f"Database type: {connection.vendor}. Sizes are only available on PostgreSQL.")
        self._backups(existing, postgres)
        self._counts(existing, postgres)

    def _fetch(self, sql, params=None):
        with connection.cursor() as cursor:
            cursor.execute(sql, params or [])
            return cursor.fetchall()

    def _postgres_overview(self):
        size = self._fetch("SELECT pg_database_size(current_database())")[0][0]
        self.stdout.write(f"Database size: {_mb(size)}")
        self.stdout.write("")
        self.stdout.write("Tables, largest first (total = table + indexes + TOAST; table = main data only):")
        rows = self._fetch(
            "SELECT c.relname, pg_total_relation_size(c.oid), pg_relation_size(c.oid), pg_indexes_size(c.oid) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' ORDER BY 2 DESC"
        )
        for name, total, table, indexes in rows:
            self.stdout.write(f"  {name}: total {_mb(total)}, table {_mb(table)}, indexes {_mb(indexes)}")

    def _backups(self, existing, postgres):
        from backups.models import BackupFile

        self.stdout.write("")
        table = BackupFile._meta.db_table
        if table not in existing:
            self.stdout.write("Stored backups: table not found.")
            return
        count = BackupFile.objects.count()
        self.stdout.write(f"Stored backups: {count}")
        if not count:
            return
        quoted = connection.ops.quote_name(table)
        if postgres:
            total_size, total_data, avg_data = self._fetch(
                f"SELECT COALESCE(SUM(size_bytes), 0), COALESCE(SUM(octet_length(data)), 0), "
                f"COALESCE(AVG(octet_length(data)), 0) FROM {quoted}"
            )[0]
        else:
            total_size, total_data, avg_data = self._fetch(
                f"SELECT COALESCE(SUM(size_bytes), 0), COALESCE(SUM(length(data)), 0), "
                f"COALESCE(AVG(length(data)), 0) FROM {quoted}"
            )[0]
        self.stdout.write(f"  Sum of size_bytes: {_mb(total_size)}")
        self.stdout.write(f"  Sum of stored data: {_mb(total_data)}")
        self.stdout.write(f"  Average per backup: {_mb(avg_data)}")

    def _counts(self, existing, postgres):
        stats = {}
        if postgres:
            for name, dead, vacuumed, auto in self._fetch(
                "SELECT relname, n_dead_tup, last_vacuum, last_autovacuum FROM pg_stat_user_tables"
            ):
                stats[name] = (dead, vacuumed, auto)
        self.stdout.write("")
        self.stdout.write("Tables that grow over time (rows" + (", dead rows, last vacuum):" if postgres else "):"))
        for label, table in watched_tables():
            if table not in existing:
                continue
            rows = self._fetch(f"SELECT COUNT(*) FROM {connection.ops.quote_name(table)}")[0][0]
            line = f"  {label} ({table}): {rows} rows"
            if table in stats:
                dead, vacuumed, auto = stats[table]
                line += f", {dead} dead rows, last vacuum {vacuumed or auto or 'never'}"
            self.stdout.write(line)
