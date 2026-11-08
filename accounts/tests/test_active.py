"""Who is active: last_seen_at throttle, the Can See Who Is Active toggle, and the Home panel."""
from datetime import timedelta
from unittest import mock

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, ProfileMembership, User
from backups import services
from diary.tests.helpers import join_main

PASSWORD = "x-long-pass-123"


def updates_of_last_seen(ctx):
    return [q for q in ctx.captured_queries if q["sql"].startswith("UPDATE") and "last_seen_at" in q["sql"]]


@override_settings(SECURE_SSL_REDIRECT=False)
class LastSeenTests(TestCase):
    def setUp(self):
        self.user = join_main(User.objects.create_user("lena", password=PASSWORD))
        self.client.force_login(self.user)

    def test_first_request_sets_it(self):
        self.client.get(reverse("home"), follow=False)
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.last_seen_at)

    def test_no_update_when_seen_a_few_seconds_ago(self):
        stamp = timezone.now() - timedelta(seconds=10)
        User.objects.filter(pk=self.user.pk).update(last_seen_at=stamp)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(reverse("home") + "?home=1")
        self.assertEqual(updates_of_last_seen(ctx), [])
        self.user.refresh_from_db()
        self.assertEqual(self.user.last_seen_at, stamp)

    def test_update_when_stale(self):
        stamp = timezone.now() - timedelta(seconds=120)
        User.objects.filter(pk=self.user.pk).update(last_seen_at=stamp)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(reverse("home") + "?home=1")
        self.assertEqual(len(updates_of_last_seen(ctx)), 1)
        self.user.refresh_from_db()
        self.assertGreater(self.user.last_seen_at, stamp)

    def test_anonymous_and_static_are_skipped(self):
        self.client.logout()
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(reverse("login"))
        self.assertEqual(updates_of_last_seen(ctx), [])


@override_settings(SECURE_SSL_REDIRECT=False)
class ActivePanelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = join_main(User.objects.create_user("boss", password=PASSWORD, is_superuser=True), "editor")
        cls.allowed = join_main(User.objects.create_user("watcher", password=PASSWORD, can_see_active=True))
        cls.other = join_main(User.objects.create_user("plain", password=PASSWORD))
        # Anchored to mid-day so a run just after local midnight cannot misclassify rows.
        now = timezone.localtime(timezone.now()).replace(hour=12, minute=0, second=0, microsecond=0)
        cls.noon = now
        cls.now_user = join_main(User.objects.create_user("nina", password=PASSWORD, first_name="Nina", last_name="Now"))
        cls.later_user = join_main(User.objects.create_user("earl", password=PASSWORD))
        cls.old_user = join_main(User.objects.create_user("olga", password=PASSWORD))
        User.objects.filter(pk=cls.now_user.pk).update(last_seen_at=now - timedelta(minutes=1))
        User.objects.filter(pk=cls.later_user.pk).update(last_seen_at=timezone.localtime(now).replace(hour=0, minute=0, second=1))
        User.objects.filter(pk=cls.old_user.pk).update(last_seen_at=now - timedelta(days=2))
        other_profile = Profile.objects.create(name="Chambers B", program="diary")
        ProfileMembership.objects.create(user=cls.now_user, profile=other_profile, program=other_profile.program, role="reader", last_used_at=now)

    def home(self, user):
        self.client.force_login(user)
        with mock.patch("django.utils.timezone.now", return_value=self.noon):
            return self.client.get(reverse("home") + "?home=1")

    def test_admin_sees_it_without_the_toggle(self):
        self.assertFalse(self.admin.can_see_active)
        self.assertContains(self.home(self.admin), "Active Now")

    def test_toggled_user_sees_it(self):
        self.assertContains(self.home(self.allowed), "Active Now")

    def test_others_and_anonymous_do_not(self):
        self.assertNotContains(self.home(self.other), "Active Now")
        self.client.logout()
        resp = self.client.get(reverse("home") + "?home=1")
        self.assertEqual(resp.status_code, 302)  # anonymous visitors are sent to sign in, never shown the panel
        self.assertNotIn("Active Now", resp.content.decode())

    def test_content_and_order(self):
        resp = self.home(self.admin)
        self.assertContains(resp, "Nina Now")
        self.assertContains(resp, "Chambers B")  # most recently used profile
        self.assertContains(resp, "Earlier Today")
        self.assertNotContains(resp, "olga")
        active = [r["name"] for r in resp.context["active_now"]]
        earlier = [r["name"] for r in resp.context["earlier_today"]]
        self.assertEqual(active[0], "boss")  # the viewer was just seen, so newest
        self.assertIn("Nina Now", active)
        self.assertNotIn("earl", active)
        self.assertEqual(earlier, ["earl"])
        self.assertLess(active.index("boss"), active.index("Nina Now"))

    def test_no_json_endpoint_carries_it(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("home") + "?home=1")
        self.assertNotIn("last_seen_at", resp.content.decode())

    def test_panel_queries_only_for_permitted_viewers(self):
        self.client.force_login(self.other)
        self.client.get(reverse("home") + "?home=1")
        with CaptureQueriesContext(connection) as plain:
            self.client.get(reverse("home") + "?home=1")
        # Compare with a permitted user who is not an Admin, so Admin-only page work is not counted as the panel.
        self.client.force_login(self.allowed)
        self.client.get(reverse("home") + "?home=1")
        with CaptureQueriesContext(connection) as allowed:
            self.client.get(reverse("home") + "?home=1")
        self.assertLessEqual(len(allowed) - len(plain), 4)


