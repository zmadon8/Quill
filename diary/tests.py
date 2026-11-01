from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(SECURE_SSL_REDIRECT=False)
class DiaryTests(TestCase):
    def test_home_requires_login(self):
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith(reverse("login")))

    def test_home_shows_title_and_username(self):
        user = get_user_model().objects.create_user("alice", password="x-long-pass-123")
        self.client.force_login(user)
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, "Judgment Diary")
        self.assertContains(resp, "alice")

    def test_healthz_without_login(self):
        resp = self.client.get("/healthz/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b"ok")
