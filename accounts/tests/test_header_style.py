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
    """D85, D86: the main Home page header has icons too (same choice), and its pages are merged into groups with tabs."""

    GROUPS = ("Users &amp; Profiles", "Backups &amp; Import", "Settings", "Help")

    def setUp(self):
        self.admin = join_main(User.objects.create_user("adam", password=PASSWORD, is_superuser=True), "editor")
        self.client.force_login(self.admin)

    def page(self, name="home"):
        url = reverse(name) + ("?home=1" if name == "home" else "")
        return self.client.get(url).content.decode()

    def header(self, name="home"):
        return self.page(name).split('<header class="site-header"')[1].split("</header>")[0]

    def tabs(self, name):
        html = self.page(name)
        if 'class="subnav"' not in html:
            return []
        nav = html.split('class="subnav"')[1].split("</nav>")[0]
        return re.findall(r">([^<]+)</a>", nav)

    def test_every_home_page_item_is_an_icon_with_its_name(self):
        header = self.header()
        for name in self.GROUPS:
            link = re.search(r'<a [^>]*aria-label="%s" title="%s">(.*?)</a>' % (name, name), header, re.S)
            self.assertIsNotNone(link, name)
            self.assertIn("<svg", link.group(1), name)
        for gone in ("Profiles", "Import", "My settings", "Site"):
            self.assertNotIn('aria-label="%s"' % gone, header, gone)
        logout = re.search(r'<button type="submit" class="link nav-icon" aria-label="Log out" title="Log out">(.*?)</button>', header, re.S)
        self.assertIsNotNone(logout)
        self.assertIn("<svg", logout.group(1))

    def test_words_on_the_home_page(self):
        self.admin.header_style = "words"
        self.admin.save(update_fields=["header_style"])
        nav = re.sub(r"<[^>]*>", " ", self.header().split('class="program-nav"')[1])
        for word in ("Users &amp; Profiles", "Backups &amp; Import", "Settings", "Help", "Log out"):
            self.assertIn(word, nav, word)
        self.assertNotIn("nav-icon", self.header())

    def test_each_merged_page_has_its_tabs_and_the_header_item_stays_marked(self):
        self.assertEqual(self.tabs("user_list"), ["Users", "Profiles"])
        self.assertEqual(self.tabs("profile_list"), ["Users", "Profiles"])
        self.assertEqual(self.tabs("backup_list"), ["Backups", "Email backups", "Import"])
        self.assertEqual(self.tabs("backup_email"), ["Backups", "Email backups", "Import"])
        self.assertEqual(self.tabs("import_word"), ["Backups", "Email backups", "Import"])
        settings_tabs = ["Account", "Display", "Numbers", "Word export", "Diary", "My edits", "Site"]  # D93
        for name in ("my_settings", "settings", "profile_settings", "my_edits", "password_change"):
            self.assertEqual(self.tabs(name), settings_tabs, name)
        self.assertEqual(self.tabs("home"), [])
        self.assertRegex(self.header("profile_list"), r'class="nav-icon on" aria-current="page" aria-label="Users &amp; Profiles"')
        self.assertRegex(self.header("backup_email"), r'class="nav-icon on" aria-current="page" aria-label="Backups &amp; Import"')
        self.assertRegex(self.header("settings"), r'class="nav-icon on" aria-current="page" aria-label="Settings"')
        html = self.page("backup_email")
        nav = html.split('class="subnav"')[1].split("</nav>")[0]
        self.assertIn('href="%s" class="on" aria-current="page">Email backups</a>' % reverse("backup_email"), nav)
        self.assertNotIn('class="on" aria-current="page">Backups</a>', nav)

    def test_header_items_open_the_first_sub_page(self):
        header = self.header()
        for url, label in ((reverse("user_list"), "Users &amp; Profiles"), (reverse("backup_list"), "Backups &amp; Import"),
                           (reverse("my_settings") + "?tab=account", "Settings")):
            self.assertRegex(header, r'<a href="%s" class="nav-icon" aria-label="%s"' % (re.escape(url), label))

    def test_readers_see_only_settings_and_help(self):
        reader = join_main(User.objects.create_user("rita", password=PASSWORD))
        self.client.force_login(reader)
        header = self.header()
        for name in ("Users &amp; Profiles", "Backups &amp; Import"):
            self.assertNotIn('aria-label="%s"' % name, header, name)
        for name in ("Settings", "Help"):
            self.assertIn('aria-label="%s"' % name, header, name)
        # D93: a reader with a profile has every Settings tab but Site
        self.assertEqual(self.tabs("my_settings"), ["Account", "Display", "Numbers", "Word export", "Diary", "My edits"])
        loner = User.objects.create_user("lone", password=PASSWORD)  # no diary profile: Account and Display only
        self.client.force_login(loner)
        self.assertEqual(self.tabs("my_settings"), ["Account", "Display"])
