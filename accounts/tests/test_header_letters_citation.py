"""Owner round (2026-11): header badge letters and the citation hyphen are per-user settings; no ';' between inline citations."""
import re

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from diary.tests.helpers import join_main

User = get_user_model()
PASSWORD = "x-long-pass-123"


def badge(page):
    return re.search(r'<span class="who-badge" aria-hidden="true">([^<]*)</span>', page).group(1)


@override_settings(SECURE_SSL_REDIRECT=False)
class HeaderLettersTests(TestCase):
    def setUp(self):
        self.user = join_main(User.objects.create_user("eve", password=PASSWORD, first_name="Eve", last_name="Ng"), "editor")
        self.client.force_login(self.user)

    def post(self, **data):
        return self.client.post(reverse("my_settings"), {"tab": "display", "landing_program": "", **data})

    def test_blank_falls_back_to_initials(self):
        self.assertEqual(badge(self.client.get(reverse("home")).content.decode()), "EN")

    def test_chosen_letters_show_in_upper_case(self):
        self.post(header_initials=" xyz ")
        self.user.refresh_from_db()
        self.assertEqual(self.user.header_initials, "XYZ")
        self.assertEqual(badge(self.client.get(reverse("home")).content.decode()), "XYZ")

    def test_more_than_three_letters_refused(self):
        self.post(header_initials="ABCD")
        self.user.refresh_from_db()
        self.assertEqual(self.user.header_initials, "")

    def test_leaving_it_out_keeps_it_and_blank_clears_it(self):
        self.user.header_initials = "QQ"
        self.user.save()
        self.post()
        self.user.refresh_from_db()
        self.assertEqual(self.user.header_initials, "QQ")
        self.post(header_initials="")
        self.user.refresh_from_db()
        self.assertEqual(self.user.header_initials, "")


@override_settings(SECURE_SSL_REDIRECT=False)
class CitationHyphenSettingTests(TestCase):
    def setUp(self):
        self.user = join_main(User.objects.create_user("hal", password=PASSWORD), "editor")
        self.client.force_login(self.user)

    def test_default_off_and_setting_saves(self):
        self.assertFalse(self.user.remove_citation_hyphen)
        resp = self.client.post(reverse("my_settings"), {"tab": "display", "landing_program": "", "remove_citation_hyphen": "on"})
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.remove_citation_hyphen)
        self.assertContains(self.client.get(reverse("my_settings") + "?tab=display"), 'name="remove_citation_hyphen"')
