"""T1.1: characterisation (golden-master) tests for the shared suite core.

These pin TODAY'S observable behaviour of the parts that the upcoming KEY_DIARY
generalisation (design section 10) will touch, so that after the refactor these
exact tests still pass unchanged. They assert what the code does now (status codes,
redirects, rows created or removed, context variables, rendered structure, backup
round trips), not idealised behaviour. Where the current behaviour is surprising it
is encoded as-is with a short note rather than "fixed".

The areas covered map to the T1.1 list in docs/fees-spec/tasks.md:
  * Profiles screen: list, create, rename, delete, restore, purge.
  * Users screen and form: save with a profile and a role.
  * Profile switch.
  * Home page program buttons.
  * Landing redirect for a user with and without a diary profile.
  * accounts/clear.py behaviour.
  * Suite backup then restore of a diary fixture.
  * Header switcher context (context processors and profiles helpers).

They use the established app conventions: the custom accounts.User model, the
accounts.profiles helpers (ensure_default_profile / set_user_profile /
set_user_profiles / request_memberships / request_role), the diary test helpers
(main_profile / join_main), Django test clients and the backups services.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts import clear, suite
from accounts.context_processors import current_profile, program_label
from accounts.models import (
    ROLE_EDITOR,
    ROLE_READER,
    Profile,
    ProfileMembership,
    PurgeLog,
)
from accounts.profiles import (
    DEFAULT_PROFILE_NAME,
    ensure_default_profile,
    get_profile_for,
    request_memberships,
    request_role,
    set_user_profile,
)
from accounts.purge import purge_expired_profiles
from backups import services
from diary.models import Subject
from diary.tests.helpers import join_main, main_profile

User = get_user_model()
PASSWORD = "correct-horse-battery-9"


def make_user(username, admin=False, active=True):
    return User.objects.create_user(
        username=username, password=PASSWORD, is_superuser=admin, is_active=active
    )


@override_settings(SECURE_SSL_REDIRECT=False)
class ProfilesScreenTests(TestCase):
    """The Admin Profiles screen: list, create, rename, delete, restore (accounts/views.py)."""

    def setUp(self):
        self.main = main_profile()
        self.admin = join_main(make_user("boss", admin=True), ROLE_EDITOR)
        self.client.force_login(self.admin)

    def test_list_shows_live_profiles_with_counts(self):
        other = Profile.objects.create(program=suite.KEY_DIARY, name="Smith")
        Subject.objects.create(profile=self.main, name="A subject")
        resp = self.client.get(reverse("profile_list"))
        self.assertEqual(resp.status_code, 200)
        names = [p.name for p in resp.context["profiles"]]
        # Live diary profiles are listed in name order.
        self.assertEqual(names, ["Main", "Smith"])
        self.assertEqual(resp.context["deleted_profiles"], [])
        main_row = next(p for p in resp.context["profiles"] if p.pk == self.main.pk)
        # profile_usage annotates members and subjects on each row.
        self.assertEqual(main_row.member_count, 1)
        self.assertEqual(main_row.subject_count, 1)
        self.assertEqual(other.name, "Smith")

    def test_create_adds_a_live_diary_profile(self):
        resp = self.client.post(reverse("profile_create"), {"name": "Jones"})
        self.assertRedirects(resp, reverse("profile_list"))
        created = Profile.objects.get(name="Jones")
        # ProfileForm forces the program to the diary.
        self.assertEqual(created.program, suite.KEY_DIARY)
        self.assertIsNone(created.deleted_at)

    def test_create_rejects_a_duplicate_name_ignoring_case(self):
        resp = self.client.post(reverse("profile_create"), {"name": "main"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "A profile with this name already exists.")
        self.assertEqual(Profile.objects.filter(program=suite.KEY_DIARY).count(), 1)

    def test_rename_changes_the_name(self):
        target = Profile.objects.create(program=suite.KEY_DIARY, name="Old")
        resp = self.client.post(reverse("profile_edit", args=[target.pk]), {"name": "New"})
        self.assertRedirects(resp, reverse("profile_list"))
        target.refresh_from_db()
        self.assertEqual(target.name, "New")

    def test_delete_is_a_soft_delete_that_suspends_memberships(self):
        target = Profile.objects.create(program=suite.KEY_DIARY, name="Temp")
        member = join_main(make_user("mia"), ROLE_READER)
        ProfileMembership.objects.create(user=member, profile=target, role=ROLE_READER)
        # An empty profile with a member is "in use", so the box must be ticked to confirm.
        resp = self.client.post(reverse("profile_delete", args=[target.pk]), {"confirm": "yes"})
        self.assertRedirects(resp, reverse("profile_list"))
        target.refresh_from_db()
        self.assertIsNotNone(target.deleted_at)
        self.assertEqual(target.deleted_by, self.admin)
        self.assertTrue(
            ProfileMembership.objects.get(user=member, profile=target).suspended
        )

    def test_delete_in_use_without_confirm_is_refused(self):
        target = Profile.objects.create(program=suite.KEY_DIARY, name="Busy")
        Subject.objects.create(profile=target, name="Live data")
        resp = self.client.post(reverse("profile_delete", args=[target.pk]))
        self.assertRedirects(resp, reverse("profile_delete", args=[target.pk]))
        target.refresh_from_db()
        self.assertIsNone(target.deleted_at)

    def test_restore_brings_a_deleted_profile_back_with_its_members(self):
        target = Profile.objects.create(program=suite.KEY_DIARY, name="Gone")
        member = join_main(make_user("ravi"), ROLE_READER)
        ProfileMembership.objects.create(user=member, profile=target, role=ROLE_EDITOR)
        self.client.post(reverse("profile_delete", args=[target.pk]), {"confirm": "yes"})
        resp = self.client.post(reverse("profile_restore", args=[target.pk]))
        self.assertRedirects(resp, reverse("profile_list"))
        target.refresh_from_db()
        self.assertIsNone(target.deleted_at)
        membership = ProfileMembership.objects.get(user=member, profile=target)
        self.assertFalse(membership.suspended)
        self.assertEqual(membership.role, ROLE_EDITOR)

    def test_restore_asks_for_a_new_name_when_a_live_profile_clashes(self):
        target = Profile.objects.create(
            program=suite.KEY_DIARY, name="Clash", deleted_at=timezone.now()
        )
        Profile.objects.create(program=suite.KEY_DIARY, name="Clash")
        # A GET lands on the rename form because a live profile already has the name.
        resp = self.client.get(reverse("profile_restore", args=[target.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "A profile with this name already exists.")
        target.refresh_from_db()
        self.assertIsNotNone(target.deleted_at)
        # Supplying a fresh name both renames and restores.
        resp = self.client.post(
            reverse("profile_restore", args=[target.pk]), {"name": "Clash Two"}
        )
        self.assertRedirects(resp, reverse("profile_list"))
        target.refresh_from_db()
        self.assertEqual(target.name, "Clash Two")
        self.assertIsNone(target.deleted_at)


@override_settings(SECURE_SSL_REDIRECT=False, PROFILE_RETENTION_DAYS=30)
class PurgeTests(TestCase):
    """accounts/purge.py::purge_expired_profiles deletes past-window profiles after a good backup."""

    def setUp(self):
        self.main = main_profile()
        self.admin = join_main(make_user("boss", admin=True), ROLE_EDITOR)
        self.old = Profile.objects.create(program=suite.KEY_DIARY, name="Old")
        Subject.objects.create(profile=self.old, name="Old subject")
        # Deleted long enough ago to be past the retention window.
        Profile.objects.filter(pk=self.old.pk).update(
            deleted_at=timezone.now() - timedelta(days=31)
        )

    def test_purge_refuses_without_todays_backup(self):
        log = purge_expired_profiles()
        self.assertIsNotNone(log)
        self.assertFalse(log.success)
        self.assertTrue(Profile.objects.filter(pk=self.old.pk).exists())

    def test_purge_removes_the_profile_and_its_data_after_a_good_backup(self):
        services.create_backup("daily")
        log = purge_expired_profiles()
        self.assertTrue(log.success)
        self.assertFalse(Profile.objects.filter(pk=self.old.pk).exists())
        self.assertFalse(Subject.objects.filter(name="Old subject").exists())
        # The purge counted the removed diary rows and the profile row.
        self.assertIn("diary.Subject", log.counts)

    def test_nothing_due_returns_none_and_writes_no_log(self):
        Profile.objects.filter(pk=self.old.pk).update(deleted_at=timezone.now())
        self.assertIsNone(purge_expired_profiles())
        self.assertEqual(PurgeLog.objects.count(), 0)


@override_settings(SECURE_SSL_REDIRECT=False)
class UsersFormTests(TestCase):
    """The Admin Users form: saving a user with a profile and a role (accounts/views.py, forms.py)."""

    def setUp(self):
        self.main = main_profile()
        self.admin = join_main(make_user("boss", admin=True), ROLE_EDITOR)
        self.client.force_login(self.admin)

    def _profile_field(self, profile):
        return f"profile_{profile.pk}"

    def test_create_user_with_a_diary_profile_and_role(self):
        resp = self.client.post(
            reverse("user_create"),
            {
                "username": "nora",
                "email": "",
                "password1": PASSWORD,
                "password2": PASSWORD,
                self._profile_field(self.main): ROLE_EDITOR,
            },
        )
        self.assertRedirects(resp, reverse("user_list"))
        nora = User.objects.get(username="nora")
        # Not an Admin by default.
        self.assertFalse(nora.is_superuser)
        membership = ProfileMembership.objects.get(user=nora, profile=self.main)
        self.assertEqual(membership.role, ROLE_EDITOR)
        self.assertFalse(membership.suspended)
        self.assertEqual(membership.program, suite.KEY_DIARY)

    def test_create_user_without_a_profile_choice_gets_no_access(self):
        resp = self.client.post(
            reverse("user_create"),
            {
                "username": "owen",
                "email": "",
                "password1": PASSWORD,
                "password2": PASSWORD,
                self._profile_field(self.main): "",
            },
        )
        self.assertRedirects(resp, reverse("user_list"))
        owen = User.objects.get(username="owen")
        self.assertEqual(ProfileMembership.objects.filter(user=owen).count(), 0)

    def test_edit_user_changes_the_role_for_a_profile(self):
        member = join_main(make_user("pat"), ROLE_READER)
        resp = self.client.post(
            reverse("user_edit", args=[member.pk]),
            {
                "username": "pat",
                "email": "",
                "is_active": "on",
                "landing_program": "",
                self._profile_field(self.main): ROLE_EDITOR,
            },
        )
        self.assertRedirects(resp, reverse("user_list"))
        self.assertEqual(
            ProfileMembership.objects.get(user=member, profile=self.main).role, ROLE_EDITOR
        )

    def test_edit_user_removing_a_profile_takes_access_away(self):
        member = join_main(make_user("quinn"), ROLE_READER)
        resp = self.client.post(
            reverse("user_edit", args=[member.pk]),
            {
                "username": "quinn",
                "email": "",
                "is_active": "on",
                "landing_program": "",
                self._profile_field(self.main): "",
            },
        )
        self.assertRedirects(resp, reverse("user_list"))
        # The live membership is deleted (not suspended) when the profile is still live.
        self.assertFalse(
            ProfileMembership.objects.filter(user=member, profile=self.main).exists()
        )

    def test_user_list_shows_profiles_text(self):
        join_main(make_user("sam"), ROLE_READER)
        resp = self.client.get(reverse("user_list"))
        self.assertEqual(resp.status_code, 200)
        by_name = {u.username: u for u in resp.context["users"]}
        self.assertEqual(by_name["sam"].profiles_text, "Main (Reader)")
        self.assertEqual(by_name["boss"].profiles_text, "Main (Editor)")


@override_settings(SECURE_SSL_REDIRECT=False)
class ProfileSwitchTests(TestCase):
    """accounts/views.py::profile_switch moves the user between their diary profiles."""

    def setUp(self):
        self.main = main_profile()
        self.junior = Profile.objects.create(program=suite.KEY_DIARY, name="Junior")
        self.user = join_main(make_user("alice"), ROLE_READER)
        ProfileMembership.objects.create(user=self.user, profile=self.junior, role=ROLE_EDITOR)
        # Main used most recently, so it is the one in use at the start.
        ProfileMembership.objects.filter(user=self.user, profile=self.main).update(
            last_used_at=timezone.now()
        )
        self.client.force_login(self.user)

    def test_switch_to_another_profile_redirects_to_the_diary_home(self):
        resp = self.client.post(reverse("profile_switch"), {"profile": self.junior.pk})
        self.assertRedirects(resp, reverse("diary_home"))
        self.assertEqual(get_profile_for(self.user), self.junior)

    def test_switch_to_a_profile_the_user_lacks_is_refused(self):
        stranger = Profile.objects.create(program=suite.KEY_DIARY, name="Stranger")
        resp = self.client.post(reverse("profile_switch"), {"profile": stranger.pk})
        self.assertRedirects(
            resp, reverse("home") + "?home=1", fetch_redirect_response=False
        )
        self.assertEqual(get_profile_for(self.user), self.main)

    def test_switch_is_post_only(self):
        self.assertEqual(self.client.get(reverse("profile_switch")).status_code, 405)


@override_settings(SECURE_SSL_REDIRECT=False)
class HomeButtonsTests(TestCase):
    """The Home page shows one launcher button per diary profile the user can reach."""

    def setUp(self):
        self.main = main_profile()
        self.junior = Profile.objects.create(
            program=suite.KEY_DIARY, name="Junior", display_name="Junior's Law"
        )
        self.user = join_main(make_user("alice"), ROLE_READER)
        ProfileMembership.objects.create(user=self.user, profile=self.junior, role=ROLE_EDITOR)
        ProfileMembership.objects.filter(user=self.user, profile=self.main).update(
            last_used_at=timezone.now()
        )
        self.client.force_login(self.user)

    def test_home_has_a_button_per_profile(self):
        body = self.client.get(reverse("home") + "?home=1").content.decode()
        # The profile in use is a direct link into the diary.
        self.assertIn('href="/caselaw/subjects/">Case Law Diary &middot; Main</a>', body)
        # Other profiles are switch buttons posting the profile id.
        self.assertIn(
            f'name="profile" value="{self.junior.pk}" class="program-link">Junior&#x27;s Law</button>',
            body,
        )

    def test_a_user_with_one_profile_sees_no_switch_button(self):
        ProfileMembership.objects.filter(user=self.user, profile=self.junior).delete()
        body = self.client.get(reverse("home") + "?home=1").content.decode()
        self.assertIn('href="/caselaw/subjects/">Case Law Diary</a>', body)
        self.assertNotIn("program-switch", body)

    def test_a_user_with_no_profile_sees_the_empty_message(self):
        loner = make_user("loner")
        self.client.force_login(loner)
        body = self.client.get(reverse("home") + "?home=1").content.decode()
        self.assertIn("No programs are available to you yet.", body)


@override_settings(SECURE_SSL_REDIRECT=False)
class LandingRedirectTests(TestCase):
    """landing.landing_url / LandingLoginView for a user with and without a diary profile."""

    def setUp(self):
        self.main = main_profile()

    def login(self, username):
        return self.client.post(
            reverse("login"), {"username": username, "password": PASSWORD}
        )

    def test_user_with_a_diary_profile_lands_in_the_diary(self):
        user = join_main(make_user("alice"), ROLE_READER)
        User.objects.filter(pk=user.pk).update(landing_program=suite.KEY_DIARY)
        # With no stored diary settings the opening page is the diary home.
        self.assertRedirects(self.login("alice"), reverse("diary_home"))

    def test_user_without_a_diary_profile_falls_back_to_home(self):
        loner = make_user("loner")
        User.objects.filter(pk=loner.pk).update(landing_program=suite.KEY_DIARY)
        # No profile in the chosen program, so the landing falls back to Home.
        self.assertRedirects(self.login("loner"), reverse("home"))

    def test_no_chosen_program_lands_on_home(self):
        user = join_main(make_user("mara"), ROLE_READER)
        self.assertEqual(user.landing_program, "")
        self.assertRedirects(self.login("mara"), reverse("home"))


@override_settings(SECURE_SSL_REDIRECT=False)
class ClearProfileTests(TestCase):
    """accounts/clear.py::clear_profile empties a profile's diary data, keeping the profile itself."""

    def setUp(self):
        self.main = main_profile()
        self.admin = join_main(make_user("boss", admin=True), ROLE_EDITOR)

    def test_clear_removes_diary_rows_but_keeps_the_profile_and_members(self):
        Subject.objects.create(profile=self.main, name="Keep no more")
        counts = clear.clear_profile(self.main, self.admin)
        self.assertEqual(Subject.objects.filter(profile=self.main).count(), 0)
        self.assertTrue(Profile.objects.filter(pk=self.main.pk).exists())
        self.assertTrue(
            ProfileMembership.objects.filter(user=self.admin, profile=self.main).exists()
        )
        self.assertIn("diary.Subject", counts)
        # A "Before clearing profile" backup is taken first and a PurgeLog row records the clear.
        log = PurgeLog.objects.latest("id")
        self.assertTrue(log.success)
        self.assertIn("Cleared all diary data", log.message)

    def test_clear_preview_lists_the_record_types(self):
        Subject.objects.create(profile=self.main, name="Preview subject")
        rows = clear.clear_preview(self.main)
        row_names = {name for name, _count in rows}
        self.assertIn("Subjects", row_names)
        subjects_count = dict(rows)["Subjects"]
        self.assertEqual(subjects_count, 1)

    def test_clear_view_requires_the_typed_name(self):
        self.client.force_login(self.admin)
        Subject.objects.create(profile=self.main, name="Still here")
        resp = self.client.post(
            reverse("profile_clear", args=[self.main.pk]), {"confirm": "wrong"}
        )
        self.assertRedirects(resp, reverse("profile_clear", args=[self.main.pk]))
        self.assertEqual(Subject.objects.filter(profile=self.main).count(), 1)


