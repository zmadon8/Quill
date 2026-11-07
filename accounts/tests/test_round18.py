"""Round 18: deleted users can be restored (D94), several profiles per user (D95), Settings regrouped (D96), export
settings on the Export page and no floating Export button (D97)."""
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, ProfileMembership, PurgeLog
from accounts.profiles import get_profile_for, profile_usage
from accounts.user_trash import delete_user, purge_expired_users
from diary.models import Subject, UserSettings
from diary.tests.helpers import join_main, main_profile

User = get_user_model()
PASSWORD = "x-long-pass-123"


@override_settings(SECURE_SSL_REDIRECT=False)
class SeveralProfilesTests(TestCase):
    def setUp(self):
        self.main = main_profile()
        self.junior = Profile.objects.create(program="diary", name="Junior", display_name="Junior's Law")
        self.user = join_main(User.objects.create_user("alice", password=PASSWORD), "reader")
        ProfileMembership.objects.create(user=self.user, profile=self.junior, role="editor")
        ProfileMembership.objects.filter(user=self.user, profile=self.main).update(last_used_at=timezone.now())
        Subject.objects.create(profile=self.main, name="Main subject")
        Subject.objects.create(profile=self.junior, name="Junior subject")
        self.client.force_login(self.user)

    def test_the_header_offers_the_other_profiles(self):
        body = self.client.get(reverse("diary_home")).content.decode()
        self.assertIn("Main subject", body)
        self.assertNotIn("Junior subject", body)
        menu = body.split("data-profile-switch")[1].split("</details>")[0]
        self.assertIn(f'action="{reverse("profile_switch")}"', menu)
        self.assertIn(f'name="profile" value="{self.junior.pk}"', menu)
        self.assertNotIn(f'value="{self.main.pk}"', menu)

    def test_switching_opens_the_other_profile_with_its_own_role(self):
        resp = self.client.post(reverse("profile_switch"), {"profile": self.junior.pk})
        self.assertRedirects(resp, reverse("diary_home"))
        body = self.client.get(reverse("diary_home")).content.decode()
        self.assertIn("Junior subject", body)
        self.assertNotIn("Main subject", body)
        self.assertIn('href="%s"' % reverse("trash"), body)  # Editor in Junior: Trash is offered
        self.assertEqual(get_profile_for(self.user), self.junior)  # remembered for the next login too
        self.client.post(reverse("profile_switch"), {"profile": self.main.pk})
        self.assertNotIn('href="%s"' % reverse("trash"), self.client.get(reverse("diary_home")).content.decode())

    def test_records_of_the_other_profile_are_not_reachable(self):
        junior_subject = Subject.objects.get(name="Junior subject")
        self.assertEqual(self.client.get(reverse("read_subject", args=[junior_subject.pk])).status_code, 404)

    def test_switching_to_a_profile_i_do_not_have_is_refused(self):
        stranger = Profile.objects.create(program="diary", name="Stranger")
        for value in (stranger.pk, "junk", ""):
            resp = self.client.post(reverse("profile_switch"), {"profile": value})
            self.assertRedirects(resp, reverse("home") + "?home=1", fetch_redirect_response=False)
        self.assertEqual(get_profile_for(self.user), self.main)
        self.assertEqual(self.client.get(reverse("profile_switch")).status_code, 405)

    def test_home_has_a_button_per_profile(self):
        body = self.client.get(reverse("home") + "?home=1").content.decode()
        self.assertIn('href="/caselaw/subjects/">Case Law Diary &middot; Main</a>', body)
        self.assertIn(f'name="profile" value="{self.junior.pk}" class="program-link">Junior&#x27;s Law</button>', body)

    def test_one_profile_shows_no_switcher(self):
        ProfileMembership.objects.filter(user=self.user, profile=self.junior).delete()
        self.assertNotIn("data-profile-switch", self.client.get(reverse("diary_home")).content.decode())
        body = self.client.get(reverse("home") + "?home=1").content.decode()
        self.assertIn('href="/caselaw/subjects/">Case Law Diary</a>', body)
        self.assertNotIn("program-switch", body)


@override_settings(SECURE_SSL_REDIRECT=False, USER_RETENTION_DAYS=30)
class DeletedUserPurgeTests(TestCase):
    def setUp(self):
        self.admin = join_main(User.objects.create_user("boss", password=PASSWORD, is_superuser=True), "editor")
        self.old = join_main(User.objects.create_user("old", password=PASSWORD), "reader")
        self.recent = join_main(User.objects.create_user("recent", password=PASSWORD), "reader")
        UserSettings.objects.create(user=self.old)
        for user in (self.old, self.recent):
            delete_user(user, self.admin)
        User.objects.filter(pk=self.old.pk).update(deleted_at=timezone.now() - timedelta(days=31))

    def good_backup(self):
        from backups import services

        services.create_backup("daily")

    def test_removes_only_users_past_the_window_after_a_good_backup(self):
        self.good_backup()
        call_command("purge_deleted_profiles", stdout=StringIO())
        self.assertFalse(User.objects.filter(pk=self.old.pk).exists())
        self.assertFalse(UserSettings.objects.filter(user_id=self.old.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.recent.pk).exists())
        log = PurgeLog.objects.get()
        self.assertTrue(log.success)
        self.assertIn("old (#", log.message)

    def test_refuses_without_todays_backup(self):
        with self.assertRaises(CommandError):
            call_command("purge_deleted_profiles", stdout=StringIO())
        self.assertTrue(User.objects.filter(pk=self.old.pk).exists())
        self.assertFalse(PurgeLog.objects.get().success)

    def test_nothing_due_logs_nothing(self):
        User.objects.filter(pk=self.old.pk).update(deleted_at=timezone.now())
        self.assertIsNone(purge_expired_users())
        self.assertEqual(PurgeLog.objects.count(), 0)

    def test_deleted_users_do_not_count_as_profile_members_and_show_days_left(self):
        self.assertEqual(profile_usage(main_profile())[0], 1)  # only boss
        self.client.force_login(self.admin)
        page = self.client.get(reverse("user_list")).content.decode()
        deleted = page.split("<h2>Deleted users</h2>")[1]
        self.assertIn("<td>recent</td>", deleted)
        self.assertIn("<td>30</td>", deleted)
        self.assertIn("<td>boss</td>", deleted)
        self.assertNotIn("<td>recent</td>", page.split("<h2>Deleted users</h2>")[0])

    def test_forgot_password_says_a_deleted_user_is_not_found(self):
        from unittest import mock

        User.objects.filter(pk=self.recent.pk).update(email="r@example.com")
        with mock.patch("accounts.views.email_ready", return_value=True):
            resp = self.client.post(reverse("password_reset"), {"username": "recent"})
        self.assertContains(resp, "User not found.")


@override_settings(SECURE_SSL_REDIRECT=False)
class PageNamesTests(TestCase):
    def test_the_site_tab_is_now_appearance_and_explains_the_boxes(self):
        admin = join_main(User.objects.create_user("boss", password=PASSWORD, is_superuser=True), "editor")
        self.client.force_login(admin)
        body = self.client.get(reverse("settings")).content.decode()
        self.assertIn("<h1>Appearance</h1>", body)
        self.assertIn("Everyone", body)
        self.assertIn("Home page name", body)
        self.assertIn("Case law diary name", body)
        self.assertIn('class="on" aria-current="page">Appearance</a>', body)
