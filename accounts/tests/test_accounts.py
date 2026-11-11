from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.forms import THROTTLE_MESSAGE
from accounts import suite
from accounts.models import FailedLogin, Profile, ProfileMembership, SuiteName
from accounts.profiles import assign_unassigned_users, live_memberships, delete_profile, ensure_default_profile, get_profile_for
from accounts.permissions import (
    admin_required,
    program_editor_required,
    program_reader_required,
    program_role,
    reader_required,
)

User = get_user_model()
PASSWORD = "correct-horse-battery-9"


@override_settings(SECURE_SSL_REDIRECT=False)
class BaseCase(TestCase):
    def make_user(self, username, admin=False, active=True, role=None):
        """A user; with ``role`` ("editor" or "reader") they also join Main with that role."""
        user = User.objects.create_user(
            username=username,
            password=PASSWORD,
            is_superuser=admin,
            is_active=active,
        )
        if role is not None:
            ProfileMembership.objects.create(user=user, profile=ensure_default_profile(), role=role)
        return user

    def setUp(self):
        self.admin = self.make_user("boss", admin=True)
        self.user = self.make_user("alice")
        for member, role in ((self.admin, "editor"), (self.user, "reader")):
            ProfileMembership.objects.create(user=member, profile=ensure_default_profile(), role=role)


class LoginTests(BaseCase):
    def test_login_success(self):
        resp = self.client.post(reverse("login"), {"username": "alice", "password": PASSWORD})
        self.assertRedirects(resp, reverse("home"))

    def test_login_failure(self):
        resp = self.client.post(reverse("login"), {"username": "alice", "password": "wrong"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(FailedLogin.objects.filter(username_lower="alice").count(), 1)

    def test_disabled_user_cannot_login(self):
        self.make_user("gone", active=False)
        resp = self.client.post(reverse("login"), {"username": "gone", "password": PASSWORD})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_is_post_only(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.client.post(reverse("logout"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_throttle_blocks_sixth_attempt_even_with_right_password(self):
        for _ in range(5):
            self.client.post(reverse("login"), {"username": "Alice", "password": "wrong"})
        resp = self.client.post(reverse("login"), {"username": "alice", "password": PASSWORD})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, THROTTLE_MESSAGE)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_other_ip_cannot_lock_out_the_real_user(self):
        for _ in range(5):
            self.client.post(
                reverse("login"), {"username": "alice", "password": "wrong"}, REMOTE_ADDR="9.9.9.9"
            )
        resp = self.client.post(
            reverse("login"), {"username": "alice", "password": PASSWORD}, REMOTE_ADDR="5.5.5.5"
        )
        self.assertRedirects(resp, reverse("home"))

    def test_same_ip_is_blocked_after_20_failures_for_any_username(self):
        now = timezone.now()
        for i in range(20):
            FailedLogin.objects.create(username_lower=f"user{i}", ip="9.9.9.9", at=now)
        resp = self.client.post(
            reverse("login"), {"username": "alice", "password": PASSWORD}, REMOTE_ADDR="9.9.9.9"
        )
        self.assertContains(resp, THROTTLE_MESSAGE)

    def test_failed_login_prunes_rows_older_than_a_day(self):
        FailedLogin.objects.create(username_lower="stale", ip="1.1.1.1", at=timezone.now() - timedelta(days=2))
        self.client.post(reverse("login"), {"username": "alice", "password": "wrong"})
        self.assertFalse(FailedLogin.objects.filter(username_lower="stale").exists())

    def test_overlong_username_is_not_recorded(self):
        self.client.post(reverse("login"), {"username": "x" * 300, "password": "wrong"})
        self.assertFalse(FailedLogin.objects.exists())

    def test_throttle_resets_after_15_minutes(self):
        old = timezone.now() - timedelta(minutes=16)
        for _ in range(5):
            FailedLogin.objects.create(username_lower="alice", ip="1.2.3.4", at=old)
        resp = self.client.post(reverse("login"), {"username": "alice", "password": PASSWORD})
        self.assertRedirects(resp, reverse("home"))

    def test_success_clears_failures(self):
        self.client.post(reverse("login"), {"username": "alice", "password": "wrong"})
        self.client.post(reverse("login"), {"username": "alice", "password": PASSWORD})
        self.assertFalse(FailedLogin.objects.filter(username_lower="alice").exists())


class LandingProgramTests(BaseCase):
    def login(self, next_url=None, username="alice"):
        data = {"username": username, "password": PASSWORD}
        if next_url is not None:
            data["next"] = next_url
        return self.client.post(reverse("login"), data)

    def choose(self, user, key="diary"):
        User.objects.filter(pk=user.pk).update(landing_program=key)

    def test_default_is_home(self):
        self.assertEqual(self.user.landing_program, "")
        self.assertRedirects(self.login(), reverse("home"))

    def test_chosen_program_is_the_landing_page(self):
        self.choose(self.user)
        self.assertRedirects(self.login(), reverse("diary_home"))

    def test_safe_next_wins(self):
        self.choose(self.user)
        resp = self.login(next_url=reverse("my_settings"))
        self.assertRedirects(resp, reverse("my_settings"))

    def test_unsafe_next_is_ignored(self):
        self.choose(self.user)
        resp = self.login(next_url="https://evil.example.com/x")
        self.assertRedirects(resp, reverse("diary_home"))

    def test_no_profile_falls_back_to_home(self):
        loner = self.make_user("loner")
        self.choose(loner)
        self.assertRedirects(self.login(username="loner"), reverse("home"))

    def test_unknown_stored_value_falls_back_to_home(self):
        self.choose(self.user, "nonsense")
        self.assertRedirects(self.login(), reverse("home"))

    def test_already_signed_in_visit_to_login_uses_the_landing_page(self):
        self.choose(self.user)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("login"))
        self.assertRedirects(resp, reverse("diary_home"))

    def test_login_redirect_setting_stays_home(self):
        from django.conf import settings

        self.assertEqual(settings.LOGIN_REDIRECT_URL, "home")

    def test_user_sets_own_landing_program(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("my_settings"), {"tab": "start"})
        self.assertContains(resp, "Open after login")
        self.assertContains(resp, 'value="diary"')
        resp = self.client.post(reverse("my_settings"), {"landing_program": "diary"})
        self.assertRedirects(resp, reverse("my_settings"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.landing_program, "diary")
        self.client.post(reverse("my_settings"), {"landing_program": ""})
        self.user.refresh_from_db()
        self.assertEqual(self.user.landing_program, "")

    def test_my_settings_needs_sign_in_and_is_linked_from_home(self):
        self.assertEqual(self.client.get(reverse("my_settings")).status_code, 302)
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("home")), reverse("my_settings"))

    def test_user_without_profile_only_sees_home_choice(self):
        loner = self.make_user("loner")
        self.client.force_login(loner)
        self.assertNotContains(self.client.get(reverse("my_settings"), {"tab": "start"}), 'value="diary"')
        resp = self.client.post(reverse("my_settings"), {"landing_program": "diary"})
        self.assertEqual(resp.status_code, 200)
        loner.refresh_from_db()
        self.assertEqual(loner.landing_program, "")

    def test_invalid_value_is_rejected(self):
        self.client.force_login(self.user)
        resp = self.client.post(reverse("my_settings"), {"landing_program": "nonsense"})
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.landing_program, "")

    def test_user_cannot_change_another_users_setting(self):
        self.client.force_login(self.user)
        self.client.post(reverse("my_settings"), {"landing_program": "diary", "id": self.admin.pk})
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.landing_program, "")
        resp = self.client.post(
            reverse("user_edit", args=[self.admin.pk]), {"username": "boss", "landing_program": "diary"}
        )
        self.assertEqual(resp.status_code, 403)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.landing_program, "")

    def test_admin_sets_it_on_user_edit(self):
        self.client.force_login(self.admin)
        url = reverse("user_edit", args=[self.user.pk])
        self.assertContains(self.client.get(url), "Open after login")
        resp = self.client.post(
            url,
            {
                "username": "alice",
                "is_active": "on",
                f"profile_{ensure_default_profile().pk}": "reader",
                "landing_program": "diary",
            },
        )
        self.assertRedirects(resp, reverse("user_list"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.landing_program, "diary")

    def test_admin_edit_rejects_invalid_value(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("user_edit", args=[self.user.pk]),
            {"username": "alice", "is_active": "on", "landing_program": "nonsense"},
        )
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.landing_program, "")


