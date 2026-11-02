from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from backups import registry, services


def rehearse(user=None):
    """Take a backup, read it back and compare it with the live database. Changes no diary data.

    Returns (backup, rows, problems). Each row is (label, in_file, in_database). A backup file is stored (kind
    "manual"), so the rehearsal also proves that a backup can be written, read and checked here.
    """
    backup = services.create_backup("manual", user)
    document = services.parse_backup(backup.data, settings.MAX_BACKUP_UPLOAD_MB * 1024 * 1024)
    rows = []
    problems = []
    for model in registry.get_models():
        label = model._meta.label
        in_file = len(document["models"].get(label, []))
        in_database = model._default_manager.count()
        rows.append((label, in_file, in_database))
        if in_file != in_database:
            problems.append(f"{label}: {in_file} in the backup, {in_database} in the database now")
    return backup, rows, problems


class Command(BaseCommand):
    help = (
        "Final backup rehearsal: take a backup, read it back and compare the record counts per model with the live "
        "database. Nothing is restored and no diary data is changed. Run it when the site is quiet, since edits made meanwhile show as count differences."
    )

    def handle(self, *args, **options):
        try:
            backup, rows, problems = rehearse()
        except Exception as exc:
            raise CommandError(f"Backup rehearsal FAILED: {exc}")
        self.stdout.write(f"Backup: {backup.filename} ({backup.size_bytes} bytes, sha256 {backup.sha256[:12]}...)")
        self.stdout.write(f"{'Model':<28}{'In backup':>10}{'In database':>13}")
        for label, in_file, in_database in rows:
            mark = "" if in_file == in_database else "  <-- DIFFERENT"
            self.stdout.write(f"{label:<28}{in_file:>10}{in_database:>13}{mark}")
        if problems:
            raise CommandError("Backup rehearsal FAILED: " + "; ".join(problems))
        self.stdout.write(self.style.SUCCESS(
            f"Backup rehearsal OK: {sum(r[1] for r in rows)} records read back and the counts match. "
            "Nothing was restored."
        ))
