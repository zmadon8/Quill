from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from accounts.models import Profile
from accounts.suite import KEY_DIARY
from diary.importer import service

DEFAULT_FILE = "Case Law Diary.docx"


class Command(BaseCommand):
    help = (
        "Import 'Case Law Diary.docx' into one profile. By default only a DRY RUN is shown and nothing is "
        "saved. Use --import to import, --reconcile to compare the file with what the profile holds. "
        "The Word file is only read."
    )

    def add_arguments(self, parser):
        parser.add_argument("--file", default=DEFAULT_FILE, help=f"Word file to read (default '{DEFAULT_FILE}').")
        parser.add_argument("--profile", required=True, help="Name of the existing Case Law Diary profile.")
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--import", dest="do_import", action="store_true", help="Really import (after a dry run).")
        mode.add_argument("--reconcile", action="store_true", help="Compare the file with the profile; read-only.")
        parser.add_argument("--output", help="Also write the report to this text file.")

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.is_file():
            raise CommandError(f"File not found: {path}")
        data = path.read_bytes()
        name = options["profile"].strip()
        profile = Profile.objects.filter(program=KEY_DIARY, name__iexact=name, deleted_at__isnull=True).first()
        if profile is None:
            raise CommandError(f"There is no profile called '{name}'. Create it on the Profiles screen first.")
        try:
            if options["do_import"]:
                text, notes = service.run_import(data, path.name, profile)
                for note in notes:
                    self.stdout.write(note)
            elif options["reconcile"]:
                _, text = service.reconcile(data, path.name, profile)
            else:
                _, text = service.dry_run(data, path.name)
        except (service.DocxError, service.ImportRefused) as exc:
            raise CommandError(str(exc))
        if options["output"]:
            Path(options["output"]).write_text(text, encoding="utf-8")
            self.stdout.write(f"Report written to {options['output']}")
        else:
            self.stdout.write(text)