class AccessTests(BaseCase):
    def test_anonymous_redirected_to_login(self):
        for url in ["/", "/users/", "/users/new/"]:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302, url)
            self.assertTrue(resp["Location"].startswith(reverse("login")), url)

    def test_non_admin_gets_403(self):
        self.client.force_login(self.user)
        urls = [
            reverse("user_list"),
            reverse("user_create"),
            reverse("user_edit", args=[self.admin.pk]),
            reverse("user_delete", args=[self.admin.pk]),
        ]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertEqual(self.client.post(urls[3]).status_code, 403)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())


class SuiteSettingsTests(BaseCase):
    def post(self, home="Home", diary="Case Law Diary", fees="Fee Register"):
        # T1.8 registered the Fee Register, so the shared rename form now has a (required) fees field too.
        return self.client.post(
            reverse("settings"), {"home_name": home, "diary_name": diary, "fees_name": fees}
        )

    def test_defaults_without_rows(self):
        self.assertEqual(SuiteName.objects.count(), 0)
        # T1.3: the Fee Register default joins the suite. Home and the diary are unchanged.
        self.assertEqual(
            suite.get_names(),
            {"home": "Home", "diary": "Case Law Diary", "fees": "Fee Register", "investments": "Investments"},
        )
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, ">Home</a>")
        self.assertContains(resp, "<title>Home</title>")
        self.assertContains(resp, "Case Law Diary")
        self.assertNotContains(resp, "Judgment Diary")

    def test_program_header_uses_program_name(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("diary_home"))
        self.assertContains(resp, 'aria-label="Case Law Diary: Home">Case Law Diary</a>')

    def test_admin_only(self):
        editor = self.make_user("ed", role="editor")
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("settings")).status_code, 403)
        self.assertEqual(self.post(diary="Hacked").status_code, 403)
        self.client.force_login(editor)
        self.assertEqual(self.client.get(reverse("settings")).status_code, 403)
        self.assertEqual(SuiteName.objects.count(), 0)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("settings")).status_code, 302)

    def test_settings_link_only_for_admin(self):
        # Page Names is the Names page of the Display tab, for an Admin only.
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("my_settings"), {"tab": "display"}), 'href="%s"' % reverse("settings"))
        self.assertNotContains(self.client.get(reverse("my_settings")), 'href="%s"' % reverse("settings"))
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse("my_settings"), {"tab": "display"}), 'href="%s"' % reverse("settings"))
        self.assertNotContains(self.client.get(reverse("home")), 'href="%s"' % reverse("settings"))

    def test_rename_shows_everywhere(self):
        self.client.force_login(self.admin)
        resp = self.post(home="  Start   Page ", diary="Judgments")
        self.assertRedirects(resp, reverse("settings"))
        self.assertEqual(
            suite.get_names(),
            {"home": "Start Page", "diary": "Judgments", "fees": "Fee Register", "investments": "Investments"},
        )
        home = self.client.get(reverse("home"))
        self.assertContains(home, ">Start Page</a>")
        self.assertContains(home, 'class="program-link" href="%s">Judgments</a>' % reverse("diary_home"))
        self.assertContains(self.client.get(reverse("diary_home")), 'aria-label="Judgments: Home">Judgments</a>')
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("home")), ">Start Page</a>")

    def test_form_shows_current_names(self):
        suite.set_names({"diary": "Judgments"})
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("settings")), 'value="Judgments"')

    def test_validation(self):
        self.client.force_login(self.admin)
        for home, diary in (("", "X"), ("   ", "X"), ("H", ""), ("x" * 61, "X"), ("Same", " same "), ("Home", "HOME")):
            resp = self.post(home=home, diary=diary)
            self.assertEqual(resp.status_code, 200, (home, diary))
            self.assertTrue(resp.context["form"].errors, (home, diary))
        self.assertEqual(SuiteName.objects.count(), 0)

    def test_saving_twice_updates_rows(self):
        self.client.force_login(self.admin)
        self.post(diary="One")
        self.post(diary="Two")
        self.assertEqual(SuiteName.objects.filter(key="diary").count(), 1)
        self.assertEqual(suite.get_names()["diary"], "Two")

    def test_fees_default_name_is_available_and_shown_once_registered(self):
        # T1.8 registers the Fee Register (fees/apps.py ready), so the shared Settings screen now shows a
        # Fee Register name field alongside Home and the Case Law Diary. Before T1.8 this test asserted the
        # field was absent while fees was unregistered; registering fees is intended (R-SH-3), so the
        # expectation now reflects the registered program while the Home and diary fields are unchanged.
        from accounts import programs

        self.assertEqual(suite.get_names()[suite.KEY_FEES], "Fee Register")
        self.assertIn(suite.KEY_FEES, programs.program_keys())
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("settings"))
        self.assertEqual(resp.status_code, 200)
        form = resp.context["form"]
        # The Site name comes first; the Words/Logo choice per program (home_brand, diary_brand, fees_brand) sits
        # after the names.
        self.assertEqual(
            list(form.fields),
            ["site_name", "home_name", "diary_name", "fees_name", "investments_name",
             "home_brand", "diary_brand", "fees_brand", "investments_brand"],
        )
        self.assertEqual(form.fields["fees_name"].initial, "Fee Register")
        self.assertEqual(form.fields["fees_name"].label, "Fee Register name")
        self.assertContains(resp, "Fee Register")

    def test_fees_field_appears_because_fees_is_registered(self):
        # The Fee Register is registered at startup (T1.8). Confirm the shared form carries its field and
        # that the diary is still present too.
        from accounts import programs
        from accounts.forms import SuiteNamesForm

        self.assertIn(suite.KEY_FEES, programs.program_keys())
        form = SuiteNamesForm()
        self.assertIn("fees_name", form.fields)
        self.assertIn("diary_name", form.fields)
        self.assertEqual(form.fields["fees_name"].initial, "Fee Register")
        self.assertEqual(form.fields["fees_name"].label, "Fee Register name")


class UserAdminTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_list(self):
        resp = self.client.get(reverse("user_list"))
        self.assertContains(resp, "alice")

    def test_create(self):
        resp = self.client.post(
            reverse("user_create"),
            {"username": "bob", "password1": PASSWORD, "password2": PASSWORD, "is_admin": "on"},
        )
        self.assertRedirects(resp, reverse("user_list"))
        bob = User.objects.get(username="bob")
        self.assertTrue(bob.is_superuser)
        self.assertTrue(bob.check_password(PASSWORD))

    def test_create_rejects_weak_password(self):
        resp = self.client.post(
            reverse("user_create"),
            {"username": "bob", "password1": "12345678", "password2": "12345678"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username="bob").exists())

    def test_edit_disable_and_password(self):
        resp = self.client.post(
            reverse("user_edit", args=[self.user.pk]),
            {"username": "alice2", "new_password": "another-good-pass-77"},
        )
        self.assertRedirects(resp, reverse("user_list"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "alice2")
        self.assertFalse(self.user.is_active)
        self.assertTrue(self.user.check_password("another-good-pass-77"))

    def test_edit_promote_to_admin(self):
        self.client.post(
            reverse("user_edit", args=[self.user.pk]),
            {"username": "alice", "is_active": "on", "is_admin": "on"},
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_superuser)

    def test_delete_keeps_the_user_for_restore(self):
        # Round 18 (D94): deleting switches the account off and lists it under Deleted users for 30 days.
        url = reverse("user_delete", args=[self.user.pk])
        self.assertContains(self.client.get(url), "alice")
        self.assertContains(self.client.get(url), "restore them from")
        self.assertRedirects(self.client.post(url), reverse("user_list"))
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.deleted_at)
        self.assertFalse(self.user.is_active)
        self.assertTrue(self.user.was_active)
        self.assertEqual(self.user.deleted_by_name, "boss")
        self.assertTrue(ProfileMembership.objects.filter(user=self.user).exists())  # kept for the restore
        page = self.client.get(reverse("user_list")).content.decode()
        deleted_part = page.split("<h2>Deleted users</h2>")[1]
        self.assertIn("alice", deleted_part)
        self.assertIn(reverse("user_restore", args=[self.user.pk]), deleted_part)
        self.assertNotIn(reverse("user_edit", args=[self.user.pk]), page)
        self.assertEqual(self.client.get(reverse("user_edit", args=[self.user.pk])).status_code, 404)
        self.assertEqual(self.client.post(url).status_code, 404)  # already deleted

    def test_a_deleted_user_cannot_sign_in_and_restore_brings_them_back(self):
        role = program_role(self.user, "diary")
        self.client.post(reverse("user_delete", args=[self.user.pk]))
        other = self.client_class()
        self.assertFalse(other.login(username="alice", password=PASSWORD))
        self.assertEqual(self.client.get(reverse("user_restore", args=[self.user.pk])).status_code, 405)
        self.assertRedirects(self.client.post(reverse("user_restore", args=[self.user.pk])), reverse("user_list"))
        self.user.refresh_from_db()
        self.assertIsNone(self.user.deleted_at)
        self.assertTrue(self.user.is_active)
        self.assertEqual(program_role(self.user, "diary"), role)
        self.assertTrue(other.login(username="alice", password=PASSWORD))
        self.assertEqual(self.client.post(reverse("user_restore", args=[self.user.pk])).status_code, 404)

    def test_restore_keeps_a_disabled_user_disabled(self):
        self.user.is_active = False
        self.user.save()
        self.client.post(reverse("user_delete", args=[self.user.pk]))
        self.client.post(reverse("user_restore", args=[self.user.pk]))
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertIsNone(self.user.deleted_at)

    def test_a_deleted_user_keeps_their_username_and_email(self):
        self.user.email = "alice@example.com"
        self.user.save()
        self.client.post(reverse("user_delete", args=[self.user.pk]))
        resp = self.client.post(reverse("user_create"), {"username": "newbie", "email": "ALICE@example.com",
                                                         "password1": PASSWORD, "password2": PASSWORD})
        self.assertContains(resp, "Another account already uses this email address.")
        resp = self.client.post(reverse("user_create"), {"username": "alice", "password1": PASSWORD,
                                                         "password2": PASSWORD})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(User.objects.filter(username__iexact="alice").count(), 1)

    def test_cannot_delete_self(self):
        other = self.make_user("second", admin=True)
        url = reverse("user_delete", args=[self.admin.pk])
        self.client.post(url)
        self.assertTrue(User.objects.filter(pk=self.admin.pk, deleted_at__isnull=True).exists())
        self.assertTrue(User.objects.filter(pk=other.pk, deleted_at__isnull=True).exists())

    def test_cannot_disable_self(self):
        self.make_user("second", admin=True)
        resp = self.client.post(
            reverse("user_edit", args=[self.admin.pk]),
            {"username": "boss", "is_admin": "on"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "cannot disable your own account")
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_cannot_remove_last_admin_rights(self):
        resp = self.client.post(
            reverse("user_edit", args=[self.admin.pk]),
            {"username": "boss", "is_active": "on"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "last active Admin")
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_superuser)

    def test_cannot_delete_self_even_if_other_admin_is_disabled(self):
        # The only active Admin can never be deleted: self-delete is refused, and no other
        # active Admin exists to do it. A disabled Admin does not change that.
        inactive = self.make_user("old", admin=True, active=False)
        self.client.post(reverse("user_delete", args=[self.admin.pk]))
        self.assertTrue(User.objects.filter(pk=self.admin.pk, deleted_at__isnull=True).exists())
        self.assertTrue(User.objects.filter(pk=inactive.pk, deleted_at__isnull=True).exists())

    def test_admin_can_delete_a_disabled_admin(self):
        inactive = self.make_user("old", admin=True, active=False)
        self.client.post(reverse("user_delete", args=[inactive.pk]))
        self.assertTrue(User.objects.filter(pk=inactive.pk, deleted_at__isnull=False).exists())

    def test_can_remove_admin_rights_from_one_of_two(self):
        second = self.make_user("second", admin=True)
        resp = self.client.post(
            reverse("user_edit", args=[second.pk]),
            {"username": "second", "is_active": "on"},
        )
        self.assertRedirects(resp, reverse("user_list"))
        second.refresh_from_db()
        self.assertFalse(second.is_superuser)


class CreateFirstAdminTests(TestCase):
    def run_command(self):
        call_command("create_first_admin", stdout=StringIO())

    def test_creates_once_then_refuses(self):
        env = {"DJANGO_SUPERUSER_USERNAME": "root", "DJANGO_SUPERUSER_PASSWORD": PASSWORD}
        with mock.patch.dict("os.environ", env):
            self.run_command()
            user = User.objects.get(username="root")
            self.assertTrue(user.is_superuser)
            self.assertTrue(user.check_password(PASSWORD))
            with self.assertRaises(CommandError):
                self.run_command()
        self.assertEqual(User.objects.count(), 1)

    def test_rejects_weak_password(self):
        env = {"DJANGO_SUPERUSER_USERNAME": "root", "DJANGO_SUPERUSER_PASSWORD": "123"}
        with mock.patch.dict("os.environ", env):
            with self.assertRaises(CommandError):
                self.run_command()
        self.assertFalse(User.objects.exists())

    def test_refuses_if_any_user_exists(self):
        User.objects.create_user("someone", password=PASSWORD)
        env = {"DJANGO_SUPERUSER_USERNAME": "root", "DJANGO_SUPERUSER_PASSWORD": PASSWORD}
        with mock.patch.dict("os.environ", env):
            with self.assertRaises(CommandError):
                self.run_command()


class RoleTests(BaseCase):
    def test_new_user_is_not_admin_and_has_no_role(self):
        user = User.objects.create_user("plain", password=PASSWORD)
        self.assertFalse(user.is_superuser)
        self.assertFalse(hasattr(user, "role"))
        self.assertIsNone(program_role(user, "diary"))

    def test_create_form_offers_no_access_by_default_and_not_admin(self):
        self.client.force_login(self.admin)
        form = self.client.get(reverse("user_create")).context["form"]
        main = ensure_default_profile()
        self.assertEqual(form.fields[f"profile_{main.pk}"].initial, "")
        self.assertFalse(form.fields["is_admin"].initial)

    def test_user_form_has_one_line_per_profile(self):
        # Round 18 (D95): one "No access / Editor / Reader" choice per live profile.
        Profile.objects.create(program="diary", name="Junior")
        Profile.objects.create(program="diary", name="Gone", deleted_at=timezone.now())
        self.client.force_login(self.admin)
        for url in (reverse("user_create"), reverse("user_edit", args=[self.user.pk])):
            resp = self.client.get(url)
            html = resp.content.decode()
            box = html.split("data-profile-access")[1].split("</fieldset>")[0]
            self.assertEqual(box.count('class="profile-row"'), 2, url)
            for name in ("Main", "Junior"):
                self.assertIn(f">{name}:</label>", box, url)
            self.assertNotIn("Gone", box, url)
            for label in ("No access", "Editor", "Reader"):
                self.assertIn(label, box, url)
            self.assertNotContains(resp, "at most one profile per program")

    def test_is_staff_follows_superuser_flag(self):
        a = User.objects.create_user("a", password=PASSWORD, is_superuser=True)
        self.assertTrue(a.is_staff)
        a.is_superuser = False
        a.save()
        a.refresh_from_db()
        self.assertEqual((a.is_superuser, a.is_staff), (False, False))

    def test_program_role_is_per_membership(self):
        ed = self.make_user("ed", role="editor")
        self.assertEqual(program_role(ed, "diary"), "editor")
        self.assertEqual(program_role(self.user, "diary"), "reader")
        # Admin is suite-wide; inside a program the membership role applies.
        self.assertEqual(program_role(self.admin, "diary"), "editor")
        self.assertTrue(self.admin.is_admin)
        self.assertFalse(ed.is_admin)
        self.assertIsNone(program_role(self.make_user("none"), "diary"))
        self.assertIsNone(program_role(AnonymousUser(), "diary"))

    def test_role_differs_per_profile(self):
        junior = Profile.objects.create(program="diary", name="Junior")
        ProfileMembership.objects.filter(user=self.user).delete()
        ProfileMembership.objects.create(user=self.user, profile=junior, role="editor")
        self.assertEqual(program_role(self.user, "diary"), "editor")
        self.assertEqual(get_profile_for(self.user), junior)

    def test_deleted_profile_gives_no_role(self):
        gone = Profile.objects.create(program="diary", name="Gone", deleted_at=timezone.now())
        member = User.objects.create_user("gm", password=PASSWORD)
        ProfileMembership.objects.create(user=member, profile=gone, role="editor")
        self.assertIsNone(program_role(member, "diary"))

    def test_create_first_admin_makes_admin_role(self):
        env = {"DJANGO_SUPERUSER_USERNAME": "root2", "DJANGO_SUPERUSER_PASSWORD": PASSWORD}
        with mock.patch.dict("os.environ", env):
            User.objects.all().delete()
            call_command("create_first_admin", stdout=StringIO())
        root = User.objects.get(username="root2")
        self.assertTrue(root.is_superuser)
        self.assertEqual(program_role(root, "diary"), "editor")

    def test_decorators(self):
        def view(request):
            return HttpResponse("ok")

        rf = RequestFactory()

        def call(decorator, user):
            request = rf.get("/x/")
            request.user = user
            return decorator(view)(request)

        editor = self.make_user("ed", role="editor")
        editor_view = program_editor_required("diary")
        reader_view = program_reader_required("diary")
        outsider = self.make_user("outsider")
        for decorator in (admin_required, editor_view, reader_view, reader_required):
            self.assertEqual(call(decorator, AnonymousUser()).status_code, 302)
        self.assertEqual(call(admin_required, self.admin).status_code, 200)
        self.assertEqual(call(editor_view, self.admin).status_code, 200)  # Admin with Editor membership
        self.assertEqual(call(editor_view, editor).status_code, 200)
        self.assertEqual(call(reader_view, self.user).status_code, 200)
        self.assertEqual(call(reader_view, editor).status_code, 200)
        self.assertEqual(call(reader_required, self.user).status_code, 200)
        with self.assertRaises(PermissionDenied):
            call(admin_required, editor)
        with self.assertRaises(PermissionDenied):
            call(editor_view, self.user)  # Reader refused
        with self.assertRaises(PermissionDenied):
            call(editor_view, outsider)
        with self.assertRaises(PermissionDenied):
            call(reader_view, outsider)
        # Owner's rule: "an 'Admin' is an 'Admin' for all sub-programs". An Admin whose own membership is Reader
        # still works as an Editor (this used to be refused).
        ProfileMembership.objects.filter(user=self.admin).update(role="reader")
        self.assertEqual(call(editor_view, self.admin).status_code, 200)
        self.assertEqual(program_role(self.admin, "diary"), "editor")

    def test_header_shows_username_only_and_user_list_shows_role(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, 'class="who" href="%s"' % reverse("my_settings"))
        self.assertContains(resp, ">alice</a>")
        self.assertNotContains(resp, "Reader")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("user_list")), "Reader")


    def test_editor_and_reader_refused_on_admin_screens(self):
        editor = self.make_user("ed", role="editor")
        target = reverse("user_edit", args=[self.user.pk])
        urls = [
            reverse("user_list"), reverse("user_create"), target,
            reverse("user_delete", args=[self.user.pk]),
            reverse("backup_list"), reverse("restore_upload"),
        ]
        for who in (editor, self.user):
            self.client.force_login(who)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 403, (who.username, url))
            resp = self.client.post(target, {"username": "alice", "is_active": "on", "is_admin": "on"})
            self.assertEqual(resp.status_code, 403)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_superuser)

    def test_admin_changes_role_in_profile(self):
        self.client.force_login(self.admin)
        main = ensure_default_profile()
        self.client.post(
            reverse("user_edit", args=[self.user.pk]),
            {"username": "alice", "is_active": "on", f"profile_{main.pk}": "editor"},
        )
        self.user.refresh_from_db()
        self.assertEqual(program_role(self.user, "diary"), "editor")
        self.assertFalse(self.user.is_superuser)
        self.assertEqual(ProfileMembership.objects.filter(user=self.user).count(), 1)

    def test_each_profile_has_its_own_role(self):
        self.client.force_login(self.admin)
        main = ensure_default_profile()
        junior = Profile.objects.create(program="diary", name="Junior")
        self.client.post(
            reverse("user_edit", args=[self.user.pk]),
            {"username": "alice", "is_active": "on", f"profile_{junior.pk}": "editor", f"profile_{main.pk}": "reader"},
        )
        roles = dict(ProfileMembership.objects.filter(user=self.user).values_list("profile__name", "role"))
        self.assertEqual(roles, {"Junior": "editor", "Main": "reader"})

    def test_invalid_role_rejected(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("user_edit", args=[self.user.pk]),
            {"username": "alice", "is_active": "on", f"profile_{ensure_default_profile().pk}": "root"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(program_role(self.user, "diary"), "reader")

    def test_admin_flag_is_independent_of_profile_role(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse("user_edit", args=[self.user.pk]),
            {"username": "alice", "is_active": "on", "is_admin": "on",
             f"profile_{ensure_default_profile().pk}": "reader"},
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_superuser)
        # The stored role stays as chosen (the Users screen shows it); the Admin flag does not rewrite it.
        stored = live_memberships(self.user, "diary", raw=True)
        self.assertEqual([m.role for m in stored], ["reader"])
        # Effective role: an Admin is an Editor in every program (the owner's rule).
        self.assertEqual(program_role(self.user, "diary"), "editor")

    def test_last_admin_cannot_become_editor_or_be_disabled(self):
        self.client.force_login(self.admin)
        url = reverse("user_edit", args=[self.admin.pk])
        self.assertContains(self.client.post(url, {"username": "boss", "is_active": "on"}), "last active Admin")
        self.assertContains(self.client.post(url, {"username": "boss", "is_admin": "on"}), "cannot disable your own")
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_superuser)


class ProfileModelTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user("alice", password=PASSWORD)
        self.main = ensure_default_profile()

    def test_main_profile_exists_from_migration(self):
        self.assertEqual(self.main.name, "Main")
        self.assertEqual(self.main.program, "diary")

    def test_name_unique_per_program_ignoring_case_among_live_profiles(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Profile.objects.create(program="diary", name="main")
        Profile.objects.create(program="other", name="Main")

    def test_deleted_profile_does_not_block_name(self):
        Profile.objects.filter(pk=self.main.pk).update(deleted_at=timezone.now())
        again = Profile.objects.create(program="diary", name="Main")
        self.assertIsNone(again.deleted_at)

    def test_blank_name_refused(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Profile.objects.create(program="diary", name="")

    def test_membership_program_follows_profile(self):
        membership = ProfileMembership.objects.create(user=self.alice, profile=self.main, program="wrong")
        self.assertEqual(membership.program, "diary")

    def test_several_profiles_per_user_but_one_membership_per_profile(self):
        # Round 18 (D95): the old "one profile per program" rule is gone.
        second = Profile.objects.create(program="diary", name="Junior")
        ProfileMembership.objects.create(user=self.alice, profile=self.main)
        ProfileMembership.objects.create(user=self.alice, profile=second, role="editor")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProfileMembership.objects.create(user=self.alice, profile=second)

    def test_the_profile_in_use_is_the_one_switched_to_last(self):
        from accounts.profiles import live_memberships, use_profile

        junior = Profile.objects.create(program="diary", name="Junior")
        ProfileMembership.objects.create(user=self.alice, profile=self.main)
        ProfileMembership.objects.create(user=self.alice, profile=junior, role="editor")
        self.assertEqual(get_profile_for(self.alice), junior)  # never switched: by name (Junior before Main)
        self.assertTrue(use_profile(self.alice, self.main))
        self.assertEqual(get_profile_for(self.alice), self.main)
        self.assertEqual([m.profile for m in live_memberships(self.alice)], [self.main, junior])
        self.assertTrue(use_profile(self.alice, junior))
        self.assertEqual(get_profile_for(self.alice), junior)
        self.assertEqual(program_role(self.alice, "diary"), "editor")
        Profile.objects.filter(pk=junior.pk).update(deleted_at=timezone.now())
        self.assertEqual(get_profile_for(self.alice), self.main)
        self.assertFalse(use_profile(self.alice, junior))
        stranger = Profile.objects.create(program="diary", name="Stranger")
        self.assertFalse(use_profile(self.alice, stranger))

    def test_several_users_may_share_a_profile(self):
        bob = User.objects.create_user("bob", password=PASSWORD)
        ProfileMembership.objects.create(user=self.alice, profile=self.main)
        ProfileMembership.objects.create(user=bob, profile=self.main)
        self.assertEqual(self.main.memberships.count(), 2)

    def test_get_profile_for(self):
        self.assertIsNone(get_profile_for(self.alice))
        self.assertIsNone(get_profile_for(AnonymousUser()))
        ProfileMembership.objects.create(user=self.alice, profile=self.main)
        self.assertEqual(get_profile_for(self.alice), self.main)
        self.assertIsNone(get_profile_for(self.alice, "other"))
        Profile.objects.filter(pk=self.main.pk).update(deleted_at=timezone.now())
        self.assertIsNone(get_profile_for(self.alice))


class DefaultProfileLogicTests(TestCase):
    """The logic the data migration uses (run here on the real models)."""

    def test_ensure_default_profile_reuses_existing_main(self):
        first = ensure_default_profile()
        self.assertEqual(ensure_default_profile(Profile, "diary", "MAIN"), first)
        self.assertEqual(Profile.objects.filter(program="diary", name__iexact="main").count(), 1)

    def test_ensure_default_profile_creates_when_missing(self):
        Profile.objects.all().delete()
        created = ensure_default_profile()
        self.assertEqual((created.program, created.name), ("diary", "Main"))

    def test_assign_unassigned_users_respects_one_per_program(self):
        main = ensure_default_profile()
        junior = Profile.objects.create(program="diary", name="Junior")
        alice = User.objects.create_user("alice", password=PASSWORD)
        bob = User.objects.create_user("bob", password=PASSWORD)
        ProfileMembership.objects.create(user=alice, profile=junior)
        assigned = assign_unassigned_users(User, ProfileMembership, main)
        self.assertEqual(assigned, User.objects.count() - 1)
        self.assertEqual(get_profile_for(alice), junior)
        self.assertEqual(get_profile_for(bob), main)
        self.assertEqual(assign_unassigned_users(User, ProfileMembership, main), 0)

    def test_create_first_admin_joins_main(self):
        User.objects.all().delete()
        with mock.patch.dict("os.environ", {"DJANGO_SUPERUSER_USERNAME": "boss", "DJANGO_SUPERUSER_PASSWORD": PASSWORD}):
            call_command("create_first_admin", stdout=StringIO())
        self.assertEqual(get_profile_for(User.objects.get(username="boss")).name, "Main")


@override_settings(SECURE_SSL_REDIRECT=False)
class ProfileScreenTests(BaseCase):
    def test_non_admins_cannot_reach_profile_screens(self):
        editor = self.make_user("ed", role="editor")
        main = ensure_default_profile()
        urls = [
            reverse("profile_list"),
            reverse("profile_create"),
            reverse("profile_edit", args=[main.pk]),
            reverse("profile_delete", args=[main.pk]),
        ]
        for who in (self.user, editor):
            self.client.force_login(who)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 403, url)
                self.assertEqual(self.client.post(url, {"name": "X", "confirm": "yes"}).status_code, 403, url)
        self.assertFalse(Profile.objects.filter(name="X").exists())
        self.client.logout()
        self.assertEqual(self.client.get(reverse("profile_list")).status_code, 302)

    def test_profiles_link_only_for_admin_on_home(self):
        # Profiles is a page of the Users & Profiles tab of Settings (Admin only).
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("my_settings")), 'href="%s"' % reverse("user_list"))
        self.assertContains(self.client.get(reverse("user_list")), 'href="%s"' % reverse("profile_list"))
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse("my_settings")), 'href="%s"' % reverse("user_list"))
        self.assertNotContains(self.client.get(reverse("home")), 'href="%s"' % reverse("profile_list"))
        self.assertNotContains(self.client.get(reverse("home")), 'href="%s"' % reverse("user_list"))

    def test_admin_creates_and_renames(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("profile_create"), {"name": "  Madon   Case Law "})
        self.assertRedirects(resp, reverse("profile_list"))
        profile = Profile.objects.get(name="Madon Case Law")
        self.assertEqual(profile.program, "diary")
        resp = self.client.post(reverse("profile_edit", args=[profile.pk]), {"name": "Madon"})
        self.assertRedirects(resp, reverse("profile_list"))
        profile.refresh_from_db()
        self.assertEqual(profile.name, "Madon")
        self.assertContains(self.client.get(reverse("profile_list")), "Madon")

    def test_duplicate_name_refused_ignoring_case(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("profile_create"), {"name": "main"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "already exists")
        self.assertEqual(Profile.objects.filter(name__iexact="main", deleted_at__isnull=True).count(), 1)

    def test_delete_unused_profile(self):
        junior = Profile.objects.create(program="diary", name="Junior")
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("profile_delete", args=[junior.pk]))
        self.assertRedirects(resp, reverse("profile_list"))
        junior.refresh_from_db()
        self.assertIsNotNone(junior.deleted_at)

    def test_delete_in_use_refused_without_confirm(self):
        main = ensure_default_profile()
        self.client.force_login(self.admin)
        page = self.client.get(reverse("profile_delete", args=[main.pk]))
        self.assertContains(page, "still in use")
        resp = self.client.post(reverse("profile_delete", args=[main.pk]))
        self.assertRedirects(resp, reverse("profile_delete", args=[main.pk]))
        main.refresh_from_db()
        self.assertIsNone(main.deleted_at)
        self.assertEqual(get_profile_for(self.user), main)

    def test_delete_in_use_with_confirm_removes_access(self):
        main = ensure_default_profile()
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("profile_delete", args=[main.pk]), {"confirm": "yes"})
        self.assertRedirects(resp, reverse("profile_list"))
        main.refresh_from_db()
        self.assertIsNotNone(main.deleted_at)
        self.assertIsNone(get_profile_for(self.user))
        # Memberships are kept (suspended) so the profile can be restored.
        self.assertEqual(ProfileMembership.objects.filter(profile=main, suspended=False).count(), 0)
        self.assertTrue(ProfileMembership.objects.filter(profile=main, suspended=True).exists())
        self.assertEqual(main.deleted_by, self.admin)

    def test_deleted_profile_name_can_be_reused(self):
        junior = Profile.objects.create(program="diary", name="Junior")
        self.client.force_login(self.admin)
        self.client.post(reverse("profile_delete", args=[junior.pk]))
        resp = self.client.post(reverse("profile_create"), {"name": "junior"})
        self.assertRedirects(resp, reverse("profile_list"))


