"""Round 15 (D84): My settings > Header bar chooses Icons (the default) or Words for the diary header bar."""
import re

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from diary.tests.helpers import join_main

User = get_user_model()
PASSWORD = "x-long-pass-123"
NAMES = ("Trash", "Export", "Help", "Settings")


@override_settings(SECURE_SSL_REDIRECT=False)
class HeaderStyleTests(TestCase):
    def setUp(self):
        self.editor = join_main(User.objects.create_user("eddie", password=PASSWORD), "editor")
        self.client.force_login(self.editor)

    def header(self, name="diary_home"):
        html = self.client.get(reverse(name)).content.decode()
        return html.split('<header class="site-header"')[1].split("</header>")[0]

    def visible_text(self, header):
        nav = header.split('class="program-nav"')[1]
        return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", nav))

    def test_icons_are_the_default_and_every_icon_keeps_its_name(self):
        self.assertEqual(self.editor.header_style, "icons")
        header = self.header()
        for name in NAMES:
            link = re.search(r'<a [^>]*aria-label="%s" title="%s">(.*?)</a>' % (name, name), header, re.S)
            self.assertIsNotNone(link, name)
            self.assertIn("<svg", link.group(1), name)
            self.assertIn('class="nav-icon', link.group(0), name)
        text = self.visible_text(header)
        for word in NAMES + ("Search", "Home"):
            self.assertNotIn(word, text, word)
        self.assertIn('class="icon-tool search-toggle"', header)
        self.assertIn('class="home-button" href=', header)

    def test_words_show_the_names_and_no_icons_for_those_items(self):
        self.editor.header_style = "words"
        self.editor.save(update_fields=["header_style"])
        header = self.header()
        text = self.visible_text(header)
        for word in NAMES + ("Search", "Home"):
            self.assertIn(word, text, word)
        self.assertNotIn('class="nav-icon', header)
        self.assertIn('class="word-tool search-toggle"', header)
        self.assertIn('class="home-button word-tool"', header)
        # only Back and Forward keep their arrows
        self.assertEqual(header.count("<svg"), 2)

    def test_the_current_page_is_still_marked(self):
        header = self.header("help")
        self.assertRegex(header, r'class="nav-icon on" aria-current="page" aria-label="Help"')

    def test_my_settings_saves_the_choice_and_a_post_without_it_keeps_it(self):
        resp = self.client.get(reverse("my_settings"))
        self.assertContains(resp, "Header bar")
        self.assertContains(resp, 'name="header_style" value="words"')
        self.client.post(reverse("my_settings"), {"header_style": "words", "landing_program": ""})
        self.editor.refresh_from_db()
        self.assertEqual(self.editor.header_style, "words")
        self.client.post(reverse("my_settings"), {"landing_program": ""})
        self.editor.refresh_from_db()
        self.assertEqual(self.editor.header_style, "words")
        resp = self.client.post(reverse("my_settings"), {"header_style": "pictures", "landing_program": ""})
        self.assertEqual(resp.status_code, 200)  # not a choice: the form shows the error
        self.editor.refresh_from_db()
        self.assertEqual(self.editor.header_style, "words")

    def test_the_choice_costs_no_extra_query(self):
        self.client.get(reverse("diary_home"))
        with CaptureQueriesContext(connection) as icons:
            self.client.get(reverse("diary_home"))
        self.editor.header_style = "words"
        self.editor.save(update_fields=["header_style"])
        self.client.get(reverse("diary_home"))
        with CaptureQueriesContext(connection) as words:
            self.client.get(reverse("diary_home"))
        self.assertEqual(len(icons), len(words))
