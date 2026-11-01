import getpass
import os
import sys

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from accounts.models import ProfileMembership
from accounts.profiles import ensure_default_profile


class Command(BaseCommand):
    help = (
        "Create the first Admin user from DJANGO_SUPERUSER_USERNAME and "
        "DJANGO_SUPERUSER_PASSWORD. Refuses to run if any user already exists."
    )

    def handle(self, *args, **options):
        User = get_user_model()
        if User.objects.exists():
            raise CommandError("Users already exist; refusing to create another Admin this way.")

        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "").strip()
        if not username:
            raise CommandError("DJANGO_SUPERUSER_USERNAME must be set.")

        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "")
        if not password:
            if sys.stdin.isatty():
                password = getpass.getpass("Password: ")
                if getpass.getpass("Password (again): ") != password:
                    raise CommandError("Passwords do not match.")
            else:
                raise CommandError("DJANGO_SUPERUSER_PASSWORD must be set.")

        user = User(username=username, role="admin", is_staff=True, is_superuser=True)
        try:
            user.full_clean(exclude=["password"])
            validate_password(password, user)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        user.set_password(password)
        user.save()
        profile = ensure_default_profile()
        ProfileMembership.objects.create(user=user, profile=profile)
        self.stdout.write(self.style.SUCCESS(f"Admin {username} created (profile: {profile.name})."))
