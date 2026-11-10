"""Give an existing user an Editor (or Reader) role in an Investments profile, creating the profile if it is missing.

It never creates a user and never touches a password. Run it once in the Render Shell at the go-ahead (the same job
``create_fees_user`` does for the Fee Register)::

    python manage.py create_investments_profile --username Ziyad --profile Ziyad-Investments

It also creates the profile's first portfolio and the built-in index (Nifty 50), so a first purchase needs no other set-up.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from accounts.models import ROLE_EDITOR, ROLE_READER, Profile, ProfileMembership
from accounts.profiles import ensure_default_profile
from accounts.suite import KEY_INVESTMENTS


class Command(BaseCommand):
    help = __doc__.split("\n\n")[0]

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--profile", required=True, help="Investments profile name (created if missing).")
        parser.add_argument("--role", choices=[ROLE_EDITOR, ROLE_READER], default=ROLE_EDITOR)

    def handle(self, *args, **options):
        from investments.services import masters

        username, name = options["username"].strip(), options["profile"].strip()
        if not username or not name:
            raise CommandError("--username and --profile must not be blank.")
        user = get_user_model().objects.filter(username__iexact=username).first()
        if user is None:
            raise CommandError(f"No user named {username!r} exists. Create the user first.")
        profile = ensure_default_profile(Profile, KEY_INVESTMENTS, name)
        ProfileMembership.objects.update_or_create(
            user=user, profile=profile, defaults={"role": options["role"], "suspended": False, "program": KEY_INVESTMENTS})
        masters.ensure_default_portfolio(profile)
        masters.ensure_builtin_indices()
        self.stdout.write(self.style.SUCCESS(f"{user.username} is {options['role']} in Investments profile {profile.name}"))