@override_settings(SECURE_SSL_REDIRECT=False)
class ToggleFormTests(TestCase):
    def setUp(self):
        self.admin = join_main(User.objects.create_user("boss", password=PASSWORD, is_superuser=True), "editor")
        self.client.force_login(self.admin)

    def test_create_saves_the_toggle(self):
        resp = self.client.post(reverse("user_create"), {
            "username": "newbie", "password1": PASSWORD + "q", "password2": PASSWORD + "q", "can_see_active": "on",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.get(username="newbie").can_see_active)

    def test_edit_saves_and_clears_the_toggle(self):
        target = User.objects.create_user("target", password=PASSWORD)
        url = reverse("user_edit", args=[target.pk])
        self.client.post(url, {"username": "target", "is_active": "on", "landing_program": "", "can_see_active": "on"})
        self.assertTrue(User.objects.get(pk=target.pk).can_see_active)
        self.client.post(url, {"username": "target", "is_active": "on", "landing_program": ""})
        self.assertFalse(User.objects.get(pk=target.pk).can_see_active)

    def test_form_shows_the_label(self):
        self.assertContains(self.client.get(reverse("user_create")), "Can See Who Is Active")


class BackupTests(TestCase):
    def test_fields_round_trip(self):
        admin = User.objects.create_user("boss", password=PASSWORD, is_superuser=True)
        user = User.objects.create_user("lena", password=PASSWORD, can_see_active=True)
        stamp = timezone.now().replace(microsecond=0)
        User.objects.filter(pk=user.pk).update(last_seen_at=stamp)
        doc = services.parse_backup(services.create_backup("manual").data, 10**9)
        User.objects.filter(pk=user.pk).update(last_seen_at=None, can_see_active=False)
        services.restore_backup(doc, admin)
        user = User.objects.get(username="lena")
        self.assertTrue(user.can_see_active)
        self.assertEqual(user.last_seen_at, stamp)


@override_settings(SECURE_SSL_REDIRECT=False, FEES_ENABLED=True)
class ActiveInEveryProfileTests(TestCase):
    """Someone working in a Case Law Diary profile and a Fee Register profile shows both on the Active Now panel."""

    def setUp(self):
        from accounts.suite import KEY_FEES

        self.admin = join_main(User.objects.create_user("boss", password=PASSWORD, is_superuser=True), "editor")
        self.ziyad = join_main(User.objects.create_user("ziyad", password=PASSWORD), "editor")
        self.fees = Profile.objects.create(program=KEY_FEES, name="Ziyad")
        ProfileMembership.objects.create(user=self.ziyad, profile=self.fees, program=KEY_FEES, role="editor")

    def where(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("home") + "?home=1")
        return {r["name"]: r["where"] for r in resp.context["active_now"]}

    def test_a_program_page_records_the_profile_it_used(self):
        self.client.force_login(self.ziyad)
        self.client.get(reverse("diary_home"))
        self.client.get(reverse("fees_dashboard"))
        seen = ProfileMembership.objects.filter(user=self.ziyad, last_seen_at__isnull=False).values_list("program", flat=True)
        self.assertEqual(sorted(seen), ["diary", "fees"])

    def test_both_profiles_show_for_one_user(self):
        self.client.force_login(self.ziyad)
        self.client.get(reverse("diary_home"))
        self.client.get(reverse("fees_dashboard"))
        where = self.where()["ziyad"]
        self.assertIn("Case Law Diary \u00b7 Main", where)
        self.assertIn("Fee Register \u00b7 Ziyad", where)

    def test_only_the_profiles_used_today_show(self):
        self.client.force_login(self.ziyad)
        self.client.get(reverse("diary_home"))
        self.assertEqual(self.where()["ziyad"], "Case Law Diary \u00b7 Main")

    def test_a_second_page_within_a_minute_writes_nothing(self):
        self.client.force_login(self.ziyad)
        self.client.get(reverse("fees_dashboard"))
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(reverse("fees_dashboard"))
        self.assertEqual(updates_of_last_seen(ctx), [])


@override_settings(SECURE_SSL_REDIRECT=False, FEES_ENABLED=True)
class HomeOpensEveryProfileTests(TestCase):
    """Home has a button for each Case Law Diary profile and each Fee Register profile the user has."""

    def setUp(self):
        from accounts.suite import KEY_FEES

        self.user = join_main(User.objects.create_user("ziyad", password=PASSWORD), "editor")
        self.one = Profile.objects.create(program=KEY_FEES, name="Ziyad")
        self.two = Profile.objects.create(program=KEY_FEES, name="Chambers")
        for p in (self.one, self.two):
            ProfileMembership.objects.create(user=self.user, profile=p, program=KEY_FEES, role="editor")
        self.client.force_login(self.user)

    def test_both_fee_register_profiles_have_a_button(self):
        html = self.client.get(reverse("home") + "?home=1").content.decode()
        self.assertIn("Fee Register &middot; Chambers", html.replace("\u00b7", "&middot;"))
        self.assertIn("Fee Register &middot; Ziyad", html.replace("\u00b7", "&middot;"))
        self.assertEqual(html.count('action="%s"' % reverse("profile_switch")), 1)

    def test_the_button_opens_that_profile(self):
        from accounts.profiles import get_profile_for
        from accounts.suite import KEY_FEES

        html = self.client.get(reverse("home") + "?home=1").content.decode()
        other = self.two if 'value="%d"' % self.two.pk in html else self.one
        resp = self.client.post(reverse("profile_switch"), {"profile": other.pk})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(get_profile_for(self.user, KEY_FEES), other)


@override_settings(SECURE_SSL_REDIRECT=False, FEES_ENABLED=True)
class AdminProfileAccessTests(TestCase):
    """Home lists only the profiles given to a user; an Admin opens any other one from Admin Profile Access."""

    def setUp(self):
        from accounts.suite import KEY_FEES

        self.admin = join_main(User.objects.create_user("boss", password=PASSWORD, is_superuser=True), "editor")
        self.other_diary = Profile.objects.create(program="diary", name="Juniors")
        self.fees = Profile.objects.create(program=KEY_FEES, name="Firm Fees")
        self.client.force_login(self.admin)

    def home(self):
        return self.client.get(reverse("home") + "?home=1").content.decode()

    def test_home_lists_only_given_profiles_and_links_to_the_access_page(self):
        html = self.home()
        self.assertNotIn('value="%d"' % self.other_diary.pk, html)
        self.assertNotIn("Firm Fees", html)
        self.assertIn('href="%s"' % reverse("admin_profile_access"), html)

    def test_the_access_page_lists_every_profile_and_opens_one(self):
        from accounts.profiles import get_profile_for
        from accounts.suite import KEY_FEES

        html = self.client.get(reverse("admin_profile_access")).content.decode()
        for p in (self.other_diary, self.fees):
            self.assertIn('name="profile" value="%d"' % p.pk, html)
        resp = self.client.post(reverse("profile_switch"), {"profile": self.fees.pk})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(get_profile_for(self.admin, KEY_FEES), self.fees)
        membership = ProfileMembership.objects.get(user=self.admin, profile=self.fees)
        self.assertTrue(membership.admin_access)
        self.assertNotIn("Firm Fees", self.home())  # opened, but still not given: not on Home

    def test_a_profile_given_on_the_users_screen_shows_on_home(self):
        from accounts.profiles import set_user_profiles, use_profile
        from accounts.suite import KEY_FEES

        use_profile(self.admin, self.fees)
        set_user_profiles(self.admin, {self.fees: "editor"}, KEY_FEES)
        self.assertFalse(ProfileMembership.objects.get(user=self.admin, profile=self.fees).admin_access)
        self.assertIn("Fee Register", self.home())

    def test_others_may_not_open_the_access_page(self):
        reader = join_main(User.objects.create_user("rita", password=PASSWORD))
        self.client.force_login(reader)
        self.assertEqual(self.client.get(reverse("admin_profile_access")).status_code, 403)
        self.assertNotIn('href="%s"' % reverse("admin_profile_access"), self.home())
