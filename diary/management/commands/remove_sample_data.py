from django.core.management.base import BaseCommand, CommandError

from diary.sample_data import SAMPLE_PREFIX, SampleDataError, remove_sample_data


class Command(BaseCommand):
    help = f"Remove only the TEST sample Subjects (names start with '{SAMPLE_PREFIX}') and what is under them."

    def handle(self, *args, **options):
        try:
            count = remove_sample_data()
        except SampleDataError as exc:
            raise CommandError(str(exc))
        self.stdout.write(self.style.SUCCESS(f"Removed {count} sample Subject(s)."))
