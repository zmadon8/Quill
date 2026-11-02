"""Template assertions for Milestone 7: skip link, labelled icon buttons, Help page, error pages, first-run hint."""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from diary.tests.helpers import join_main

PASSWORD = "x-long-pass-123"


@override_settings(SECURE_SSL_REDIRECT=False)
class AccessibilityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("carol", password=PASSWORD)
        join_main(self.user)
        self.client.force_login(self.user)

    def test_every_page_has_skip_link_and_main_target(self):
        for name in ("home", "help", "diary_home", "search", "review_list"):
            resp = self.client.get(reverse(name) + ("?home=1" if name == "home" else ""))
            self.assertContains(resp, 'class="skip-link" href="#main"', msg_prefix=name)
            self.assertContains(resp, '<main id="main">', msg_prefix=name)

    def test_icon_only_buttons_have_labels(self):
        resp = self.client.get(reverse("diary_home"))
        self.assertContains(resp, 'aria-label="Home"')
        self.assertContains(resp, 'aria-label="Search"')
        self.assertContains(resp, 'aria-label="Back"')
        self.assertContains(resp, 'aria-label="Forward"')

    def test_search_input_has_a_label(self):
        resp = self.client.get(reverse("diary_home"))
        self.assertContains(resp, '<label class="visually-hidden" for="search-pop-q">')

    def test_html_declares_language_and_viewport(self):
        resp = self.client.get(reverse("diary_home"))
        self.assertContains(resp, '<html lang="en">')
        self.assertContains(resp, 'name="viewport"')

    def test_stylesheets_have_focus_and_reduced_motion_rules(self):
        base = Path(settings.BASE_DIR) / "static" / "css"
        self.assertIn(":focus-visible", (base / "site.css").read_text())
        self.assertIn("prefers-reduced-motion", (base / "site.css").read_text())
        self.assertIn("prefers-reduced-motion", (base / "edit.css").read_text())


@override_settings(SECURE_SSL_REDIRECT=False)
class HelpAndHintTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("dave", password=PASSWORD)
        join_main(self.user)
        self.client.force_login(self.user)

    def test_help_requires_login(self):
        self.client.logout()
        resp = self.client.get(reverse("help"))
        self.assertEqual(resp.status_code, 302)

    def test_help_covers_each_topic_and_has_one_h1(self):
        resp = self.client.get(reverse("help"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "<h1>Help</h1>", count=1, html=True)
        for heading in ("Trash and Undo", "Search", "Settings", "Profiles and users", "Backups and restore",
                        "Export to Word", "Import from Word", "Editing"):
            self.assertContains(resp, heading)

    def test_home_links_to_help(self):
        resp = self.client.get(reverse("home") + "?home=1")
        self.assertContains(resp, reverse("help"))

    def test_empty_diary_shows_first_run_hint(self):
        resp = self.client.get(reverse("diary_home"))
        self.assertContains(resp, "This diary is empty")


@override_settings(SECURE_SSL_REDIRECT=False)
class ErrorPageTests(TestCase):
    def test_error_templates_are_friendly_and_link_home(self):
        from django.template.loader import render_to_string
        for name in ("404.html", "403.html", "500.html", "403_csrf.html"):
            html = render_to_string(name)
            self.assertIn("Skip to content", html, name)
            self.assertIn('href="/?home=1"', html, name)
            self.assertIn("<h1>", html, name)

    def test_non_browser_unknown_address_is_a_real_404_with_friendly_page(self):
        resp = self.client.get("/nothing-here.css")
        self.assertEqual(resp.status_code, 404)

    def test_browser_unknown_address_still_redirects_home(self):
        resp = self.client.get("/nothing-here/", HTTP_ACCEPT="text/html")
        self.assertEqual(resp.status_code, 302)

    def test_reader_gets_friendly_403_for_trash(self):
        user = get_user_model().objects.create_user("erin", password=PASSWORD)
        join_main(user)
        self.client.force_login(user)
        resp = self.client.get(reverse("trash"))
        self.assertEqual(resp.status_code, 403)
