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
from accounts.profiles import assign_unassigned_users, ensure_default_profile, get_profile_for
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
        resp = self.client.get(reverse("my_settings"))
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
        self.assertNotContains(self.client.get(reverse("my_settings")), 'value="diary"')
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
                "profile": ensure_default_profile().pk,
                "profile_role": "reader",
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
            {"username": "alice", "is_active": "on", "profile_role": "reader", "landing_program": "nonsense"},
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
    def post(self, home="Home", diary="Case Law Diary"):
        return self.client.post(reverse("settings"), {"home_name": home, "diary_name": diary})

    def test_defaults_without_rows(self):
        self.assertEqual(SuiteName.objects.count(), 0)
        self.assertEqual(suite.get_names(), {"home": "Home", "diary": "Case Law Diary"})
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
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("home")), 'href="%s"' % reverse("settings"))
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse("home")), 'href="%s"' % reverse("settings"))

    def test_rename_shows_everywhere(self):
        self.client.force_login(self.admin)
        resp = self.post(home="  Start   Page ", diary="Judgments")
        self.assertRedirects(resp, reverse("settings"))
        self.assertEqual(suite.get_names(), {"home": "Start Page", "diary": "Judgments"})
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

    def test_delete(self):
        url = reverse("user_delete", args=[self.user.pk])
        self.assertContains(self.client.get(url), "alice")
        self.assertRedirects(self.client.post(url), reverse("user_list"))
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())

    def test_cannot_delete_self(self):
        other = self.make_user("second", admin=True)
        url = reverse("user_delete", args=[self.admin.pk])
        self.client.post(url)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())
        self.assertTrue(User.objects.filter(pk=other.pk).exists())

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
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())
        self.assertTrue(User.objects.filter(pk=inactive.pk).exists())

    def test_admin_can_delete_a_disabled_admin(self):
        inactive = self.make_user("old", admin=True, active=False)
        self.client.post(reverse("user_delete", args=[inactive.pk]))
        self.assertFalse(User.objects.filter(pk=inactive.pk).exists())

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

    def test_create_form_defaults_to_reader_and_not_admin(self):
        self.client.force_login(self.admin)
        form = self.client.get(reverse("user_create")).context["form"]
        self.assertEqual(form.fields["profile_role"].initial, "reader")
        self.assertFalse(form.fields["is_admin"].initial)

    def test_user_form_has_profile_and_role_on_one_line_without_help_text(self):
        self.client.force_login(self.admin)
        for url in (reverse("user_create"), reverse("user_edit", args=[self.user.pk])):
            resp = self.client.get(url)
            html = resp.content.decode()
            row = html.split('class="profile-row"')[1].split("</div>")[0]
            self.assertIn('name="profile"', row, url)
            self.assertIn('name="profile_role"', row, url)
            self.assertIn("Case law diary profile", row, url)
            self.assertIn("Role in that profile", row, url)
            self.assertNotContains(resp, "at most one profile per program")
            self.assertNotContains(resp, "Reader: view only. Editor: view and edit.")

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
        # An Admin whose own membership is Reader may not use editor-only views.
        ProfileMembership.objects.filter(user=self.admin).update(role="reader")
        with self.assertRaises(PermissionDenied):
            call(editor_view, self.admin)

    def test_header_shows_username_only_and_user_list_shows_role(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, '<span class="who">alice</span>', html=True)
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
            {"username": "alice", "is_active": "on", "profile": main.pk, "profile_role": "editor"},
        )
        self.user.refresh_from_db()
        self.assertEqual(program_role(self.user, "diary"), "editor")
        self.assertFalse(self.user.is_superuser)
        self.assertEqual(ProfileMembership.objects.filter(user=self.user).count(), 1)

    def test_role_follows_the_profile_chosen(self):
        self.client.force_login(self.admin)
        junior = Profile.objects.create(program="diary", name="Junior")
        self.client.post(
            reverse("user_edit", args=[self.user.pk]),
            {"username": "alice", "is_active": "on", "profile": junior.pk, "profile_role": "editor"},
        )
        membership = ProfileMembership.objects.get(user=self.user)
        self.assertEqual((membership.profile, membership.role), (junior, "editor"))

    def test_invalid_role_rejected(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("user_edit", args=[self.user.pk]),
            {"username": "alice", "is_active": "on", "profile": ensure_default_profile().pk, "profile_role": "root"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(program_role(self.user, "diary"), "reader")

    def test_blank_role_defaults_to_reader(self):
        self.client.force_login(self.admin)
        ProfileMembership.objects.filter(user=self.user).update(role="editor")
        self.client.post(
            reverse("user_edit", args=[self.user.pk]),
            {"username": "alice", "is_active": "on", "profile": ensure_default_profile().pk},
        )
        self.assertEqual(program_role(self.user, "diary"), "reader")

    def test_admin_flag_is_independent_of_profile_role(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse("user_edit", args=[self.user.pk]),
            {"username": "alice", "is_active": "on", "is_admin": "on",
             "profile": ensure_default_profile().pk, "profile_role": "reader"},
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_superuser)
        self.assertEqual(program_role(self.user, "diary"), "reader")

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

    def test_one_profile_per_user_per_program(self):
        second = Profile.objects.create(program="diary", name="Junior")
        ProfileMembership.objects.create(user=self.alice, profile=self.main)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProfileMembership.objects.create(user=self.alice, profile=second)
        other_program = Profile.objects.create(program="other", name="Anything")
        ProfileMembership.objects.create(user=self.alice, profile=other_program)

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
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("home")), 'href="%s"' % reverse("profile_list"))
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse("home")), 'href="%s"' % reverse("profile_list"))

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

    def test_member_given_another_profile_can_be_assigned_and_blocks_restore(self):
        main = self.delete_main()
        junior = Profile.objects.create(program="diary", name="Junior")
        from accounts.profiles import set_user_profile

        set_user_profile(self.user, junior, "reader")
        resp = self.client.post(reverse("profile_restore", args=[main.pk]), follow=True)
        self.assertContains(resp, self.user.username)
        self.assertContains(resp, "cannot be restored")
        main.refresh_from_db()
        self.assertIsNotNone(main.deleted_at)
        self.assertEqual(get_profile_for(self.user), junior)

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

    def test_edit_form_preselects_current_profile(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("user_edit", args=[self.user.pk]))
        self.assertEqual(resp.context["form"].fields["profile"].initial, ensure_default_profile())

    def test_assignment_is_replaced_not_duplicated(self):
        junior = Profile.objects.create(program="diary", name="Junior")
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("user_edit", args=[self.user.pk]),
            {"username": "alice", "is_active": "on", "profile_role": "reader", "profile": junior.pk},
        )
        self.assertRedirects(resp, reverse("user_list"))
        self.assertEqual(ProfileMembership.objects.filter(user=self.user).count(), 1)
        self.assertEqual(get_profile_for(self.user), junior)

    def test_blank_profile_removes_access(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse("user_edit", args=[self.user.pk]),
            {"username": "alice", "is_active": "on", "profile_role": "reader", "profile": ""},
        )
        self.assertIsNone(get_profile_for(self.user))

    def test_deleted_profile_not_offered_or_accepted(self):
        gone = Profile.objects.create(program="diary", name="Gone", deleted_at=timezone.now())
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("user_edit", args=[self.user.pk]),
            {"username": "alice", "is_active": "on", "profile_role": "reader", "profile": gone.pk},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(get_profile_for(self.user), ensure_default_profile())

    def test_create_user_with_profile(self):
        junior = Profile.objects.create(program="diary", name="Junior")
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("user_create"),
            {"username": "newbie", "password1": PASSWORD, "password2": PASSWORD, "profile_role": "reader",
             "profile": junior.pk},
        )
        self.assertRedirects(resp, reverse("user_list"))
        self.assertEqual(get_profile_for(User.objects.get(username="newbie")), junior)


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

    def test_custom_name_trimmed_and_illegal_characters_removed(self):
        from accounts.profiles import effective_export_name, export_file_name, safe_file_name

        profile = self.main()
        profile.export_name = '  Madon:  Case/Law *"Diary"?  '
        self.assertEqual(effective_export_name(profile), 'Madon: Case/Law *"Diary"?')
        self.assertEqual(export_file_name(profile), "Madon CaseLaw Diary")
        self.assertEqual(safe_file_name('a\\b<c>d|e\x01f.'), "abcdef")
        profile.export_name = '???'
        self.assertEqual(export_file_name(profile), "Main")

    def test_editor_can_change_name(self):
        self.client.force_login(self.admin)  # Editor of Main through the membership
        resp = self.client.post(reverse("profile_settings"), {"export_name": "  My: Diary ", "reading_all_mode": "remember"})
        self.assertRedirects(resp, reverse("profile_settings"))
        self.assertEqual(Profile.objects.get(pk=self.main().pk).export_name, "My: Diary")
        self.assertContains(self.client.get(reverse("profile_settings")), "My Diary")

    def test_all_default_is_on_and_editor_can_switch_it_off_and_on(self):
        self.assertTrue(self.main().reading_all_default)
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("profile_settings"))
        self.assertContains(resp, 'name="reading_all_default"')
        self.assertContains(resp, "If there is no last view yet, Contents links open the whole Subject")
        self.client.post(reverse("profile_settings"), {"export_name": "", "reading_all_mode": "remember"})
        self.assertFalse(Profile.objects.get(pk=self.main().pk).reading_all_default)
        self.client.post(
            reverse("profile_settings"),
            {"export_name": "", "reading_all_mode": "remember", "reading_all_default": "on"},
        )
        self.assertTrue(Profile.objects.get(pk=self.main().pk).reading_all_default)

    def test_mode_defaults_to_remember_and_editor_can_change_it(self):
        self.assertEqual(self.main().reading_all_mode, "remember")
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("profile_settings"))
        self.assertContains(resp, 'name="reading_all_mode"')
        for label in ("The whole Subject", "Only that Topic or Sub-topic", "The view I used last"):
            self.assertContains(resp, label)
        for mode in ("always_on", "always_off", "remember"):
            self.client.post(reverse("profile_settings"), {"export_name": "", "reading_all_mode": mode})
            self.assertEqual(Profile.objects.get(pk=self.main().pk).reading_all_mode, mode)
        resp = self.client.post(reverse("profile_settings"), {"export_name": "", "reading_all_mode": "bogus"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Profile.objects.get(pk=self.main().pk).reading_all_mode, "remember")

    def test_reader_cannot_change_all_default(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse("profile_settings"),
            {"export_name": "", "reading_all_default": "on", "reading_all_mode": "always_on"},
        )
        self.assertEqual(resp.status_code, 403)
        Profile.objects.filter(pk=self.main().pk).update(reading_all_default=False)
        resp = self.client.get(reverse("profile_settings"))
        self.assertNotContains(resp, 'name="reading_all_default"')
        self.assertNotContains(resp, 'name="reading_all_mode"')
        self.assertContains(resp, "With no last view yet, Contents links open the whole Subject")
        self.assertEqual(Profile.objects.get(pk=self.main().pk).reading_all_mode, "remember")
        self.assertFalse(Profile.objects.get(pk=self.main().pk).reading_all_default)

    def test_reader_can_view_but_not_change(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("profile_settings"))
        self.assertContains(resp, "Case Law Diary Main")
        self.assertNotContains(resp, 'name="export_name"')
        self.assertNotContains(resp, "Save")
        self.assertContains(resp, "Only Editors of this profile can change it.")
        self.assertEqual(self.client.post(reverse("profile_settings"), {"export_name": "X"}).status_code, 403)
        self.assertEqual(self.main().export_name, "")

    def test_user_without_profile_refused(self):
        other = self.make_user("nobody")
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("profile_settings")).status_code, 403)

    def test_only_own_profile_changes(self):
        junior = Profile.objects.create(program="diary", name="Junior")
        self.client.force_login(self.admin)
        self.client.post(reverse("profile_settings"), {"export_name": "Mine", "reading_all_mode": "remember"})
        junior.refresh_from_db()
        self.assertEqual(junior.export_name, "")


class UserEditFormImportTests(SimpleTestCase):
    def test_landing_choices_are_not_computed_when_the_module_loads(self):
        from accounts.forms import UserEditForm

        self.assertEqual(list(UserEditForm.base_fields["landing_program"].choices), [])
