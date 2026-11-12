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


@override_settings(SECURE_SSL_REDIRECT=False, FEES_ENABLED=True)
class HomeMetricsChoiceTests(TestCase):
    def setUp(self):
        load_sample_data(main_profile())
        self.fees = Profile.objects.create(program=KEY_FEES, name="Metrics-Fees")
        xs.seed_web_data(self.fees)
        self.user = join_main(User.objects.create_user("meg", password=PASSWORD), "editor")
        set_user_profile(self.user, self.fees, ROLE_EDITOR, KEY_FEES)
        self.client.force_login(self.user)

    def post(self, **data):
        return self.client.post(reverse("my_settings"), {"tab": "display", "landing_program": "", **data})

    def home(self):
        return self.client.get(reverse("home") + "?home=1").content.decode()

    def test_defaults_when_nothing_chosen(self):
        from accounts import home_cards

        self.assertEqual(home_cards.chosen_metrics(self.user, "diary"), ["subjects", "items", "flagged"])
        html = self.home()
        for label in ("Subjects", "Items", "Flagged", "Memos this year", "Outstanding", "Drafts"):
            self.assertIn("<dt>%s</dt>" % label, html)

    def test_choice_is_saved_and_shown_exactly(self):
        resp = self.post(home_metrics_present="1", home_metrics_diary=["flagged", "subjects"], home_metrics_fees=["payments"])
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.home_metrics["diary"], ["subjects", "flagged"])
        self.assertEqual(self.user.home_metrics["fees"], ["payments"])
        self.assertNotIn("investments", self.user.home_metrics)
        html = self.home()
        self.assertIn("<dt>Flagged</dt>", html)
        self.assertNotIn("<dt>Items</dt>", html)
        self.assertIn("<dt>Payments recorded</dt>", html)
        self.assertNotIn("<dt>Drafts</dt>", html)

    def test_more_than_three_is_rejected(self):
        resp = self.post(home_metrics_present="1", home_metrics_diary=["subjects", "items", "flagged", "clean"])
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.home_metrics, {})

    def test_invalid_key_is_rejected(self):
        resp = self.post(home_metrics_present="1", home_metrics_fees=["nonsense"])
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.home_metrics, {})

    def test_unticking_all_or_absent_keys(self):
        self.post(home_metrics_present="1", home_metrics_diary=["items"])
        self.post()  # no home_metrics keys at all: unchanged
        self.user.refresh_from_db()
        self.assertEqual(self.user.home_metrics["diary"], ["items"])
        self.post(home_metrics_present="1")  # everything unticked: defaults
        self.user.refresh_from_db()
        self.assertEqual(self.user.home_metrics, {})

    def test_stale_stored_keys_fall_back(self):
        from accounts import home_cards

        self.user.home_metrics = {"diary": ["gone", "items", "items", "a", "b"], "fees": "bad"}
        self.assertEqual(home_cards.chosen_metrics(self.user, "diary"), ["items"])
        self.assertEqual(home_cards.chosen_metrics(self.user, "fees"), ["memos_fy", "outstanding", "drafts"])


@override_settings(SECURE_SSL_REDIRECT=False, FEES_ENABLED=True)
class HomeDetailsTests(TestCase):
    def setUp(self):
        load_sample_data(main_profile())
        self.fees = Profile.objects.create(program=KEY_FEES, name="Details-Fees")
        xs.seed_web_data(self.fees)
        self.user = join_main(User.objects.create_user("dee", password=PASSWORD), "editor")
        set_user_profile(self.user, self.fees, ROLE_EDITOR, KEY_FEES)
        self.client.force_login(self.user)

    def post(self, **data):
        return self.client.post(reverse("my_settings"), {"tab": "display", "landing_program": "", **data})

    def home(self):
        resp = self.client.get(reverse("home") + "?home=1")
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def test_chosen_details_validates_and_keeps_catalogue_order(self):
        from accounts import home_cards

        self.assertEqual(home_cards.chosen_details(self.user, "fees"), [])
        self.user.home_details = {"fees": ["who_owes", "gone", "billed_this_year", "who_owes"], "investments": "bad"}
        self.assertEqual(home_cards.chosen_details(self.user, "fees"), ["billed_this_year", "who_owes"])
        self.assertEqual(home_cards.chosen_details(self.user, "investments"), [])

    def test_nothing_chosen_adds_nothing(self):
        self.assertNotIn('class="home-details"', self.home())

    def test_settings_save_and_clear(self):
        resp = self.post(home_details_present="1", home_details_fees=["who_owes", "memos_this_year"],
                         home_details_investments=["over_time", "nonsense"])
        self.assertEqual(resp.status_code, 200)  # the unknown choice is refused
        resp = self.post(home_details_present="1", home_details_fees=["who_owes", "memos_this_year"], home_details_investments=["over_time"])
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.home_details, {"fees": ["memos_this_year", "who_owes"], "investments": ["over_time"]})
        self.post()  # no home_details keys at all: unchanged
        self.user.refresh_from_db()
        self.assertEqual(self.user.home_details["investments"], ["over_time"])
        self.post(home_details_present="1")  # everything unticked: none
        self.user.refresh_from_db()
        self.assertEqual(self.user.home_details, {})

    def test_home_shows_chosen_fee_sections_only(self):
        from fees.models import FeesSettings

        # The seeded sample data switches the Dashboard figures off; they must be on to be offered below the cards.
        FeesSettings.objects.filter(profile=self.fees).update(statistics_enabled=True)
        self.user.home_details = {"fees": ["memos_this_year", "who_owes"]}
        self.user.save()
        html = self.home()
        self.assertIn('class="home-details"', html)
        self.assertIn("<dt>Memos This Year</dt>", html)
        self.assertIn('aria-label="Who owes the most"', html)
        self.assertNotIn('aria-label="Recently billed matters"', html)
        self.assertNotIn("<dt>Billed This Month</dt>", html)

    def test_a_failing_section_does_not_break_home(self):
        self.user.home_details = {"fees": ["who_owes"]}
        self.user.save()
        with mock.patch("fees.services.dashboard_panels.get_panels", side_effect=RuntimeError("boom")):
            html = self.home()
        self.assertNotIn('class="home-details"', html)
        self.assertIn("<dt>Subjects</dt>", html)

    def test_kpis_switched_off_show_a_note(self):
        from fees.services import settings as settings_service

        self.user.home_details = {"fees": ["memos_this_year"]}
        self.user.save()
        config = {**settings_service.get_settings(self.fees), "statistics_enabled": False}
        with mock.patch("fees.services.settings.get_settings", return_value=config):
            html = self.home()
        self.assertIn("switched off in the Fee Register settings", html)
        self.assertNotIn("<dt>Memos This Year</dt>", html)

    def test_investments_items_say_so_when_the_overview_is_not_cached(self):
        from accounts import home_cards

        self.user.home_details = {"investments": ["value", "over_time"]}
        with mock.patch("investments.services.dashboard.peek_payload", return_value=None):
            sections = home_cards._investments_details(None, self.user)
        self.assertEqual([s["kind"] for s in sections], ["note"])
        self.assertEqual(sections[0]["text"], home_cards.NOT_READY)

    def test_migration_field(self):
        field = User._meta.get_field("home_details")
        self.assertEqual(field.get_default(), {})
        self.assertTrue(field.blank)
