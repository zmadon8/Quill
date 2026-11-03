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
        # The Export page uses the diary header bar (the Help page uses the suite Home header).
        header = self.header("export")
        self.assertRegex(header, r'class="nav-icon on" aria-current="page" aria-label="Export"')

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


@override_settings(SECURE_SSL_REDIRECT=False)
class SuiteHeaderTests(TestCase):
    """D85: the main Home page header has icons too, and follows the same choice."""

    SUITE = ("Profiles", "Users", "Import", "Backups", "Settings", "Help", "My settings")

    def setUp(self):
        self.admin = join_main(User.objects.create_user("adam", password=PASSWORD, is_superuser=True), "editor")
        self.client.force_login(self.admin)

    def header(self, name="home"):
        url = reverse(name) + ("?home=1" if name == "home" else "")
        html = self.client.get(url).content.decode()
        return html.split('<header class="site-header"')[1].split("</header>")[0]

    def test_every_home_page_link_is_an_icon_with_its_name(self):
        header = self.header()
        for name in self.SUITE:
            link = re.search(r'<a [^>]*aria-label="%s" title="%s">(.*?)</a>' % (name, name), header, re.S)
            self.assertIsNotNone(link, name)
            self.assertIn("<svg", link.group(1), name)
        logout = re.search(r'<button type="submit" class="link nav-icon" aria-label="Log out" title="Log out">(.*?)</button>', header, re.S)
        self.assertIsNotNone(logout)
        self.assertIn("<svg", logout.group(1))
        nav = re.sub(r"<[^>]*>", " ", header.split('class="program-nav"')[1])
        for word in self.SUITE + ("Log out",):
            self.assertNotIn(word, nav, word)

    def test_words_on_the_home_page(self):
        self.admin.header_style = "words"
        self.admin.save(update_fields=["header_style"])
        header = self.header()
        nav = re.sub(r"<[^>]*>", " ", header.split('class="program-nav"')[1])
        for word in self.SUITE + ("Log out",):
            self.assertIn(word, nav, word)
        self.assertNotIn("nav-icon", header)

    def test_the_current_page_is_marked_and_readers_see_only_their_links(self):
        self.assertRegex(self.header("user_list"), r'class="nav-icon on" aria-current="page" aria-label="Users"')
        reader = join_main(User.objects.create_user("rita", password=PASSWORD))
        self.client.force_login(reader)
        header = self.header()
        for name in ("Profiles", "Users", "Import", "Backups", "Settings"):
            self.assertNotIn('aria-label="%s"' % name, header, name)
        for name in ("Help", "My settings"):
            self.assertIn('aria-label="%s"' % name, header, name)

