"""Phase 0: the dark-launch flag, program registration and the empty shells."""
from django.utils.html import escape
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts import programs
from accounts.models import ROLE_EDITOR, ROLE_READER, Profile, User
from accounts.profiles import set_user_profile
from accounts.suite import KEY_INVESTMENTS
from investments import pages


def make_user(name, role=ROLE_EDITOR, admin=False, profile=None):
    user = User.objects.create_user(username=name, password="pw-for-tests-1")
    if admin:
        user.is_superuser = True
        user.save()
    profile = profile or Profile.objects.create(name=f"{name}-inv", program=KEY_INVESTMENTS)
    set_user_profile(user, profile, role, KEY_INVESTMENTS)
    return user, profile


class RegistrationTests(TestCase):
    def test_program_registered(self):
        self.assertIn(KEY_INVESTMENTS, programs.program_keys())
        self.assertEqual(programs.get_program(KEY_INVESTMENTS).landing_url_name, "investments_landing")

    def test_follows_flag(self):
        with override_settings(INVESTMENTS_ENABLED=False):
            self.assertFalse(programs.is_enabled(KEY_INVESTMENTS))
            self.assertNotIn(KEY_INVESTMENTS, programs.enabled_program_keys())
        with override_settings(INVESTMENTS_ENABLED=True):
            self.assertIn(KEY_INVESTMENTS, programs.enabled_program_keys())

    def test_profile_model_lists_agree(self):
        from backups import registry

        self.assertEqual(programs.get_program(KEY_INVESTMENTS).profile_models(), registry.INVESTMENT_PROFILE_MODELS)
        self.assertEqual(registry.PROGRAM_PROFILE_MODELS["investments"], registry.INVESTMENT_PROFILE_MODELS)


@override_settings(SECURE_SSL_REDIRECT=False)
class DarkLaunchTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_user("ziyad", admin=True)
        self.client.force_login(self.user)

    @override_settings(INVESTMENTS_ENABLED=False)
    def test_every_url_is_404_when_off(self):
        paths = ["/investments", "/investments/"] + [f"/investments/{p.path}" for p in pages.PAGES]
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    @override_settings(INVESTMENTS_ENABLED=False)
    def test_home_has_no_investments_button_when_off(self):
        response = self.client.get(reverse("home") + "?home=1")
        self.assertNotContains(response, reverse("investments_landing"))

    @override_settings(INVESTMENTS_ENABLED=True)
    def test_home_button_when_on(self):
        response = self.client.get(reverse("home") + "?home=1")
        self.assertContains(response, reverse("investments_landing"))

    @override_settings(INVESTMENTS_ENABLED=False)
    def test_backup_and_restore_work_with_flag_off(self):
        from backups import services

        backup = services.create_backup("manual", self.user)
        self.assertTrue(backup.size_bytes > 0)


@override_settings(INVESTMENTS_ENABLED=True, SECURE_SSL_REDIRECT=False)
class ShellTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_user("ziyad", admin=True)
        self.client.force_login(self.user)

    def test_landing_redirects_to_dashboard(self):
        response = self.client.get("/investments/")
        self.assertRedirects(response, reverse("investments_dashboard"), fetch_redirect_response=False)

    def test_every_shell_renders_with_header_menu_and_tools(self):
        from investments.urls import REAL
        for page in pages.PAGES:
            with self.subTest(page=page.slug):
                response = self.client.get(reverse(pages.url_name(page.slug)))
                self.assertEqual(response.status_code, 200)
                if page.slug not in REAL:      # a real page has its own content; only the shells show the empty-state text
                    self.assertContains(response, page.title)
                    self.assertContains(response, escape(page.empty))
                for label in ("Overview", "Holdings", "Reports", "Alerts", "Settings"):
                    self.assertContains(response, label)
                self.assertContains(response, 'data-money-mode="auto"')

    def test_page_titles_follow_the_fee_register_rule(self):
        # Owner round (2026-11): a page that a header entry or a sub-tab opens shows no title of its own (its name is already
        # underlined above it); its one <h1> is for screen readers. Every other page shows its title. Exactly one <h1> each.
        import re

        menu = pages.menu_slugs()
        self.assertIn("transactions", menu)
        self.assertNotIn("import_statement", menu)
        for page in pages.PAGES:
            with self.subTest(page=page.slug):
                html = self.client.get(reverse(pages.url_name(page.slug))).content.decode()
                h1s = re.findall(r"<h1[^>]*>", html)
                self.assertEqual(len(h1s), 1, h1s)
                self.assertEqual("visually-hidden" in h1s[0], page.slug in menu, h1s[0])
                self.assertNotIn('class="titlebar"', html)

    def test_menu_marks_current_group(self):
        response = self.client.get(reverse("investments_transactions"))
        self.assertContains(response, '<a href="/investments/transactions/" class="on" aria-current="page">Transactions</a>', html=False)

    def test_anonymous_goes_to_login(self):
        self.client.logout()
        response = self.client.get(reverse("investments_dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_user_without_profile_is_refused(self):
        other = User.objects.create_user(username="nobody", password="pw-for-tests-1")
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("investments_dashboard")).status_code, 403)

    def test_reader_can_read(self):
        reader, _ = make_user("reader", ROLE_READER, profile=self.profile)
        self.client.force_login(reader)
        self.assertEqual(self.client.get(reverse("investments_dashboard")).status_code, 200)

    def test_admin_pages_refuse_a_non_admin(self):
        editor, _ = make_user("editor", ROLE_EDITOR, profile=self.profile)
        self.client.force_login(editor)
        for slug in ("admin_prices", "admin_price_history"):
            with self.subTest(slug=slug):
                self.assertEqual(self.client.get(reverse(pages.url_name(slug))).status_code, 403)
        # the catalogue is open to every member since the owner round of November 2026 (its Admin parts stay Admin-only)
        self.assertEqual(self.client.get(reverse(pages.url_name("admin_catalogue"))).status_code, 200)

    def test_money_filters_emit_both_texts(self):
        from django.template import Context, Template

        out = Template("{% load investments_money %}{{ v|inr }}{{ g|inr_signed }}").render(Context({"v": 396000, "g": -60300}))
        self.assertIn('data-auto="₹3.96 lac"', out)
        self.assertIn('data-full="₹3,96,000"', out)
        self.assertIn('data-auto="−₹60.3k"', out)
        self.assertIn("m l", out)