@override_settings(SECURE_SSL_REDIRECT=False)
class SuiteBackupRoundTripTests(TestCase):
    """backups/services.py create_backup then restore_backup of a small diary fixture."""

    def setUp(self):
        self.main = main_profile()
        self.smith = Profile.objects.create(program=suite.KEY_DIARY, name="Smith")
        self.admin = join_main(make_user("boss", admin=True), ROLE_EDITOR)
        # A couple of diary subjects across two profiles keeps the round trip small.
        self.subject_main = Subject.objects.create(profile=self.main, name="Main subject")
        self.subject_smith = Subject.objects.create(profile=self.smith, name="Smith subject")

    def test_backup_then_restore_restores_the_same_rows(self):
        backup = services.create_backup("manual", self.admin)
        document = services.parse_backup(backup.data, max_bytes=50 * 1024 * 1024)
        # Wipe the diary data, then restore from the file.
        Subject.objects.all().delete()
        self.assertEqual(Subject.objects.count(), 0)
        services.restore_backup(document, self.admin)
        restored = {(s.name, s.profile_id) for s in Subject.objects.all()}
        self.assertEqual(
            restored,
            {
                ("Main subject", self.main.pk),
                ("Smith subject", self.smith.pk),
            },
        )
        # Profiles and the admin user survive the round trip.
        self.assertTrue(Profile.objects.filter(pk=self.smith.pk).exists())
        self.assertTrue(User.objects.filter(username="boss").exists())

    def test_backup_counts_include_the_diary_subjects(self):
        backup = services.create_backup("manual", self.admin)
        self.assertEqual(backup.record_counts.get("diary.Subject"), 2)
        self.assertGreaterEqual(backup.record_counts.get("accounts.Profile"), 2)