@override_settings(SECURE_SSL_REDIRECT=False, PROFILE_RETENTION_DAYS=30)
class ProfileRecoveryTests(BaseCase):
    def delete_main(self):
        main = ensure_default_profile()
        self.client.force_login(self.admin)
        self.client.post(reverse("profile_delete", args=[main.pk]), {"confirm": "yes"})
        main.refresh_from_db()
        return main

    def test_list_shows_deleted_with_details(self):
        main = self.delete_main()
        page = self.client.get(reverse("profile_list"))
        self.assertContains(page, "Deleted profiles")
        self.assertContains(page, reverse("profile_restore", args=[main.pk]))
        self.assertContains(page, "<td>30</td>")
        self.assertContains(page, self.admin.username)

    def test_restore_brings_back_exact_state_and_members(self):
        main = self.delete_main()
        self.assertIsNone(get_profile_for(self.user))
        resp = self.client.post(reverse("profile_restore", args=[main.pk]))
        self.assertRedirects(resp, reverse("profile_list"))
        main.refresh_from_db()
        self.assertIsNone(main.deleted_at)
        self.assertIsNone(main.deleted_by)
        self.assertEqual(main.name, "Main")
        self.assertEqual(get_profile_for(self.user), main)
        self.assertFalse(ProfileMembership.objects.filter(suspended=True).exists())

    def test_restore_is_admin_only(self):
        main = self.delete_main()
        editor = self.make_user("ed2", role="editor")
        self.client.force_login(editor)
        self.assertEqual(self.client.post(reverse("profile_restore", args=[main.pk])).status_code, 403)
        main.refresh_from_db()
        self.assertIsNotNone(main.deleted_at)

    def test_member_given_another_profile_meanwhile_keeps_both_after_restore(self):
        # Round 18 (D95): a user may have several profiles, so another profile no longer blocks a restore.
        main = self.delete_main()
        junior = Profile.objects.create(program="diary", name="Junior")
        from accounts.profiles import set_user_profile

        set_user_profile(self.user, junior, "reader")
        resp = self.client.post(reverse("profile_restore", args=[main.pk]), follow=True)
        self.assertNotContains(resp, "cannot be restored")
        main.refresh_from_db()
        self.assertIsNone(main.deleted_at)
        names = sorted(ProfileMembership.objects.filter(user=self.user, suspended=False)
                       .values_list("profile__name", flat=True))
        self.assertEqual(names, ["Junior", "Main"])

    def test_same_name_asks_for_rename(self):
        main = self.delete_main()
        Profile.objects.create(program="diary", name="main")
        page = self.client.post(reverse("profile_restore", args=[main.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "already exists")
        main.refresh_from_db()
        self.assertIsNotNone(main.deleted_at)
        same = self.client.post(reverse("profile_restore", args=[main.pk]), {"name": "MAIN"})
        self.assertEqual(same.status_code, 200)
        resp = self.client.post(reverse("profile_restore", args=[main.pk]), {"name": "Main restored"})
        self.assertRedirects(resp, reverse("profile_list"))
        main.refresh_from_db()
        self.assertIsNone(main.deleted_at)
        self.assertEqual(main.name, "Main restored")

    def test_cannot_restore_live_profile(self):
        main = ensure_default_profile()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse("profile_restore", args=[main.pk])).status_code, 404)


