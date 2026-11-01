from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from backups import services


def has_pending_migrations():
    executor = MigrationExecutor(connection)
    return bool(executor.migration_plan(executor.loader.graph.leaf_nodes()))


def needs_safety_backup():
    """True when there is real data to protect and a database change is about to happen."""
    tables = set(connection.introspection.table_names())
    User = get_user_model()
    if "backups_backupfile" not in tables or User._meta.db_table not in tables:
        return False
    # Historical User model: the real one may have columns that do not exist yet.
    HistoricalUser = services.applied_state_apps().get_model(User._meta.label)
    if not HistoricalUser._default_manager.exists():
        return False
    return has_pending_migrations()


class Command(BaseCommand):
    help = "Run database migrations, taking a safety backup first if there is data and changes are pending."

    def handle(self, *args, **options):
        if needs_safety_backup():
            try:
                backup = services.create_backup("pre_migration", use_applied_state=True)
            except Exception as exc:
                raise CommandError(
                    f"Safety backup before the database update FAILED, so the update was NOT run: {exc}"
                )
            self.stdout.write(f"Safety backup taken: {backup.filename}")
        else:
            self.stdout.write("No safety backup needed (no data yet, or nothing to update).")
        call_command("migrate", interactive=False)