@override_settings(SECURE_SSL_REDIRECT=False)
class HeaderSwitcherContextTests(TestCase):
    """accounts/context_processors.py and accounts/profiles.py: the header switcher context."""

    def setUp(self):
        self.main = main_profile()
        self.junior = Profile.objects.create(
            program=suite.KEY_DIARY, name="Junior", display_name="Junior's Law"
        )
        self.user = join_main(make_user("alice"), ROLE_EDITOR)
        ProfileMembership.objects.create(user=self.user, profile=self.junior, role=ROLE_READER)
        ProfileMembership.objects.filter(user=self.user, profile=self.main).update(
            last_used_at=timezone.now()
        )
        self.factory = RequestFactory()

    def _request(self, user):
        request = self.factory.get("/")
        request.user = user
        return request

    def test_current_profile_context_lists_the_other_profiles(self):
        context = current_profile(self._request(self.user))
        self.assertEqual(context["current_profile"], self.main)
        # Admin aside, the role in the profile in use (Main, Editor) drives diary_editor.
        self.assertTrue(context["diary_editor"])
        self.assertEqual([p.pk for p in context["other_profiles"]], [self.junior.pk])

    def test_program_label_uses_the_display_name_when_set(self):
        # Switch the user so Junior (with a display name) is the one in use.
        ProfileMembership.objects.filter(user=self.user, profile=self.junior).update(
            last_used_at=timezone.now() + timedelta(minutes=1)
        )
        context = program_label(self._request(self.user))
        self.assertEqual(context["program_label"], "Junior's Law")

    def test_program_label_falls_back_to_the_program_name(self):
        # Main has no display name, so the program name is shown.
        context = program_label(self._request(self.user))
        self.assertEqual(context["program_label"], suite.get_names()[suite.KEY_DIARY])

    def test_request_memberships_and_role_use_one_cached_lookup(self):
        request = self._request(self.user)
        memberships = request_memberships(request)
        # The membership in use (Main) comes first.
        self.assertEqual(memberships[0].profile, self.main)
        self.assertEqual({m.profile_id for m in memberships}, {self.main.pk, self.junior.pk})
        self.assertEqual(request_role(request), ROLE_EDITOR)

    def test_anonymous_user_gets_the_empty_switcher_context(self):
        from django.contrib.auth.models import AnonymousUser

        context = current_profile(self._request(AnonymousUser()))
        self.assertIsNone(context["current_profile"])
        self.assertFalse(context["diary_editor"])
        self.assertEqual(context["other_profiles"], [])


@override_settings(SECURE_SSL_REDIRECT=False)
class DefaultProfileHelperTests(TestCase):
    """ensure_default_profile and set_user_profile keep the diary default behaviour."""

    def test_ensure_default_profile_returns_the_seeded_main(self):
        self.assertEqual(ensure_default_profile().name, DEFAULT_PROFILE_NAME)
        self.assertEqual(ensure_default_profile().program, suite.KEY_DIARY)

    def test_set_user_profile_makes_it_the_only_one(self):
        user = make_user("tom")
        set_user_profile(user, main_profile(), ROLE_READER)
        self.assertEqual(get_profile_for(user), main_profile())
        # None removes access.
        set_user_profile(user, None)
        self.assertIsNone(get_profile_for(user))