@override_settings(SECURE_SSL_REDIRECT=False, PROFILE_RETENTION_DAYS=30)
class PurgeDeletedProfilesTests(BaseCase):
    def setUp(self):
        super().setUp()
        from diary.models import Subject

        self.Subject = Subject
        self.old = Profile.objects.create(program="diary", name="Old")
        self.recent = Profile.objects.create(program="diary", name="Recent")
        self.live = ensure_default_profile()
        now = timezone.now()
        Profile.objects.filter(pk=self.old.pk).update(deleted_at=now - timedelta(days=31))
        Profile.objects.filter(pk=self.recent.pk).update(deleted_at=now - timedelta(days=5))
        for profile in (self.old, self.recent, self.live):
            Subject.objects.create(profile=profile, name=f"S of {profile.name}")

    def good_backup(self):
        from backups import services

        return services.create_backup("daily")

    def run_purge(self):
        from io import StringIO

        call_command("purge_deleted_profiles", stdout=StringIO())

    def test_purges_only_expired_profiles_and_their_data(self):
        self.good_backup()
        self.run_purge()
        self.assertFalse(Profile.objects.filter(pk=self.old.pk).exists())
        self.assertFalse(self.Subject.objects.filter(profile_id=self.old.pk).exists())
        self.assertTrue(Profile.objects.filter(pk=self.recent.pk).exists())
        self.assertTrue(self.Subject.objects.filter(profile=self.recent).exists())
        self.assertTrue(self.Subject.objects.filter(profile=self.live).exists())

    def test_log_entry_has_counts_and_is_shown(self):
        from accounts.models import PurgeLog

        self.good_backup()
        self.run_purge()
        log = PurgeLog.objects.get()
        self.assertTrue(log.success)
        self.assertEqual(log.counts.get("diary.Subject"), 1)
        self.assertEqual(log.counts.get("accounts.Profile"), 1)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("profile_list")), "diary.Subject: 1")

    def test_refuses_without_todays_backup(self):
        from accounts.models import PurgeLog

        with self.assertRaises(CommandError):
            self.run_purge()
        self.assertTrue(Profile.objects.filter(pk=self.old.pk).exists())
        self.assertTrue(self.Subject.objects.filter(profile_id=self.old.pk).exists())
        log = PurgeLog.objects.get()
        self.assertFalse(log.success)
        self.assertIn("no successful backup", log.message)

    def test_refuses_when_todays_backup_failed(self):
        from backups.models import BackupLog

        self.good_backup()
        BackupLog.objects.create(kind="daily", success=False, message="boom")
        with self.assertRaises(CommandError):
            self.run_purge()
        self.assertTrue(Profile.objects.filter(pk=self.old.pk).exists())

    def test_nothing_to_purge_logs_nothing(self):
        from accounts.models import PurgeLog

        Profile.objects.filter(pk=self.old.pk).update(deleted_at=timezone.now())
        self.run_purge()
        self.assertEqual(PurgeLog.objects.count(), 0)
        self.assertTrue(Profile.objects.filter(pk=self.old.pk).exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class UserProfileAssignmentTests(BaseCase):
    def test_user_list_shows_profile(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("user_list")), "Main")

    def test_edit_form_preselects_current_profiles(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("user_edit", args=[self.user.pk]))
        self.assertEqual(resp.context["form"].fields[f"profile_{ensure_default_profile().pk}"].initial, "reader")

    def test_a_second_profile_is_added_and_the_first_kept(self):
        junior = Profile.objects.create(program="diary", name="Junior")
        main = ensure_default_profile()
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("user_edit", args=[self.user.pk]),
            {"username": "alice", "is_active": "on", f"profile_{main.pk}": "reader", f"profile_{junior.pk}": "editor"},
        )
        self.assertRedirects(resp, reverse("user_list"))
        self.assertEqual(ProfileMembership.objects.filter(user=self.user).count(), 2)
        listing = self.client.get(reverse("user_list")).content.decode()
        self.assertIn("Junior (Editor), Main (Reader)", listing)

    def test_no_access_removes_that_profile_only(self):
        junior = Profile.objects.create(program="diary", name="Junior")
        main = ensure_default_profile()
        ProfileMembership.objects.create(user=self.user, profile=junior)
        self.client.force_login(self.admin)
        self.client.post(
            reverse("user_edit", args=[self.user.pk]),
            {"username": "alice", "is_active": "on", f"profile_{main.pk}": "", f"profile_{junior.pk}": "reader"},
        )
        self.assertEqual(get_profile_for(self.user), junior)
        self.client.post(reverse("user_edit", args=[self.user.pk]), {"username": "alice", "is_active": "on"})
        self.assertIsNone(get_profile_for(self.user))

    def test_deleted_profile_not_offered_and_its_membership_kept(self):
        gone = Profile.objects.create(program="diary", name="Gone")
        ProfileMembership.objects.create(user=self.user, profile=gone, role="editor")
        delete_profile(gone)
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("user_edit", args=[self.user.pk]),
            {"username": "alice", "is_active": "on", f"profile_{gone.pk}": "reader",
             f"profile_{ensure_default_profile().pk}": "reader"},
        )
        self.assertRedirects(resp, reverse("user_list"))
        self.assertEqual(get_profile_for(self.user), ensure_default_profile())
        kept = ProfileMembership.objects.get(user=self.user, profile=gone)
        self.assertEqual((kept.suspended, kept.role), (True, "editor"))  # restorable as it was

    def test_create_user_with_profiles(self):
        junior = Profile.objects.create(program="diary", name="Junior")
        main = ensure_default_profile()
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("user_create"),
            {"username": "newbie", "password1": PASSWORD, "password2": PASSWORD,
             f"profile_{junior.pk}": "reader", f"profile_{main.pk}": "editor"},
        )
        self.assertRedirects(resp, reverse("user_list"))
        newbie = User.objects.get(username="newbie")
        self.assertEqual(ProfileMembership.objects.filter(user=newbie).count(), 2)
        self.assertEqual(program_role(newbie, "diary"), "reader")  # Junior comes first by name until they switch


