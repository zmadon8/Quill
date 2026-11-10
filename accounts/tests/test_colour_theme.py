"""Owner round (2026-11): a colour theme per user (My settings > Display), applied to every page for that user only."""
import os
import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.profiles import ensure_default_profile
from diary.tests.helpers import join_main

User = get_user_model()
PASSWORD = "x-long-pass-123"


def html_tag(page):
    return re.search(r"<html[^>]*>", page).group(0)


@override_settings(SECURE_SSL_REDIRECT=False)
class ColourThemeTests(TestCase):
    def setUp(self):
        self.user = join_main(User.objects.create_user("tess", password=PASSWORD), "editor")
        self.other = join_main(User.objects.create_user("omar", password=PASSWORD), "editor")
        self.client.force_login(self.user)

    def page(self, name="my_settings"):
        return self.client.get(reverse(name)).content.decode()

    def test_oxblood_is_the_default_and_needs_no_attribute(self):
        self.assertEqual(self.user.colour_theme, "oxblood")
        self.assertNotIn("data-theme", html_tag(self.page()))
        self.assertNotIn("data-theme", html_tag(self.page("home")))

    def test_the_display_section_offers_every_theme(self):
        page = self.page()
        self.assertIn('name="colour_theme"', page)
        for key, label in User.COLOUR_THEME_CHOICES:
            self.assertIn(f'value="{key}"', page)
            self.assertIn(label, page)

    def test_choosing_a_theme_applies_to_this_user_only(self):
        resp = self.client.post(reverse("my_settings"), {"tab": "display", "landing_program": "", "colour_theme": "navy"})
        self.assertRedirects(resp, reverse("my_settings") + "?tab=display", fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.colour_theme, "navy")
        self.assertIn('data-theme="navy"', html_tag(self.page()))
        self.assertIn('data-theme="navy"', html_tag(self.page("home")))
        self.client.force_login(self.other)
        self.assertNotIn("data-theme", html_tag(self.page()))

    def test_leaving_the_theme_out_of_a_post_keeps_it(self):
        self.user.colour_theme = "teal"
        self.user.save()
        self.client.post(reverse("my_settings"), {"tab": "display", "landing_program": ""})
        self.user.refresh_from_db()
        self.assertEqual(self.user.colour_theme, "teal")

    def test_an_unknown_theme_is_refused(self):
        resp = self.client.post(reverse("my_settings"), {"tab": "display", "landing_program": "", "colour_theme": "purple"})
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.colour_theme, "oxblood")

    def test_an_admin_can_set_a_users_theme(self):
        admin = User.objects.create_user("ada", password=PASSWORD, is_superuser=True)
        self.client.force_login(admin)
        url = reverse("user_edit", args=[self.user.pk])
        self.assertContains(self.client.get(url), 'name="colour_theme"')
        resp = self.client.post(url, {"username": "tess", "is_active": "on", f"profile_{ensure_default_profile().pk}": "editor",
                                      "colour_theme": "plum"})
        self.assertRedirects(resp, reverse("user_list"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.colour_theme, "plum")

    def test_every_theme_has_its_colours_in_tokens_css(self):
        with open(os.path.join(settings.BASE_DIR, "static", "css", "tokens.css"), encoding="utf-8") as handle:
            css = handle.read()
        for key, _label in User.COLOUR_THEME_CHOICES:
            if key == User.THEME_OXBLOOD:
                continue
            block = re.search(r'html\[data-theme="%s"\]\s*\{([^}]*)\}' % key, css)
            self.assertIsNotNone(block, key)
            for name in ("--accent:", "--accent-hover:", "--accent-tint:"):
                self.assertIn(name, block.group(1), key)

    def test_the_fee_register_no_longer_redeclares_the_palette(self):
        # A colour declared on body.ledger would beat the theme on <html>.
        with open(os.path.join(settings.BASE_DIR, "static", "css", "ledger.css"), encoding="utf-8") as handle:
            body = re.search(r"body\.ledger \{([^}]*)\}", handle.read()).group(1)
        for name in ("--accent:", "--paper:", "--ink:", "--oxblood:"):
            self.assertNotIn(name, body)
