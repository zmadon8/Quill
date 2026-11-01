from django.core.management.base import BaseCommand

from diary.sample_data import SAMPLE_PREFIX, remove_sample_data


class Command(BaseCommand):
    help = f"Remove only the TEST sample Subjects (names start with '{SAMPLE_PREFIX}') and what is under them."

    def handle(self, *args, **options):
        count = remove_sample_data()
        self.stdout.write(self.style.SUCCESS(f"Removed {count} sample Subject(s)."))
