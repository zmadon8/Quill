"""Owner item 5: Admin > Users and Profiles sort by every column, and every table in the suite is resizable."""
import re
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, ProfileMembership

User = get_user_model()
ROOT = Path(__file__).resolve().parent.parent.parent
PASSWORD = "correct-horse-battery-9"


def join(user, profile, role):
    return ProfileMembership.objects.create(user=user, profile=profile, program=profile.program, role=role)


def cell_texts(html, column):
    """The text of one column of the first table (by data-table-id order) in the page."""
    rows = re.findall(r"<tr>(.*?)</tr>", html.split("<tbody>", 1)[1].split("</tbody>", 1)[0], re.S)
    return [re.sub(r"<[^>]+>", "", re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)[column]).strip() for r in rows]


@override_settings(SECURE_SSL_REDIRECT=False)
class UserSortTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.admin = User.objects.create_user("boss", password=PASSWORD, is_superuser=True)
        cls.bob = User.objects.create_user("bob", password=PASSWORD)
        cls.amy = User.objects.create_user("Amy", password=PASSWORD, is_active=False)
        cls.cat = User.objects.create_user("cat", password=PASSWORD)
        cls.admin.last_login = now
        cls.admin.save()
        cls.bob.last_login = now - timedelta(days=3)
        cls.bob.save()
        cls.cat.last_login = now - timedelta(days=9)
        cls.cat.save()
        alpha = Profile.objects.create(program="diary", name="Alpha")
        zulu = Profile.objects.create(program="diary", name="Zulu")
        join(cls.bob, zulu, "editor")
        join(cls.cat, alpha, "reader")

    def setUp(self):
        self.client.force_login(self.admin)

    def names(self, query=""):
        resp = self.client.get(reverse("user_list") + query)
        self.assertEqual(resp.status_code, 200)
        return cell_texts(resp.content.decode(), 0), resp

    def test_default_is_username_ascending_ignoring_case(self):
        names, _ = self.names()
        self.assertEqual(names, ["Amy", "bob", "boss", "cat"])

    def test_every_column_sorts_both_ways(self):
        expected = {
            "username": ["Amy", "bob", "boss", "cat"],
            "admin": ["Amy", "bob", "cat", "boss"],  # False first; ties by username
            "profiles": ["Amy", "boss", "cat", "bob"],  # "" < "alpha (reader)" < "zulu (editor)"
            "active": ["Amy", "bob", "boss", "cat"],  # inactive Amy first, then the rest by username
            "last_login": ["Amy", "cat", "bob", "boss"],  # never logged in first, oldest to newest
        }
        for key, ascending in expected.items():
            names, _ = self.names("?sort=" + key)
            self.assertEqual(names, ascending, key)
            names, _ = self.names("?sort=-" + key)
            # Descending reverses the primary key only: ties stay in username order.
            self.assertEqual(sorted(names), sorted(ascending), key)
        names, _ = self.names("?sort=-username")
        self.assertEqual(names, ["cat", "boss", "bob", "Amy"])
        names, _ = self.names("?sort=-last_login")
        self.assertEqual(names, ["boss", "bob", "cat", "Amy"])
        names, _ = self.names("?sort=-admin")
        self.assertEqual(names, ["boss", "Amy", "bob", "cat"])
        names, _ = self.names("?sort=-active")
        self.assertEqual(names, ["bob", "boss", "cat", "Amy"])
        names, _ = self.names("?sort=-profiles")
        self.assertEqual(names, ["bob", "cat", "Amy", "boss"])

    def test_unknown_sort_is_ignored(self):
        for junk in ("?sort=password", "?sort=-", "?sort=", "?sort=--username", "?sort=username;drop"):
            names, resp = self.names(junk)
            self.assertEqual(names, ["Amy", "bob", "boss", "cat"], junk)

    def test_headers_are_links_with_aria_sort_and_the_next_direction(self):
        _, resp = self.names("?sort=last_login")
        html = resp.content.decode()
        self.assertIn('aria-sort="ascending"><a class="sort-link" href="%s?sort=-last_login">Last Login</a>' % reverse("user_list"), html)
        self.assertEqual(html.count("aria-sort="), 5)
        self.assertIn('aria-sort="none"><a class="sort-link" href="%s?sort=username">Username</a>' % reverse("user_list"), html)
        _, resp = self.names("?sort=-last_login")
        self.assertIn('aria-sort="descending"><a class="sort-link" href="%s?sort=last_login">Last Login' % reverse("user_list"),
                      resp.content.decode())

    def test_the_table_is_resizable(self):
        _, resp = self.names()
        self.assertContains(resp, 'data-table-id="admin-users"')
        self.assertContains(resp, "js/resizable-columns.js")


