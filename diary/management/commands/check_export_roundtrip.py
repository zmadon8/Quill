from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from accounts.models import Profile
from accounts.suite import KEY_DIARY
from diary.importer.docx_reader import DocxError
from diary.wordexport import service

DEFAULT_FILE = "Case Law Diary.docx"


class Command(BaseCommand):
    help = (
        "Round-trip check (Milestone 6): export a profile to Word (Full, standard number formats, no review "
        "markers) and compare it, line by line, with the original Word file. Read-only: nothing in the "
        "database or in the Word file is changed. Prints a plain report and fails (exit code 1) if anything "
        "unexpected differs."
    )

    def add_arguments(self, parser):
        parser.add_argument("--file", default=DEFAULT_FILE, help=f"The original Word file (default '{DEFAULT_FILE}').")
        parser.add_argument("--profile", required=True, help="Name of the Case Law Diary profile that holds the imported file.")
        parser.add_argument("--output", help="Also write the report to this text file.")

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.is_file():
            raise CommandError(f"File not found: {path}")
        name = options["profile"].strip()
        profile = Profile.objects.filter(program=KEY_DIARY, name__iexact=name, deleted_at__isnull=True).first()
        if profile is None:
            raise CommandError(f"There is no profile called '{name}'.")
        try:
            result = service.roundtrip(profile, path.read_bytes())
        except DocxError as exc:
            raise CommandError(str(exc))
        if options["output"]:
            Path(options["output"]).write_text(result.text, encoding="utf-8")
            self.stdout.write(f"Report written to {options['output']}")
        self.stdout.write(result.text)
        if not result.ok:
            raise CommandError(f"{len(result.unexpected)} unexpected difference(s) between the export and the original.")