class RoleMigrationTests(TransactionTestCase):
    """0006 copies User.role onto the profile membership; 0007 drops the column."""

    serialized_rollback = True  # keep the "Main" profile that the data migration created
    before = [("accounts", "0005_default_profile")]
    after = [("accounts", "0006_profilemembership_role")]

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_user_role_moves_to_membership_role(self):
        apps = self.migrate(self.before)
        OldUser = apps.get_model("accounts", "User")
        Profile_ = apps.get_model("accounts", "Profile")
        Membership = apps.get_model("accounts", "ProfileMembership")
        main, _ = Profile_.objects.get_or_create(program="diary", name="Main")
        for name, role, superuser in (
            ("adm", "admin", True),
            ("edi", "editor", False),
            ("rea", "reader", False),
            ("odd", "admin", False),
        ):
            user = OldUser.objects.create(username=name, role=role, is_superuser=superuser)
            Membership.objects.create(user=user, profile=main, program="diary")
        apps = self.migrate(self.after)
        Membership = apps.get_model("accounts", "ProfileMembership")
        roles = dict(Membership.objects.values_list("user__username", "role"))
        self.assertEqual(roles, {"adm": "editor", "edi": "editor", "rea": "reader", "odd": "editor"})
        apps = self.migrate([("accounts", "0007_remove_user_role")])
        self.assertNotIn("role", [f.name for f in apps.get_model("accounts", "User")._meta.get_fields()])
        self.assertTrue(apps.get_model("accounts", "User").objects.get(username="adm").is_superuser)


