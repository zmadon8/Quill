"""Tests for the ``create_fees_user`` bootstrap command (T1.10, R-ACC-1, design section 9).

The command attaches a Fee Register profile and Editor membership to an EXISTING user; it never
creates a second account unless ``--create-missing`` is given. No user or password is created outside
the test database: every creation here happens in the test DB through the command under test.
"""
from io import StringIO
from unittest import mock

from django.contrib.auth import authenticate, get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from accounts.models import ROLE_EDITOR, ROLE_READER, Profile, ProfileMembership
from accounts.suite import KEY_FEES

User = get_user_model()

# Test-only strings. Never a real secret; the "no secret is printed" test asserts this never leaks.
VALID_PASSWORD = "Fees-Test-Pw-9271"
OTHER_PASSWORD = "Second-Test-Pw-5048"
WEAK_PASSWORD = "123"


@override_settings(SECURE_SSL_REDIRECT=False)
class CreateFeesUserTests(TestCase):
    def setUp(self):
        # The owner's existing user, as on the live site (not an Admin yet).
        self.user = User.objects.create_user(
            username="Ziyad", password=VALID_PASSWORD, is_superuser=False
        )
        self.initial_user_count = User.objects.count()

    def run_command(self, **kwargs):
        out = StringIO()
        call_command("create_fees_user", stdout=out, **kwargs)
        return out.getvalue()

    def fees_profile(self, name="Ziyad-Fees"):
        return Profile.objects.filter(program=KEY_FEES, name__iexact=name, deleted_at__isnull=True).first()

    # --- Existing user (the owner's case) --------------------------------------------------------

    def test_existing_user_gets_one_membership_admin_and_landing_no_second_user(self):
        self.run_command(username="Ziyad", profile="Ziyad-Fees", make_admin=True)

        # No second user row was created.
        self.assertEqual(User.objects.count(), self.initial_user_count)

        profile = self.fees_profile()
        self.assertIsNotNone(profile)

        memberships = ProfileMembership.objects.filter(user=self.user, profile=profile)
        self.assertEqual(memberships.count(), 1)
        membership = memberships.get()
        self.assertEqual(membership.role, ROLE_EDITOR)
        self.assertFalse(membership.suspended)
        self.assertEqual(membership.program, KEY_FEES)

        self.user.refresh_from_db()
        self.assertTrue(self.user.is_superuser)
        self.assertTrue(self.user.is_staff)  # kept in step by User.save
        self.assertEqual(self.user.landing_program, "fees")

        # The password was not changed: the original one still authenticates.
        self.assertIsNotNone(authenticate(username="Ziyad", password=VALID_PASSWORD))

    def test_second_run_is_a_no_op(self):
        self.run_command(username="Ziyad", profile="Ziyad-Fees", make_admin=True)
        self.run_command(username="Ziyad", profile="Ziyad-Fees", make_admin=True)

        self.assertEqual(User.objects.count(), self.initial_user_count)
        profile = self.fees_profile()
        self.assertEqual(
            ProfileMembership.objects.filter(user=self.user, profile=profile).count(), 1
        )
        self.assertEqual(Profile.objects.filter(program=KEY_FEES, name__iexact="Ziyad-Fees").count(), 1)

    def test_existing_reader_membership_is_upgraded_to_editor(self):
        profile = Profile.objects.create(program=KEY_FEES, name="Ziyad-Fees")
        ProfileMembership.objects.create(
            user=self.user, profile=profile, program=KEY_FEES, role=ROLE_READER
        )

        self.run_command(username="Ziyad", profile="Ziyad-Fees", make_admin=True)

        membership = ProfileMembership.objects.get(user=self.user, profile=profile)
        self.assertEqual(membership.role, ROLE_EDITOR)
        self.assertEqual(ProfileMembership.objects.filter(user=self.user, profile=profile).count(), 1)

    def test_no_admin_does_not_promote(self):
        self.run_command(username="Ziyad", profile="Ziyad-Fees", make_admin=False)

        self.user.refresh_from_db()
        self.assertFalse(self.user.is_superuser)
        self.assertFalse(self.user.is_staff)
        # Still gets the membership and landing program.
        self.assertEqual(self.user.landing_program, "fees")
        profile = self.fees_profile()
        self.assertEqual(ProfileMembership.objects.filter(user=self.user, profile=profile).count(), 1)

    def test_case_insensitive_username_match(self):
        # The existing user is "Ziyad"; a lower-case argument resolves to the same user, no new row.
        self.run_command(username="ziyad", profile="Ziyad-Fees", make_admin=True)

        self.assertEqual(User.objects.count(), self.initial_user_count)
        profile = self.fees_profile()
        self.assertEqual(ProfileMembership.objects.filter(user=self.user, profile=profile).count(), 1)

    def test_password_is_never_printed(self):
        output = self.run_command(username="Ziyad", profile="Ziyad-Fees", make_admin=True)
        self.assertNotIn(VALID_PASSWORD, output)
        self.assertIn("Ziyad", output)
        self.assertIn("Ziyad-Fees", output)

    # --- Reset password on an existing user ------------------------------------------------------

    @mock.patch.dict("os.environ", {"FEES_USER_PASSWORD": OTHER_PASSWORD})
    def test_reset_password_changes_password(self):
        self.run_command(
            username="Ziyad", profile="Ziyad-Fees", make_admin=True, reset_password=True
        )
        # The new password authenticates; the old one no longer does.
        self.assertIsNotNone(authenticate(username="Ziyad", password=OTHER_PASSWORD))
        self.assertIsNone(authenticate(username="Ziyad", password=VALID_PASSWORD))

    @mock.patch.dict("os.environ", {"FEES_USER_PASSWORD": OTHER_PASSWORD})
    def test_reset_password_output_has_no_secret(self):
        output = self.run_command(
            username="Ziyad", profile="Ziyad-Fees", make_admin=True, reset_password=True
        )
        self.assertNotIn(OTHER_PASSWORD, output)

    # --- Missing user ----------------------------------------------------------------------------

    def test_missing_user_without_create_missing_is_refused(self):
        with self.assertRaises(CommandError):
            self.run_command(username="Nobody", profile="New-Fees", make_admin=True)

        # No user created, and the profile was refused before it could be created.
        self.assertEqual(User.objects.count(), self.initial_user_count)
        self.assertFalse(User.objects.filter(username__iexact="Nobody").exists())
        self.assertIsNone(self.fees_profile("New-Fees"))
        self.assertFalse(ProfileMembership.objects.filter(program=KEY_FEES, profile__name="New-Fees").exists())

    @mock.patch.dict("os.environ", {"FEES_USER_PASSWORD": VALID_PASSWORD})
    def test_create_missing_creates_user_and_membership(self):
        self.run_command(
            username="Fresh", profile="Fresh-Fees", make_admin=True, create_missing=True
        )

        self.assertEqual(User.objects.count(), self.initial_user_count + 1)
        new_user = User.objects.get(username="Fresh")
        self.assertTrue(new_user.is_superuser)
        self.assertTrue(new_user.is_staff)
        self.assertEqual(new_user.landing_program, "fees")
        self.assertIsNotNone(authenticate(username="Fresh", password=VALID_PASSWORD))

        profile = self.fees_profile("Fresh-Fees")
        self.assertIsNotNone(profile)
        membership = ProfileMembership.objects.get(user=new_user, profile=profile)
        self.assertEqual(membership.role, ROLE_EDITOR)
        self.assertEqual(membership.program, KEY_FEES)

    @mock.patch.dict("os.environ", {"FEES_USER_PASSWORD": VALID_PASSWORD})
    def test_create_missing_without_make_admin_is_not_superuser(self):
        self.run_command(
            username="Fresh", profile="Fresh-Fees", make_admin=False, create_missing=True
        )
        new_user = User.objects.get(username="Fresh")
        self.assertFalse(new_user.is_superuser)

    @mock.patch.dict("os.environ", {"FEES_USER_PASSWORD": WEAK_PASSWORD})
    def test_create_missing_weak_password_is_refused(self):
        with self.assertRaises(CommandError):
            self.run_command(
                username="Fresh", profile="Fresh-Fees", make_admin=True, create_missing=True
            )
        self.assertEqual(User.objects.count(), self.initial_user_count)
        self.assertFalse(User.objects.filter(username="Fresh").exists())

    @mock.patch.dict("os.environ", {"FEES_USER_PASSWORD": VALID_PASSWORD})
    def test_create_missing_never_prints_password(self):
        output = self.run_command(
            username="Fresh", profile="Fresh-Fees", make_admin=True, create_missing=True
        )
        self.assertNotIn(VALID_PASSWORD, output)
