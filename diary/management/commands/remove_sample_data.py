from django.core.management.base import BaseCommand, CommandError

from accounts.models import Profile
from accounts.profiles import DEFAULT_PROFILE_NAME
from accounts.suite import KEY_DIARY
from diary.sample_data import SAMPLE_PREFIX, SampleDataError, remove_sample_data


class Command(BaseCommand):
    help = (
        f"Remove only the TEST sample Subjects (names start with '{SAMPLE_PREFIX}') and what is under them, "
        "inside one profile."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--profile",
            default=DEFAULT_PROFILE_NAME,
            help=f"Name of the Case Law Diary profile to remove from (default '{DEFAULT_PROFILE_NAME}').",
        )

    def handle(self, *args, **options):
        name = options["profile"].strip()
        profile = Profile.objects.filter(program=KEY_DIARY, name__iexact=name, deleted_at__isnull=True).first()
        if profile is None:
            raise CommandError(f"There is no profile called '{name}'.")
        try:
            count = remove_sample_data(profile)
        except SampleDataError as exc:
            raise CommandError(str(exc))
        self.stdout.write(self.style.SUCCESS(f"Removed {count} sample Subject(s) from profile '{profile.name}'."))
