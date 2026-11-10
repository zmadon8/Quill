"""Owner round 2026-11: Home shows a card per program with live figures, recent activity and quick actions; Search everything."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import ROLE_EDITOR, ROLE_READER, Profile
from accounts.profiles import set_user_profile
from accounts.suite import KEY_FEES
from diary.sample_data import load_sample_data
from diary.tests.helpers import join_main, main_profile
from fees.models import Firm
from fees.tests import xlsx_support as xs

User = get_user_model()
PASSWORD = "x-long-pass-123"


@override_settings(SECURE_SSL_REDIRECT=False, FEES_ENABLED=True)
class HomeDashboardTests(TestCase):
    def setUp(self):
        load_sample_data(main_profile())
        self.fees = Profile.objects.create(program=KEY_FEES, name="Home-Fees")
        xs.seed_web_data(self.fees)
        self.editor = join_main(User.objects.create_user("eve", password=PASSWORD, first_name="Eve", last_name="Ng"), "editor")
        set_user_profile(self.editor, self.fees, ROLE_EDITOR, KEY_FEES)
        self.reader = join_main(User.objects.create_user("rex", password=PASSWORD), "reader")

    def home(self, user):
        self.client.force_login(user)
        resp = self.client.get(reverse("home") + "?home=1")
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def test_cards_with_figures_for_each_given_program(self):
        html = self.home(self.editor)
        self.assertIn('class="program-card"', html)
        self.assertIn('<a class="program-link" href="%s">' % reverse("diary_home"), html)
        self.assertIn('<a class="program-link" href="%s">' % reverse("fees_landing"), html)
        for label in ("<dt>Subjects</dt>", "<dt>Items</dt>", "<dt>Flagged</dt>", "<dt>Memos this year</dt>", "<dt>Outstanding</dt>",
                      "<dt>Drafts</dt>"):
            self.assertIn(label, html)
        self.assertIn("Good ", html)

    def test_editor_gets_quick_actions_and_recent_activity(self):
        html = self.home(self.editor)
        self.assertIn('href="%s">New memo</a>' % reverse("fees_memo_new"), html)
        self.assertIn('href="%s">Record a payment</a>' % reverse("fees_payment_new"), html)
        self.assertIn('href="%s?edit=1">Add to the diary</a>' % reverse("diary_home"), html)
        self.assertIn('href="%s">Search everything</a>' % reverse("suite_search"), html)
        self.assertIn('id="recent-activity"', html)
        self.assertIn("saved", html)                       # the seeded memos
        self.assertNotIn(reverse("backup_now"), html)      # Backup now is for Admins only

    def test_reader_gets_no_write_actions_and_no_fee_register(self):
        html = self.home(self.reader)
        self.assertNotIn(reverse("fees_memo_new"), html)
        self.assertNotIn("?edit=1", html)
        self.assertNotIn('href="%s"' % reverse("fees_landing"), html)

    def test_a_failing_program_does_not_break_home(self):
        with mock.patch("fees.services.dashboard_panels.home_figures", side_effect=RuntimeError("boom")):
            html = self.home(self.editor)
        self.assertIn('<a class="program-link" href="%s">' % reverse("fees_landing"), html)
        self.assertNotIn("<dt>Memos this year</dt>", html)
        self.assertIn("<dt>Subjects</dt>", html)

    def test_header_shows_initials(self):
        html = self.home(self.editor)
        self.assertIn('<span class="who-badge" aria-hidden="true">EN</span>Eve Ng</a>', html)


@override_settings(SECURE_SSL_REDIRECT=False, FEES_ENABLED=True)
class SuiteSearchTests(TestCase):
    def setUp(self):
        load_sample_data(main_profile())
        self.fees = Profile.objects.create(program=KEY_FEES, name="Find-Fees")
        xs.seed_web_data(self.fees)
        self.user = join_main(User.objects.create_user("finn", password=PASSWORD), "editor")
        set_user_profile(self.user, self.fees, ROLE_READER, KEY_FEES)
        self.client.force_login(self.user)

    def test_results_are_grouped_by_program(self):
        resp = self.client.get(reverse("suite_search"), {"q": "Alpha"})
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('id="results-diary"', html)
        self.assertIn('id="results-fees"', html)
        self.assertIn("Alpha &amp; Co", html)
        firm = Firm.objects.get(profile=self.fees, name="Alpha & Co")
        self.assertIn(reverse("fees_firm_detail", args=[firm.pk]), html)

    def test_short_queries_ask_for_more(self):
        html = self.client.get(reverse("suite_search"), {"q": "a"}).content.decode()
        self.assertIn("Type at least two letters.", html)

    def test_needs_sign_in(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("suite_search")).status_code, 302)

    def test_a_program_that_fails_is_skipped(self):
        with mock.patch("diary.search.run_search", side_effect=RuntimeError("boom")):
            html = self.client.get(reverse("suite_search"), {"q": "Alpha"}).content.decode()
        self.assertIn("could not be searched just now", html)
        self.assertIn("Alpha &amp; Co", html)
