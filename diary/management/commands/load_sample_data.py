from django.core.management.base import BaseCommand

from accounts.models import Profile
from accounts.profiles import DEFAULT_PROFILE_NAME, ensure_default_profile
from accounts.suite import KEY_DIARY
from diary.sample_data import SAMPLE_PREFIX, load_sample_data


class Command(BaseCommand):
    help = (
        f"Load the TEST sample Subjects (names start with '{SAMPLE_PREFIX}') into one profile. "
        "Safe to run twice."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--profile",
            default=DEFAULT_PROFILE_NAME,
            help=f"Name of the Case Law Diary profile to load into (default '{DEFAULT_PROFILE_NAME}'; created if missing).",
        )

    def handle(self, *args, **options):
        profile = ensure_default_profile(Profile, KEY_DIARY, options["profile"].strip())
        if load_sample_data(profile):
            self.stdout.write(self.style.SUCCESS(f"Sample data loaded into profile '{profile.name}'."))
        else:
            self.stdout.write(f"Sample data is already loaded in profile '{profile.name}'; nothing changed.")
