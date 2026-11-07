"""Round 15 (D84), changed in round 20 (3.1) and round 22: Admins > Appearance chooses Words (the default) or Logo (icons)
for the header bar of Home, the Case Law Diary and the Fee Register, for everyone. Search, Home and Sign out are ALWAYS
icons, whatever the choice. Most tests below pick Logo in setUp so they can check the icons; the default has its own test."""
import re

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts import suite
from accounts.models import SuiteName
from diary.tests.helpers import join_main

User = get_user_model()
PASSWORD = "x-long-pass-123"
NAMES = ("Trash", "Export", "Help", "Settings")
SIGN_OUT = r'<button type="submit" class="link nav-icon signout-button" aria-label="Sign out" title="Sign out">(.*?)</button>'


def choose_logo_everywhere():
    suite.set_brand_modes({key: suite.BRAND_LOGO for key in suite.BRAND_KEYS})


@override_settings(SECURE_SSL_REDIRECT=False)
class HeaderStyleTests(TestCase):
    def setUp(self):
        self.editor = join_main(User.objects.create_user("eddie", password=PASSWORD), "editor")
        self.client.force_login(self.editor)
        choose_logo_everywhere()

    def header(self, name="diary_home"):
        html = self.client.get(reverse(name)).content.decode()
        return html.split('<header class="site-header"')[1].split("</header>")[0]

    def visible_text(self, header):
        nav = header.split('class="program-nav"')[1]
        return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", nav))

    def test_words_are_the_default_but_search_home_and_sign_out_are_icons(self):
        # Owner: "Words / Logo should default to Words. Search and Home should ALWAYS be logos." (and Sign out)
        SuiteName.objects.filter(key__startswith="brand_").delete()
        self.assertEqual(suite.get_brand_modes(), {"home": "words", "diary": "words", "fees": "words"})
        header = self.header()
        text = self.visible_text(header)
        for word in NAMES:
            self.assertIn(word, text, word)
        self.assertIn('class="icon-tool search-toggle"', header)
        self.assertIn('class="home-button" href=', header)
        self.assertIsNotNone(re.search(SIGN_OUT, header, re.S))

    def test_logo_shows_icons_and_every_icon_keeps_its_name(self):
        header = self.header()
        for name in NAMES:
            link = re.search(r'<a [^>]*aria-label="%s" title="[^"]*">(.*?)</a>' % name, header, re.S)
            self.assertIsNotNone(link, name)
            self.assertIn("<svg", link.group(1), name)
            self.assertIn('class="nav-icon', link.group(0), name)
        text = self.visible_text(header)
        for word in NAMES + ("Search", "Home", "Sign out"):
            self.assertNotIn(word, text, word)
        self.assertIn('class="icon-tool search-toggle"', header)
        self.assertIn('class="home-button" href=', header)

    def test_words_show_the_names_and_no_icons_for_those_items(self):
        suite.set_brand_modes({suite.KEY_DIARY: "words"})
        header = self.header()
        text = self.visible_text(header)
        for word in NAMES:
            self.assertIn(word, text, word)
        for word in ("Search", "Home", "Sign out"):
            self.assertNotIn(word, text, word)  # always icons
        self.assertNotIn('class="nav-icon', header)
        self.assertNotIn("word-tool", header)
        self.assertIn('class="icon-tool search-toggle"', header)
        self.assertIn('class="home-button" href=', header)
        # Back, Forward, Search, Home and Sign out are the only icons
        self.assertEqual(header.count("<svg"), 5)

    def test_export_is_the_only_download_item_and_uses_the_arrow(self):
        # D101: no separate Offline item; Export (downward arrow) opens the Export page.
        header = self.header()
        self.assertNotIn('aria-label="Offline"', header)
        self.assertNotIn("type=offline", header)
        export = re.search(r'<a [^>]*aria-label="Export"[^>]*>(.*?)</a>', header, re.S)
        self.assertIn('href="%s"' % reverse("export"), export.group(0))
        self.assertIn("M12 4v11", export.group(1))
        self.assertNotIn("M8.5 11l1.2 6", export.group(1))

    def test_every_member_still_gets_the_offline_copy_from_the_export_page(self):
        reader = join_main(User.objects.create_user("rita", password=PASSWORD))
        self.client.force_login(reader)
        self.assertNotIn('aria-label="Offline"', self.header())
        resp = self.client.get(reverse("export_download") + "?type=offline&review=1")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment", resp["Content-Disposition"])
        self.assertIn("text/html", resp["Content-Type"])

    def test_the_current_page_is_still_marked(self):
        # The Export page uses the diary header bar (the Help page uses the suite Home header).
        header = self.header("export")
        self.assertRegex(header, r'class="nav-icon on" aria-current="page" aria-label="Export"')

    def test_display_no_longer_has_a_personal_header_bar_choice(self):
        resp = self.client.get(reverse("my_settings"))
        self.assertNotContains(resp, 'name="header_style"')
        self.assertNotContains(resp, "<h2>Header bar</h2>")
        before = self.editor.header_style
        self.client.post(reverse("my_settings"), {"header_style": "words", "landing_program": ""})
        self.editor.refresh_from_db()
        self.assertEqual(self.editor.header_style, before)
        self.assertNotIn(">Trash</a>", self.header())

    def test_the_choice_is_for_everyone_and_set_by_an_admin_on_page_names(self):
        admin = join_main(User.objects.create_user("adam", password=PASSWORD, is_superuser=True), "editor")
        names = {"home_name": "Home", "diary_name": "Case Law Diary", "fees_name": "Fee Register"}
        # a non-Admin may not change it
        self.assertEqual(self.client.post(reverse("settings"), {**names, "diary_brand": "words"}).status_code, 403)
        self.client.force_login(admin)
        resp = self.client.post(reverse("settings"), {**names, "home_brand": "logo", "diary_brand": "words"})
        self.assertEqual(resp.status_code, 302)
        modes = suite.get_brand_modes()
        self.assertEqual((modes["home"], modes["diary"]), ("logo", "words"))
        # a post without the choices keeps them
        self.client.post(reverse("settings"), names)
        self.assertEqual(suite.get_brand_modes()["diary"], "words")
        # not a choice: refused
        resp = self.client.post(reverse("settings"), {**names, "diary_brand": "pictures"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(suite.get_brand_modes()["diary"], "words")
        # everyone now sees Words on the diary
        self.client.force_login(self.editor)
        self.assertIn(">Trash</a>", self.header())

    def test_home_and_diary_choices_are_separate(self):
        suite.set_brand_modes({suite.KEY_HOME: "words"})
        self.assertNotIn(">Trash</a>", self.header())  # the diary is still Logo
        suite.set_brand_modes({suite.KEY_HOME: "logo", suite.KEY_DIARY: "words"})
        self.assertIn(">Trash</a>", self.header())
        home = self.client.get(reverse("home") + "?home=1").content.decode()
        self.assertIn('class="nav-icon"', home.split('<header class="site-header"')[1].split("</header>")[0])

    def test_page_names_offers_the_fee_register_choice_only_when_it_is_enabled(self):
        admin = join_main(User.objects.create_user("adam", password=PASSWORD, is_superuser=True), "editor")
        self.client.force_login(admin)
        with override_settings(FEES_ENABLED=True):
            body = self.client.get(reverse("settings")).content.decode()
            for key in ("home_brand", "diary_brand", "fees_brand"):
                self.assertIn('name="%s"' % key, body)
        with override_settings(FEES_ENABLED=False):
            body = self.client.get(reverse("settings")).content.decode()
            self.assertIn('name="diary_brand"', body)
            self.assertNotIn('name="fees_brand"', body)

    def test_context_variables(self):
        from accounts.context_processors import header_style, suite_names

        suite.set_brand_modes({suite.KEY_FEES: "words"})
        request = self.client.get(reverse("diary_home")).wsgi_request
        self.assertEqual(suite_names(request)["suite_brand"], {"home": "logo", "diary": "logo", "fees": "words"})
        self.assertFalse(header_style(request)["header_words"])

    def test_the_choice_costs_no_extra_query(self):
        self.client.get(reverse("diary_home"))
        with CaptureQueriesContext(connection) as icons:
            self.client.get(reverse("diary_home"))
        suite.set_brand_modes({suite.KEY_DIARY: "words"})
        self.client.get(reverse("diary_home"))
        with CaptureQueriesContext(connection) as words:
            self.client.get(reverse("diary_home"))
        self.assertEqual(len(icons), len(words))


@override_settings(SECURE_SSL_REDIRECT=False)
class SuiteHeaderTests(TestCase):
    """The main Home page header has icons too (same choice), and its pages are grouped with tabs: Admins (Users,
    Profiles, Appearance, Backups), Settings (short links: My settings and each program's Settings tab, only for a
    program the user can open) and Help. The user name in the header opens My settings."""

    GROUPS = ("Admins", "Settings", "Help")
    ADMIN_TABS = ["Users", "Profiles", "Appearance", "Backups"]
    SETTINGS_TABS = ["My Settings", "Case Law Diary Settings"]

    def setUp(self):
        self.admin = join_main(User.objects.create_user("adam", password=PASSWORD, is_superuser=True), "editor")
        self.client.force_login(self.admin)
        choose_logo_everywhere()

    def page(self, name="home", query=""):
        url = reverse(name) + ("?home=1" if name == "home" else query)
        return self.client.get(url).content.decode()

    def header(self, name="home", query=""):
        return self.page(name, query).split('<header class="site-header"')[1].split("</header>")[0]

    def _subnav(self, html, index):
        """The labels in the ``index``-th <nav class="subnav"> (0 = first-level tabs, 1 = the diary's Numbers/Edits)."""
        parts = html.split('class="subnav"')
        if len(parts) <= index + 1:
            return []
        nav = parts[index + 1].split("</nav>")[0]
        return re.findall(r">([^<]+)</a>", nav)

    def tabs(self, name, query=""):
        return self._subnav(self.page(name, query), 0)

    def test_every_home_page_item_is_an_icon_with_its_name(self):
        header = self.header()
        for name in self.GROUPS:
            link = re.search(r'<a [^>]*aria-label="%s" title="[^"]*">(.*?)</a>' % name, header, re.S)
            self.assertIsNotNone(link, name)
            self.assertIn("<svg", link.group(1), name)
        for gone in ("Profiles", "Import", "My Settings", "Site", "Users &amp; Profiles", "Case Law Diary"):
            self.assertNotIn('aria-label="%s"' % gone, header, gone)
        logout = re.search(SIGN_OUT, header, re.S)
        self.assertIsNotNone(logout)
        self.assertIn("<svg", logout.group(1))

    def test_words_on_the_home_page(self):
        suite.set_brand_modes({suite.KEY_HOME: "words"})
        nav = re.sub(r"<[^>]*>", " ", self.header().split('class="program-nav"')[1])
        for word in self.GROUPS:
            self.assertIn(word, nav, word)
        # Sign out is always the logo, never the words, even in Words mode.
        self.assertNotIn("Sign out", nav)
        header = self.header()
        logout = re.search(SIGN_OUT, header, re.S)
        self.assertIsNotNone(logout)
        self.assertIn("<svg", logout.group(1))
        self.assertEqual(header.count("nav-icon"), 1)

    def test_each_merged_page_has_its_tabs_and_the_header_item_stays_marked(self):
        for name in ("user_list", "profile_list", "settings", "backup_list", "user_create"):
            self.assertEqual(self.tabs(name), self.ADMIN_TABS, name)
            self.assertRegex(self.header(name), r'class="nav-icon on" aria-current="page" aria-label="Admins"', name)
        for name, query in (("my_settings", ""), ("my_settings", "?tab=account"), ("my_settings", "?tab=display"),
                            ("my_settings", "?tab=diary"), ("password_change", "")):
            self.assertEqual(self.tabs(name, query), self.SETTINGS_TABS, (name, query))
            self.assertRegex(self.header(name, query), r'class="nav-icon on" aria-current="page" aria-label="Settings"')
        self.assertEqual(self.tabs("home"), [])

    def test_the_old_email_backups_and_import_tabs_are_gone(self):
        labels = self.tabs("backup_list")
        self.assertNotIn("Email Backups", labels)
        self.assertNotIn("Import", labels)
        self.assertNotIn("Page Names", labels)

    def test_the_settings_links_are_named_after_the_programs(self):
        from accounts import suite

        suite.set_names({suite.KEY_HOME: "Home", suite.KEY_DIARY: "Judgments"})
        self.assertEqual(self.tabs("my_settings"), ["My Settings", "Judgments Settings"])
        header = self.header()
        self.assertNotIn('aria-label="Judgments"', header)
        self.assertNotIn('aria-label="Case Law Diary"', header)

    def test_header_items_open_the_first_sub_page(self):
        # Each header item opens its first tab: Admins -> Users; Settings -> My settings.
        header = self.header()
        for url, label in ((reverse("user_list"), "Admins"), (reverse("my_settings"), "Settings")):
            self.assertRegex(header, r'<a href="%s" class="nav-icon" aria-label="%s"' % (re.escape(url), label))
        self.assertNotIn('aria-label="Case Law Diary"', header)

    def test_the_user_name_opens_my_settings(self):
        header = self.header()
        self.assertRegex(header, r'<a class="who" href="%s[^"]*"' % re.escape(reverse("my_settings")))

    def test_a_user_with_a_diary_profile_sees_the_diary_settings_link(self):
        reader = join_main(User.objects.create_user("rita", password=PASSWORD))
        self.client.force_login(reader)
        header = self.header()
        self.assertNotIn('aria-label="Admins"', header)
        for name in ("Settings", "Help"):
            self.assertIn('aria-label="%s"' % name, header, name)
        self.assertEqual(self.tabs("my_settings"), ["My Settings", "Case Law Diary Settings"])
        loner = User.objects.create_user("lone", password=PASSWORD)  # no diary profile: only My settings
        self.client.force_login(loner)
        self.assertEqual(self.tabs("my_settings"), [])  # one link only, so no sub-navigation row
        self.assertNotIn('aria-label="Case Law Diary"', self.header())
