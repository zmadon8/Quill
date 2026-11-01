from django.core.management.base import BaseCommand

from diary.sample_data import SAMPLE_PREFIX, load_sample_data


class Command(BaseCommand):
    help = f"Load the TEST sample Subjects (names start with '{SAMPLE_PREFIX}'). Safe to run twice."

    def handle(self, *args, **options):
        if load_sample_data():
            self.stdout.write(self.style.SUCCESS("Sample data loaded."))
        else:
            self.stdout.write("Sample data is already loaded; nothing changed.")
