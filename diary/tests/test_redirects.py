"""Round 8, item 1: the 301 redirects (unknown pages, /caselaw, the old /caselaw/subjects/ address)."""
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Profile, User
from diary.models import Subject
from diary.tests.helpers import join_main, main_profile

PASSWORD = "x-long-pass-123"
HTML = {"HTTP_ACCEPT": "text/html,application/xhtml+xml"}


@override_settings(SECURE_SSL_REDIRECT=False)
class RedirectTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.editor = join_main(User.objects.create_user("erin", password=PASSWORD), "editor")
        cls.reader = join_main(User.objects.create_user("rita", password=PASSWORD))
        cls.no_profile = User.objects.create_user("nina", password=PASSWORD)
        cls.subject = Subject.objects.create(profile=main_profile(), name="Arbitration", landing_position=1)

    def test_diary_home_url(self):
        self.assertEqual(reverse("diary_home"), "/caselaw/home/")

    def test_caselaw_with_and_without_slash_go_to_program_home(self):
        for path in ("/caselaw", "/caselaw/"):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 301, path)
            self.assertEqual(resp["Location"], "/caselaw/home/", path)

    def test_old_subjects_page_keeps_the_query_string(self):
        resp = self.client.get("/caselaw/subjects/?edit=1")
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp["Location"], "/caselaw/home/?edit=1")

    def test_old_root_subjects_page_is_a_single_hop(self):
        resp = self.client.get("/subjects/?edit=1")
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp["Location"], "/caselaw/home/?edit=1")

    def test_subject_contents_address_is_unchanged(self):
        self.assertEqual(reverse("subject_contents", args=[7]), "/caselaw/subjects/7/")

    def test_program_home_page_renders(self):
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get("/caselaw/home/").status_code, 200)

    def test_unknown_root_page_in_a_browser_goes_to_suite_home(self):
        for path in ("/nope/", "/nope"):
            resp = self.client.get(path, **HTML)
            self.assertEqual(resp.status_code, 301, path)
            self.assertEqual(resp["Location"], "/?home=1", path)

    def test_unknown_caselaw_page_goes_to_program_home_with_a_profile(self):
        self.client.force_login(self.reader)
        resp = self.client.get("/caselaw/nope/", **HTML)
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp["Location"], "/caselaw/home/")

    def test_unknown_caselaw_page_goes_to_suite_home_without_a_profile(self):
        self.client.force_login(self.no_profile)
        resp = self.client.get("/caselaw/nope/", **HTML)
        self.assertEqual((resp.status_code, resp["Location"]), (301, "/?home=1"))
        self.client.logout()
        resp = self.client.get("/caselaw/nope/", **HTML)
        self.assertEqual((resp.status_code, resp["Location"]), (301, "/?home=1"))

    def test_only_browser_page_requests_are_redirected(self):
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get("/nope/").status_code, 404)  # no Accept header
        self.assertEqual(self.client.get("/nope/", HTTP_ACCEPT="application/json").status_code, 404)
        self.assertEqual(self.client.post("/nope/", **HTML).status_code, 404)
        self.assertEqual(self.client.get("/nope/", HTTP_X_REQUESTED_WITH="fetch", **HTML).status_code, 404)
        self.assertEqual(self.client.get("/nope/", HTTP_X_REQUESTED_WITH="XMLHttpRequest", **HTML).status_code, 404)

    def test_assets_and_health_check_are_not_redirected(self):
        for path in ("/static/nope.css", "/favicon.ico", "/nope.js", "/nope.map"):
            self.assertEqual(self.client.get(path, **HTML).status_code, 404, path)
        self.assertEqual(self.client.get("/healthz/", **HTML).status_code, 200)

    def test_missing_record_redirects_with_a_message(self):
        self.client.force_login(self.reader)
        resp = self.client.get("/caselaw/subjects/999999/", **HTML)
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp["Location"], "/caselaw/home/")
        page = self.client.get(resp["Location"], **HTML)
        self.assertContains(page, "That page no longer exists.")
        self.assertNotContains(self.client.get("/caselaw/home/", **HTML), "That page no longer exists.")

    def test_another_profiles_record_redirects_the_same_way(self):
        other = Profile.objects.create(program="diary", name="Other")
        theirs = Subject.objects.create(profile=other, name="Theirs", landing_position=1)
        self.client.force_login(self.reader)
        resp = self.client.get("/caselaw/subjects/%d/" % theirs.pk, **HTML)
        self.assertEqual((resp.status_code, resp["Location"]), (301, "/caselaw/home/"))

    def test_forbidden_stays_forbidden(self):
        self.client.force_login(self.reader)
        resp = self.client.post(reverse("edit_rename"), {"kind": "subject", "id": self.subject.pk, "name": "X"}, **HTML)
        self.assertEqual(resp.status_code, 403)
