"""The header bar is always Words (round 23: the Words or Logo choice and the hide-Home option are gone). Only the user
badge, Search, Home and Sign out are icons. The diary, Fee Register and Investments headers have no Settings link: the user
name opens My settings, whose tabs lead to each program's settings."""
import re

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from diary.tests.helpers import join_main

User = get_user_model()
PASSWORD = "x-long-pass-123"
NAMES = ("Trash", "Export", "Help")
SIGN_OUT = r'<button type="submit" class="link nav-icon signout-button" aria-label="Sign out" title="Sign out">(.*?)</button>'


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

    def test_words_show_the_names_and_only_the_fixed_items_are_icons(self):
        header = self.header()
        text = self.visible_text(header)
        for word in NAMES:
            self.assertIn(word, text, word)
        for word in ("Search", "Home", "Sign out"):
            self.assertNotIn(word, text, word)  # always icons
        self.assertNotIn('class="nav-icon on"', header)
        self.assertEqual(header.count("nav-icon"), 1)  # Sign out only
        self.assertIn('class="icon-tool search-toggle"', header)
        self.assertIn('class="home-button" href=', header)
        self.assertIsNotNone(re.search(SIGN_OUT, header, re.S))
        # Back, Forward, Search, Home and Sign out are the only icons
        self.assertEqual(header.count("<svg"), 5)

    def test_the_diary_header_has_no_settings_link(self):
        header = self.header()
        self.assertNotIn('aria-label="Settings"', header)
        self.assertNotIn(reverse("profile_settings"), header)
        self.assertIn(reverse("my_settings"), header)  # the user name

    def test_home_is_always_shown(self):
        self.assertIn('class="home-button" href=', self.header())
        self.assertIn('class="home-button" href=', self.header("my_settings"))

    def test_export_is_the_only_download_item(self):
        # D101: no separate Offline item; Export opens the Export page.
        header = self.header()
        self.assertNotIn('aria-label="Offline"', header)
        self.assertNotIn("type=offline", header)
        export = re.search(r'<a [^>]*aria-label="Export"[^>]*>(.*?)</a>', header, re.S)
        self.assertIn('href="%s"' % reverse("export"), export.group(0))
        self.assertEqual(export.group(1), "Export")

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
        self.assertRegex(header, r'class="on" aria-current="page" aria-label="Export"')

    def test_there_is_no_header_bar_choice_anywhere(self):
        self.assertNotContains(self.client.get(reverse("my_settings")), "header_style")
        self.assertNotContains(self.client.get(reverse("my_settings")), "show_home_button")
        admin = join_main(User.objects.create_user("adam", password=PASSWORD, is_superuser=True), "editor")
        self.client.force_login(admin)
        body = self.client.get(reverse("settings")).content.decode()
        self.assertNotIn("_brand", body)
        self.assertNotIn("Logo", body)

    def test_context_variables(self):
        from accounts.context_processors import header_style, suite_names

        request = self.client.get(reverse("diary_home")).wsgi_request
        self.assertTrue(header_style(request)["header_words"])
        self.assertTrue(suite_names(request)["home_header_words"])
        self.assertNotIn("show_home_button", header_style(request))


@override_settings(SECURE_SSL_REDIRECT=False)
class SuiteHeaderTests(TestCase):
    """The main Home page header is words too, and its pages are grouped with tabs: Admins (Users,
    Profiles, Profile Access, Appearance, Backups), Settings (short links: My settings and each program's Settings tab, only for a
    program the user can open) and Help. The user name in the header opens My settings."""

    GROUPS = ("Admins", "Settings", "Help")
    ADMIN_TABS = ["Users", "Profiles", "Profile Access", "Appearance", "Backups"]
    SETTINGS_TABS = ["My Settings", "Case Law Diary Settings"]

    def setUp(self):
        self.admin = join_main(User.objects.create_user("adam", password=PASSWORD, is_superuser=True), "editor")
        self.client.force_login(self.admin)

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

    def test_every_home_page_item_is_a_word_and_sign_out_is_an_icon(self):
        header = self.header()
        nav = re.sub(r"<[^>]*>", " ", header.split('class="program-nav"')[1])
        for word in self.GROUPS:
            self.assertIn(word, nav, word)
        for gone in ("Profiles", "Import", "My Settings", "Site", "Users &amp; Profiles", "Case Law Diary"):
            self.assertNotIn('aria-label="%s"' % gone, header, gone)
        self.assertNotIn("Sign out", nav)
        logout = re.search(SIGN_OUT, header, re.S)
        self.assertIsNotNone(logout)
        self.assertIn("<svg", logout.group(1))
        self.assertEqual(header.count("nav-icon"), 1)

    def test_each_merged_page_has_its_tabs_and_the_header_item_stays_marked(self):
        for name in ("user_list", "profile_list", "settings", "backup_list", "user_create"):
            self.assertEqual(self.tabs(name), self.ADMIN_TABS, name)
            self.assertRegex(self.header(name), r'class="on" aria-current="page" aria-label="Admins"', name)
        for name, query in (("my_settings", ""), ("my_settings", "?tab=account"), ("my_settings", "?tab=display"),
                            ("my_settings", "?tab=diary"), ("password_change", "")):
            self.assertEqual(self.tabs(name, query), self.SETTINGS_TABS, (name, query))
            self.assertRegex(self.header(name, query), r'class="on" aria-current="page" aria-label="Settings"')
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
            self.assertRegex(header, r'<a href="%s" class="" aria-label="%s"' % (re.escape(url), label))
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
