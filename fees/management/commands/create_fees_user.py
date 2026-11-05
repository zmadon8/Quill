"""Attach a Fee Register profile and Editor membership to an existing user (owner answer R-ACC-1).

The owner's user (``Ziyad``) already exists; this command adds the ``fees`` profile ``Ziyad-Fees``
to that user, promotes it to Admin when asked, and sets its landing program to ``fees``. It never
creates a second account unless ``--create-missing`` is given, and it is dormant code: it only runs
when an operator invokes it (never at import time, in a migration, a fixture or ``render.yaml``).

Password handling follows ``accounts.management.commands.create_first_admin``: read from the
environment variable ``FEES_USER_PASSWORD`` or two ``getpass`` prompts, validate with Django's
validators, and never pass it as an argument, print it or store it anywhere.
"""
import argparse
import getpass
import os
import sys

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from accounts.models import ROLE_EDITOR, Profile, ProfileMembership
from accounts.profiles import ensure_default_profile
from accounts.suite import KEY_FEES, get_names


class Command(BaseCommand):
    help = (
        "Attach the Fee Register profile and an Editor membership to an existing user, promote it to "
        "Admin (unless --no-admin) and set its landing program to the Fee Register. Never creates a "
        "second user unless --create-missing is given; no password is set unless --reset-password or "
        "a user is created."
    )

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True, help="Existing username to attach the profile to.")
        parser.add_argument("--profile", required=True, help="Fee Register profile name (created if missing).")
        parser.add_argument(
            "--make-admin",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="Promote the user to Admin (is_superuser). On by default; pass --no-admin to leave the user as is.",
        )
        parser.add_argument(
            "--reset-password",
            action="store_true",
            help="Set a new password for an existing user (read from FEES_USER_PASSWORD or prompted).",
        )
        parser.add_argument(
            "--create-missing",
            action="store_true",
            help="Create the user if it does not exist (fresh install only). Off by default so a typo cannot "
            "silently create a stray account.",
        )

    def handle(self, *args, **options):
        username = (options["username"] or "").strip()
        profile_name = (options["profile"] or "").strip()
        make_admin = options["make_admin"]
        reset_password = options["reset_password"]
        create_missing = options["create_missing"]

        if not username:
            raise CommandError("--username must not be blank.")
        if not profile_name:
            raise CommandError("--profile must not be blank.")

        User = get_user_model()
        matches = list(User.objects.filter(username__iexact=username))
        user = self._resolve_user(matches, username)

        if user is None and not create_missing:
            # Refuse before creating the profile, so a typo in --username leaves nothing behind.
            raise CommandError(
                f"No user named {username!r} exists. Create the user first, or pass --create-missing "
                "to create one (fresh install only)."
            )

        # The owner's user exists: ensuring the profile is safe (nothing stray is created).
        profile = ensure_default_profile(Profile, KEY_FEES, profile_name)

        if user is None:
            user = self._create_user(User, username, make_admin)
        else:
            self._update_existing_user(user, make_admin, reset_password)

        ProfileMembership.objects.update_or_create(
            user=user,
            profile=profile,
            defaults={"role": ROLE_EDITOR, "suspended": False, "program": KEY_FEES},
        )

        program_name = get_names().get(KEY_FEES, "Fee Register")
        admin_word = "Admin" if user.is_superuser else "not Admin"
        self.stdout.write(
            self.style.SUCCESS(
                f"User {user.username} ready: {admin_word}, Editor in {program_name} profile {profile.name}"
            )
        )

    def _resolve_user(self, matches, username):
        """The single user to use, preferring an exact-case match if several differ only by case."""
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0]
        exact = [m for m in matches if m.username == username]
        if len(exact) == 1:
            return exact[0]
        raise CommandError(
            f"More than one user matches {username!r} (case-insensitively). Pass the exact username."
        )

    def _update_existing_user(self, user, make_admin, reset_password):
        """Promote to Admin (if asked), set landing_program, and reset the password only if asked."""
        update_fields = set()
        if make_admin and not user.is_superuser:
            user.is_superuser = True
            update_fields.add("is_superuser")
        if user.landing_program != KEY_FEES:
            user.landing_program = KEY_FEES
            update_fields.add("landing_program")
        if reset_password:
            password = self._read_password(user)
            user.set_password(password)
            update_fields.add("password")
        if update_fields:
            user.save(update_fields=update_fields)

    def _create_user(self, User, username, make_admin):
        """Create a new user (only reached with --create-missing). Reads and validates a password."""
        user = User(username=username, is_superuser=bool(make_admin), landing_program=KEY_FEES)
        try:
            user.full_clean(exclude=["password"])
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        password = self._read_password(user)
        user.set_password(password)
        user.save()
        return user

    def _read_password(self, user):
        """Read a password from FEES_USER_PASSWORD or two getpass prompts, then validate it.

        The password is never taken from an argument, printed or stored outside the user's password hash.
        """
        password = os.environ.get("FEES_USER_PASSWORD", "")
        if not password:
            if sys.stdin.isatty():
                password = getpass.getpass("Password: ")
                if getpass.getpass("Password (again): ") != password:
                    raise CommandError("Passwords do not match.")
            else:
                raise CommandError(
                    "FEES_USER_PASSWORD must be set (no terminal to prompt on)."
                )
        try:
            validate_password(password, user)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        return password
