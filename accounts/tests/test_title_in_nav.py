"""A page title that only repeats the name already underlined in the header or the sub-tab bar is visually hidden
(kept as the one <h1> for screen readers); a title that is the only visible name stays visible (docs/DESIGN.md)."""
import re

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from diary.tests.helpers import join_main

PASSWORD = "x-long-pass-123"
HIDDEN = '<h1 class="visually-hidden">%s</h1>'
VISIBLE = "<h1>%s</h1>"


@override_settings(SECURE_SSL_REDIRECT=False)
class TitleInNavTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("boss", password=PASSWORD, is_superuser=True)
        join_main(user, "editor")
        self.client.force_login(user)

    def html(self, name, query=""):
        resp = self.client.get(reverse(name) + query)
        self.assertEqual(resp.status_code, 200, name)
        html = resp.content.decode()
        self.assertEqual(len(re.findall(r"<h1[ >]", html)), 1, name + ": exactly one h1")
        return html

    def test_titles_repeating_an_underlined_tab_are_visually_hidden(self):
        for name, title in (("user_list", "Users"), ("profile_list", "Profiles"), ("settings", "Appearance"),
                            ("backup_list", "Backups"), ("my_settings", "Account and Profile View"), ("flags", "Flags"),
                            ("flag_links", "Hyperlinks")):
            self.assertIn(HIDDEN % title, self.html(name), name)

    def test_titles_that_are_the_only_visible_name_stay_visible(self):
        self.assertIn(VISIBLE % "Index of Subjects", self.html("diary_home"))
        self.assertIn(VISIBLE % "Search", self.html("search"))
        self.assertIn(VISIBLE % "Settings", self.html("password_change"))

    def test_pages_named_in_the_header_hide_their_title(self):
        pages = (("home", "?home=1", "Programs"), ("trash", "", "Trash"), ("diary_history", "", "History"),
                 ("export", "", "Export"), ("help", "", "Help"), ("profile_settings", "", "Case Law Diary settings"))
        for name, query, title in pages:
            self.assertIn(HIDDEN % title, self.html(name, query), name)