@override_settings(SECURE_SSL_REDIRECT=False)
class ProfileSortTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user("boss", password=PASSWORD, is_superuser=True)
        cls.beta = Profile.objects.create(program="diary", name="beta", display_name="Zed Chambers")
        cls.alpha = Profile.objects.create(program="diary", name="Alpha")
        cls.gamma = Profile.objects.create(program="diary", name="Gamma", display_name="Ann Chambers")
        for i in range(2):
            join(User.objects.create_user("m%d" % i, password=PASSWORD), cls.beta, "reader")
        join(User.objects.create_user("solo", password=PASSWORD), cls.gamma, "reader")

    def setUp(self):
        self.client.force_login(self.admin)

    def names(self, query=""):
        resp = self.client.get(reverse("profile_list") + query)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        rows = [n for n in cell_texts(html, 0) if n in ("Alpha", "beta", "Gamma")]
        return rows, html

    def test_default_is_name_ascending(self):
        self.assertEqual(self.names()[0], ["Alpha", "beta", "Gamma"])

    def test_name_users_and_display_name_both_ways(self):
        self.assertEqual(self.names("?sort=name")[0], ["Alpha", "beta", "Gamma"])
        self.assertEqual(self.names("?sort=-name")[0], ["Gamma", "beta", "Alpha"])
        self.assertEqual(self.names("?sort=users")[0], ["Alpha", "Gamma", "beta"])
        self.assertEqual(self.names("?sort=-users")[0], ["beta", "Gamma", "Alpha"])
        self.assertEqual(self.names("?sort=display_name")[0], ["Alpha", "Gamma", "beta"])
        self.assertEqual(self.names("?sort=-display_name")[0], ["beta", "Gamma", "Alpha"])

    def test_program_and_subjects_sort_with_name_as_the_tie_break(self):
        # All three are diary profiles with no subjects, so every tie falls back to the name, ascending.
        for key in ("program", "-program", "subjects", "-subjects"):
            self.assertEqual(self.names("?sort=" + key)[0], ["Alpha", "beta", "Gamma"], key)

    def test_unknown_sort_is_ignored(self):
        for junk in ("?sort=pk", "?sort=-", "?sort=members"):
            self.assertEqual(self.names(junk)[0], ["Alpha", "beta", "Gamma"], junk)

    def test_headers_link_to_the_next_direction(self):
        _, html = self.names("?sort=users")
        self.assertIn('aria-sort="ascending"><a class="sort-link" href="%s?sort=-users">Users</a>' % reverse("profile_list"), html)
        self.assertIn('aria-sort="none"><a class="sort-link" href="%s?sort=name">Name</a>' % reverse("profile_list"), html)
        self.assertIn('data-table-id="admin-profiles"', html)


class EveryTableIsResizableTests(SimpleTestCase):
    """Static guard: every <table> in templates/ has a data-table-id, ids are unique per template, and the script loads."""

    # Templates whose tables are deliberately not given an id: none today. Add "path": "reason" here before adding one.
    ALLOWED_WITHOUT_ID = {}

    def tables(self):
        for path in sorted((ROOT / "templates").rglob("*.html")):
            for tag in re.findall(r"<table\b[^>]*>", path.read_text()):
                yield path.relative_to(ROOT).as_posix(), tag

    def test_every_table_has_a_stable_data_table_id(self):
        found = list(self.tables())
        self.assertGreaterEqual(len(found), 30)
        for path, tag in found:
            if path in self.ALLOWED_WITHOUT_ID:
                continue
            self.assertIn("data-table-id=", tag, "%s: %s" % (path, tag))

    def test_ids_are_unique_within_a_template_and_well_formed(self):
        seen = {}
        for path, tag in self.tables():
            m = re.search(r'data-table-id="([^"]+)"', tag)
            if not m:
                continue
            value = m.group(1)
            if "{{" not in value:
                self.assertRegex(value, r"^[a-z0-9][a-z0-9_-]{0,39}$", path)
            self.assertNotIn((path, value), seen, "%s repeats %s" % (path, value))
            seen[(path, value)] = True

    def test_no_old_spelling_is_left_in_templates(self):
        for path in (ROOT / "templates").rglob("*.html"):
            self.assertNotIn("data-resizable-columns", path.read_text(), path.name)

    def test_the_shared_script_is_loaded_by_the_suite_shell_once(self):
        shell = (ROOT / "templates/base_suite.html").read_text()
        self.assertEqual(shell.count("js/resizable-columns.js"), 1)
        for path in (ROOT / "templates").rglob("*.html"):
            if path.name != "base_suite.html":
                self.assertNotIn("js/resizable-columns.js", path.read_text(), path.name)
        # It loads before the page scripts, so fees/columns.js can use QuillColumns.
        self.assertLess(shell.index("js/resizable-columns.js"), shell.index("{% block extra_js %}"))

    def test_the_fees_script_uses_the_shared_component_and_keeps_server_storage(self):
        source = (ROOT / "static/js/fees/columns.js").read_text()
        self.assertIn("QuillColumns.attach", source)
        self.assertIn('"col-widths:" + id', source)
        self.assertIn("quill.fees.widths.", source)
        self.assertNotIn("setPointerCapture", source)
        shared = (ROOT / "static/js/resizable-columns.js").read_text()
        self.assertIn('"quill.cols."', shared)
        self.assertIn("setPointerCapture", shared)
