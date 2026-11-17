"""Owner round (2026-12): commas while typing numbers (D212). One per-user switch, on by default; the page flag is <meta name="group-digits">."""
import re

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from diary.tests.helpers import join_main

User = get_user_model()
PASSWORD = "x-long-pass-123"


def html_tag(page):
    """The page's <head>, where the flag sits (the <html> tag itself is left alone)."""
    return page.split("</head>")[0]


@override_settings(SECURE_SSL_REDIRECT=False)
class GroupDigitsSettingTests(TestCase):
    def setUp(self):
        self.user = join_main(User.objects.create_user("gina", password=PASSWORD), "editor")
        self.client.force_login(self.user)

    def page(self, name="my_settings", **query):
        return self.client.get(reverse(name), query).content.decode()

    def test_the_setting_is_on_by_default(self):
        self.assertTrue(self.user.group_digits)
        self.assertIn('<meta name="group-digits" content="on">', html_tag(self.page()))
        self.assertIn('<meta name="group-digits" content="on">', html_tag(self.page("home")))

    def test_the_display_section_has_the_tick_box_ticked(self):
        page = self.page(tab="display")
        tick = re.search(r'<input[^>]*name="group_digits"[^>]*>', page).group(0)
        self.assertIn("checked", tick)
        self.assertIn("Add commas while typing numbers", page)

    def test_the_script_is_loaded_once_by_the_suite_shell(self):
        page = self.page()
        self.assertEqual(page.count("js/number-commas.js"), 1)

    def test_unticking_and_saving_turns_the_attribute_off_for_that_user_only(self):
        other = join_main(User.objects.create_user("omar", password=PASSWORD), "editor")
        resp = self.client.post(reverse("my_settings"), {"tab": "display", "colour_theme": "oxblood"})
        self.assertRedirects(resp, reverse("my_settings") + "?tab=display", fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertFalse(self.user.group_digits)
        self.assertNotIn('<meta name="group-digits" content="on">', html_tag(self.page()))
        self.assertNotIn('<meta name="group-digits" content="on">', html_tag(self.page("home")))
        other.refresh_from_db()
        self.assertTrue(other.group_digits)

    def test_ticking_and_saving_turns_it_back_on(self):
        self.user.group_digits = False
        self.user.save()
        self.client.post(reverse("my_settings"), {"tab": "display", "group_digits": "on", "colour_theme": "oxblood"})
        self.user.refresh_from_db()
        self.assertTrue(self.user.group_digits)
        self.assertIn('<meta name="group-digits" content="on">', html_tag(self.page()))

    def test_saving_another_section_leaves_it_alone(self):
        self.user.group_digits = False
        self.user.save()
        self.client.post(reverse("my_settings"), {"tab": "account", "email": "g@example.com"})
        self.user.refresh_from_db()
        self.assertFalse(self.user.group_digits)

    def test_the_login_page_has_no_attribute(self):
        self.client.logout()
        self.assertNotIn('<meta name="group-digits" content="on">', html_tag(self.client.get(reverse("login")).content.decode()))

    def test_it_travels_with_the_user_in_a_backup(self):
        from backups import registry

        self.assertIn("group_digits", registry.field_names(User))