class ExportNameTests(BaseCase):
    def main(self):
        return ensure_default_profile()

    def test_default_name_uses_program_and_profile_name(self):
        from accounts.profiles import effective_export_name

        self.assertEqual(effective_export_name(self.main()), "Case Law Diary Main")

    def test_custom_name_trimmed_and_illegal_characters_replaced_with_a_hyphen(self):
        from accounts.profiles import effective_export_name, export_file_name, safe_file_name

        profile = self.main()
        profile.export_name = '  Madon:  Case/Law *"Diary"?  '
        self.assertEqual(effective_export_name(profile), 'Madon: Case/Law *"Diary"?')
        self.assertEqual(export_file_name(profile), "Madon- Case-Law --Diary--")
        self.assertEqual(safe_file_name('a\\b<c>d|e\x01f.'), "a-b-c-d-e-f")
        profile.export_name = '???'
        self.assertEqual(export_file_name(profile), "---")
        profile.export_name = "  . "  # nothing usable is left, so the profile's own name is used
        self.assertEqual(export_file_name(profile), "Main")

    # The export file name, the Display Name and the Contents settings are program settings: Case Law Diary settings
    # (Reading and Data sections). Editors change them; Readers see them read-only.
    def display(self, data=None):
        url = reverse("profile_settings") + "?tab=reading"
        if data is None:
            return self.client.get(url)
        # Round 19: the Display tab's only reading control is the required Yes/No "open the whole Subject" toggle.
        # reading_all_mode and reading_all_default are no longer form fields, so posting them is harmless extra data
        # that Django ignores; the toggle alone decides the stored reading_all_mode. When a test posts the old
        # reading_all_mode key without a toggle, default the toggle to match it (always_on -> Yes, else No).
        payload = {"tab": "reading", **data}
        if "diary-reading_all_mode" in payload and "diary-view_whole_subject" not in payload:
            payload["diary-view_whole_subject"] = "yes" if payload["diary-reading_all_mode"] == "always_on" else "no"
        return self.client.post(reverse("profile_settings"), payload)

    def test_editor_can_change_name(self):
        self.client.force_login(self.admin)  # Editor of Main through the membership
        resp = self.client.post(reverse("export_settings"), {"export_name": "  My: Diary "})
        self.assertRedirects(resp, reverse("profile_settings") + "?tab=data")
        self.assertEqual(Profile.objects.get(pk=self.main().pk).export_name, "My: Diary")
        self.assertContains(self.client.get(reverse("profile_settings") + "?tab=data"), "My- Diary")  # the preview shows the hyphen

    def test_reader_cannot_change_the_export_name(self):
        self.client.force_login(self.user)
        resp = self.client.post(reverse("export_settings"), {"export_name": "Shared"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self.main().export_name, "")

    def test_the_diary_settings_tab_has_reading_and_data_sections(self):
        self.client.force_login(self.user)  # a Reader sees the values but no Save button
        resp = self.client.get(reverse("profile_settings"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        for key in ("reading", "numbers", "data"):
            self.assertIn('data-section="%s"' % key, html)
        self.assertIn("Only you", html)  # My number formats
        self.assertEqual(html.count(">Save</button>"), 1)  # only the personal number formats can be saved
        self.assertIn("Everyone in this profile", html)

    def test_display_form_no_longer_offers_remember_or_all_default(self):
        # Round 19 (user item 4): the Yes/No toggle is the only reading control. The advanced "remember" select and
        # the reading_all_default checkbox are gone from the form and the page, and saving never changes the stored
        # reading_all_default. The Profile model keeps both fields (no migration); only the UI is simplified.
        from diary.forms import ProfileSettingsForm

        fields = ProfileSettingsForm().fields
        self.assertIn("view_whole_subject", fields)
        self.assertNotIn("reading_all_mode", fields)
        self.assertNotIn("reading_all_default", fields)
        self.assertTrue(self.main().reading_all_default)
        self.client.force_login(self.admin)
        resp = self.display()
        self.assertNotContains(resp, 'name="diary-reading_all_default"')
        self.assertNotContains(resp, 'name="diary-reading_all_mode"')
        self.assertNotContains(resp, "The View I Used Last")
        self.assertNotContains(resp, "Advanced reading options")
        # Posting the toggle (even alongside the now-ignored old keys) leaves reading_all_default untouched.
        self.display({"diary-view_whole_subject": "no", "diary-reading_all_default": "on"})
        self.assertTrue(Profile.objects.get(pk=self.main().pk).reading_all_default)

    def test_saving_another_tab_leaves_the_diary_settings_alone(self):
        Profile.objects.filter(pk=self.main().pk).update(display_name="Kept", reading_all_mode="always_on")
        self.client.force_login(self.admin)
        self.client.post(reverse("my_settings"), {"tab": "account", "email": ""})
        main = self.main()
        self.assertEqual((main.display_name, main.reading_all_mode, main.reading_all_default),
                         ("Kept", "always_on", True))

    def test_yes_no_toggle_sets_always_on_or_always_off(self):
        # Round 19 (user item 4): the plain Display toggle is the only reading control and always sets
        # reading_all_mode. Yes -> always_on (clicking a Subject opens the whole Subject); No -> always_off (the
        # scoped Contents page with a "Read Whole Subject" button). There is no longer a way to choose remember.
        self.client.force_login(self.admin)  # Editor of Main
        resp = self.client.post(reverse("profile_settings"), {
            "tab": "reading", "diary-view_whole_subject": "yes"})
        self.assertRedirects(resp, reverse("profile_settings") + "?tab=reading")
        self.assertEqual(Profile.objects.get(pk=self.main().pk).reading_all_mode, "always_on")
        self.client.post(reverse("profile_settings"), {
            "tab": "reading", "diary-view_whole_subject": "no"})
        self.assertEqual(Profile.objects.get(pk=self.main().pk).reading_all_mode, "always_off")

    def test_toggle_maps_a_pre_existing_remember_profile_on_save(self):
        # A row still on the old "remember" mode (no longer offered) is shown as Yes/No and mapped to
        # always_on/always_off on its next save: the toggle wins, remember can never be kept through the form.
        Profile.objects.filter(pk=self.main().pk).update(reading_all_mode="remember")
        self.client.force_login(self.admin)
        self.client.post(reverse("profile_settings"), {"tab": "reading", "diary-view_whole_subject": "yes"})
        self.assertEqual(Profile.objects.get(pk=self.main().pk).reading_all_mode, "always_on")

    def test_reader_cannot_change_the_diary_settings(self):
        self.client.force_login(self.user)
        self.display({"diary-view_whole_subject": "yes"})
        resp = self.display()
        self.assertNotContains(resp, 'name="diary-reading_all_default"')
        self.assertNotContains(resp, 'name="diary-reading_all_mode"')
        self.assertNotContains(resp, 'name="diary-view_whole_subject"')
        self.assertContains(resp, "Only its Editors can change them.")
        # A Reader cannot post the Display form, so the profile's reading_all_mode is unchanged (still the default).
        self.assertEqual(Profile.objects.get(pk=self.main().pk).reading_all_mode, "remember")

    def test_user_without_profile_has_no_diary_settings(self):
        other = self.make_user("nobody")
        self.client.force_login(other)
        # My settings opens for everyone signed in, just without the Case Law Diary section.
        response = self.client.get(reverse("my_settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-section="account"')
        self.assertNotContains(response, 'data-section="diary"')
        # The diary's own Settings tab is closed to a user with no diary profile.
        self.assertEqual(self.display().status_code, 403)
        self.assertEqual(self.client.get(reverse("export")).status_code, 403)

    def test_only_own_profile_changes(self):
        junior = Profile.objects.create(program="diary", name="Junior")
        self.client.force_login(self.admin)
        self.client.post(reverse("export_settings"), {"export_name": "Mine", "export_date_format": "YYYY-MM-DD"})
        self.display({"diary-display_name": "Mine too", "diary-reading_all_mode": "remember"})
        junior.refresh_from_db()
        self.assertEqual((junior.export_name, junior.display_name), ("", ""))


class UserEditFormImportTests(SimpleTestCase):
    def test_landing_choices_are_not_computed_when_the_module_loads(self):
        from accounts.forms import UserEditForm

        self.assertEqual(list(UserEditForm.base_fields["landing_program"].choices), [])
