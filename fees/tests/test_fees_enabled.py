"""The FEES_ENABLED dark-launch flag (design U11): off hides and blocks the Fee Register, on changes nothing."""
from django.test import override_settings
from django.urls import reverse

from accounts import landing, programs
from accounts.suite import KEY_FEES
from fees.models import Firm
from fees.tests.test_views_read import SeededViewsBase


@override_settings(SECURE_SSL_REDIRECT=False)
class FeesFlagOffTests(SeededViewsBase):
    def get(self, url):
        self.login(self.reader)
        return self.client.get(url)

    @override_settings(FEES_ENABLED=False)
    def test_fees_urls_are_404(self):
        for url in ("/fees/", "/fees/dashboard/", "/fees/memos/", "/fees/settings/", "/fees/backup/", "/fees"):
            self.assertEqual(self.get(url).status_code, 404, url)

    @override_settings(FEES_ENABLED=False)
    def test_no_home_button_or_settings_tab(self):
        home = self.get(reverse("home") + "?home=1")
        self.assertEqual(home.status_code, 200)
        self.assertNotIn(reverse("fees_landing"), home.content.decode())
        settings_page = self.get(reverse("my_settings"))
        self.assertNotIn(reverse("fees_settings"), settings_page.content.decode())

    @override_settings(FEES_ENABLED=False)
    def test_not_offered_or_opened_as_a_landing_program(self):
        self.assertNotIn(KEY_FEES, programs.enabled_program_keys())
        self.assertNotIn(KEY_FEES, landing.program_keys())
        self.assertIsNone(landing.landing_url_name(KEY_FEES))
        self.reader.landing_program = KEY_FEES
        self.assertEqual(landing.landing_url(self.reader), reverse("home"))

    @override_settings(FEES_ENABLED=False)
    def test_data_and_registry_are_kept(self):
        self.assertIn(KEY_FEES, programs.program_keys())
        self.assertTrue(Firm.objects.filter(profile=self.profile).exists())

    @override_settings(FEES_ENABLED=False)
    def test_profile_switch_does_not_open_fees(self):
        self.login(self.reader)
        response = self.client.post(reverse("profile_switch"), {"profile": self.profile.pk})
        self.assertNotIn("/fees", response["Location"])


@override_settings(SECURE_SSL_REDIRECT=False)
class FeesFlagOnTests(SeededViewsBase):
    @override_settings(FEES_ENABLED=True)
    def test_everything_works(self):
        self.login(self.reader)
        self.assertEqual(self.client.get("/fees/dashboard/").status_code, 200)
        home = self.client.get(reverse("home") + "?home=1")
        self.assertIn(reverse("fees_landing"), home.content.decode())
        self.assertIn(KEY_FEES, landing.program_keys())
        self.assertEqual(landing.landing_url_name(KEY_FEES), "fees_landing")
        settings_page = self.client.get(reverse("my_settings"))
        self.assertIn(reverse("fees_settings"), settings_page.content.decode())
