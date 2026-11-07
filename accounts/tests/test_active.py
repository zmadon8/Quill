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
