from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.forms import THROTTLE_MESSAGE
from accounts import suite
from accounts.models import FailedLogin, Profile, ProfileMembership, SuiteName
from accounts.profiles import assign_unassigned_users, ensure_default_profile, get_profile_for
from accounts.permissions import admin_required, editor_required, reader_required

User = get_user_model()
PASSWORD = "correct-horse-battery-9"


@override_settings(SECURE_SSL_REDIRECT=False)
class BaseCase(TestCase):
    def make_user(self, username, admin=False, active=True, role=None):
        if role is None:
            role = "admin" if admin else "reader"
        return User.objects.create_user(
            username=username,
            password=PASSWORD,
            role=role,
            is_active=active,
        )

    def setUp(self):
        self.admin = self.make_user("boss", admin=True)
        self.user = self.make_user("alice")
        for member in (self.admin, self.user):
            ProfileMembership.objects.create(user=member, profile=ensure_default_profile())


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
        resp = self.client.get(reverse("subjects"))
        self.assertContains(resp, 'aria-label="Go to Home">Case Law Diary</a>')

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
        self.assertContains(home, "<h2>Judgments</h2>", html=True)
        self.assertContains(self.client.get(reverse("subjects")), 'aria-label="Go to Home">Judgments</a>')
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
            {"username": "bob", "password1": PASSWORD, "password2": PASSWORD, "role": "admin"},
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
            {"username": "alice2", "role": "reader", "new_password": "another-good-pass-77"},
        )
        self.assertRedirects(resp, reverse("user_list"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "alice2")
        self.assertFalse(self.user.is_active)
        self.assertTrue(self.user.check_password("another-good-pass-77"))

    def test_edit_promote_to_admin(self):
        self.client.post(
            reverse("user_edit", args=[self.user.pk]),
            {"username": "alice", "is_active": "on", "role": "admin"},
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
            {"username": "boss", "role": "admin"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "cannot disable your own account")
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_cannot_remove_last_admin_rights(self):
        resp = self.client.post(
            reverse("user_edit", args=[self.admin.pk]),
            {"username": "boss", "is_active": "on", "role": "editor"},
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
            {"username": "second", "is_active": "on", "role": "reader"},
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
    def test_new_user_defaults_to_reader(self):
        user = User.objects.create_user("plain", password=PASSWORD)
        self.assertEqual(user.role, "reader")
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_editor)

    def test_create_form_defaults_to_reader(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("user_create"))
        self.assertEqual(resp.context["form"].fields["role"].initial, "reader")

    def test_superuser_flag_and_admin_role_stay_in_step(self):
        a = User.objects.create_user("a", password=PASSWORD, is_superuser=True)
        self.assertEqual(a.role, "admin")
        self.assertTrue(a.is_staff)
        b = User.objects.create_user("b", password=PASSWORD, role="admin")
        self.assertTrue(b.is_superuser)
        b.set_role("editor")
        b.save()
        b.refresh_from_db()
        self.assertEqual((b.role, b.is_superuser, b.is_staff), ("editor", False, False))

    def test_role_helpers(self):
        ed = self.make_user("ed", role="editor")
        self.assertTrue(ed.is_editor)
        self.assertFalse(ed.is_admin)
        self.assertTrue(self.admin.is_editor)
        self.assertTrue(self.admin.is_admin)
        self.assertFalse(self.user.is_editor)

    def test_create_first_admin_makes_admin_role(self):
        env = {"DJANGO_SUPERUSER_USERNAME": "root2", "DJANGO_SUPERUSER_PASSWORD": PASSWORD}
        with mock.patch.dict("os.environ", env):
            User.objects.all().delete()
            call_command("create_first_admin", stdout=StringIO())
        self.assertEqual(User.objects.get(username="root2").role, "admin")

    def test_decorators(self):
        def view(request):
            return HttpResponse("ok")

        rf = RequestFactory()

        def call(decorator, user):
            request = rf.get("/x/")
            request.user = user
            return decorator(view)(request)

        editor = self.make_user("ed", role="editor")
        for decorator in (admin_required, editor_required, reader_required):
            self.assertEqual(call(decorator, AnonymousUser()).status_code, 302)
        self.assertEqual(call(admin_required, self.admin).status_code, 200)
        self.assertEqual(call(editor_required, self.admin).status_code, 200)
        self.assertEqual(call(editor_required, editor).status_code, 200)
        self.assertEqual(call(reader_required, self.user).status_code, 200)
        with self.assertRaises(PermissionDenied):
            call(admin_required, editor)
        with self.assertRaises(PermissionDenied):
            call(editor_required, self.user)

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
            resp = self.client.post(target, {"username": "alice", "is_active": "on", "role": "admin"})
            self.assertEqual(resp.status_code, 403)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, "reader")

    def test_admin_changes_role(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse("user_edit", args=[self.user.pk]),
            {"username": "alice", "is_active": "on", "role": "editor"},
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, "editor")
        self.assertFalse(self.user.is_superuser)

    def test_invalid_role_rejected(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("user_edit", args=[self.user.pk]),
            {"username": "alice", "is_active": "on", "role": "root"},
        )
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, "reader")

    def test_last_admin_cannot_become_editor_or_be_disabled(self):
        self.client.force_login(self.admin)
        url = reverse("user_edit", args=[self.admin.pk])
        self.assertContains(self.client.post(url, {"username": "boss", "is_active": "on", "role": "editor"}), "last active Admin")
        self.assertContains(self.client.post(url, {"username": "boss", "role": "admin"}), "cannot disable your own")
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, "admin")


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
        self.assertEqual(ProfileMembership.objects.filter(profile=main).count(), 0)

    def test_deleted_profile_name_can_be_reused(self):
        junior = Profile.objects.create(program="diary", name="Junior")
        self.client.force_login(self.admin)
        self.client.post(reverse("profile_delete", args=[junior.pk]))
        resp = self.client.post(reverse("profile_create"), {"name": "junior"})
        self.assertRedirects(resp, reverse("profile_list"))


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
            {"username": "alice", "is_active": "on", "role": "reader", "profile": junior.pk},
        )
        self.assertRedirects(resp, reverse("user_list"))
        self.assertEqual(ProfileMembership.objects.filter(user=self.user).count(), 1)
        self.assertEqual(get_profile_for(self.user), junior)

    def test_blank_profile_removes_access(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse("user_edit", args=[self.user.pk]),
            {"username": "alice", "is_active": "on", "role": "reader", "profile": ""},
        )
        self.assertIsNone(get_profile_for(self.user))

    def test_deleted_profile_not_offered_or_accepted(self):
        gone = Profile.objects.create(program="diary", name="Gone", deleted_at=timezone.now())
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("user_edit", args=[self.user.pk]),
            {"username": "alice", "is_active": "on", "role": "reader", "profile": gone.pk},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(get_profile_for(self.user), ensure_default_profile())

    def test_create_user_with_profile(self):
        junior = Profile.objects.create(program="diary", name="Junior")
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("user_create"),
            {"username": "newbie", "password1": PASSWORD, "password2": PASSWORD, "role": "reader",
             "profile": junior.pk},
        )
        self.assertRedirects(resp, reverse("user_list"))
        self.assertEqual(get_profile_for(User.objects.get(username="newbie")), junior)
