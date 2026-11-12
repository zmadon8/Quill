"""Owner round (2026-11): Statistics (with the Dashboard) and Bank can each be switched off in Settings (per profile, Editors).

Statistics off: no Statistics or Dashboard in the header or the Statistics tabs, its address opens the person's first page, an Opening
page of Dashboard opens Memos, and the program name links to the first page. Bank off: no Bank filter or column on
Feebook, no Bank account box on a payment, no Bank column in the Feebook export, no bank list in Settings; a bank in an
old link is ignored, and editing a payment keeps the bank it had. Both are on by default and round-trip through the
Fee Register backup keys.
"""
from django.test import override_settings
from django.urls import reverse

from fees.models import FeesSettings, Payment
from fees.pages import feebook_filters
from fees.personal_form import FeesPersonalForm
from fees.services import excel_backup, prefs
from fees.services import settings as settings_service
from fees.services.excel_restore import _WEB_BOOL_KEYS
from fees.tests.test_views_write import WriteBase


def _switch(profile, **values):
    settings_service.update_settings(profile, values)


def _nav(html):
    return html[html.index('<nav class="program-nav"'):html.index("</nav>", html.index('<nav class="program-nav"'))]


@override_settings(SECURE_SSL_REDIRECT=False, FEES_ENABLED=True)
class DashboardSwitchTests(WriteBase):
    def test_on_by_default_and_in_the_backup_keys(self):
        config = settings_service.get_settings(self.profile)
        self.assertTrue(config["show_bank"])
        self.assertNotIn("dashboard_enabled", config)
        self.assertNotIn("dashboard_kpis_enabled", config)
        for key in ("statistics_enabled", "show_bank"):
            self.assertIn(key, excel_backup.WEB_SETTINGS_KEYS)
            self.assertIn(key, _WEB_BOOL_KEYS)
        for key in ("dashboard_enabled", "dashboard_kpis_enabled", "items_per_page"):
            self.assertNotIn(key, excel_backup.WEB_SETTINGS_KEYS)

    def test_settings_page_saves_both_switches(self):
        page = self.client.get(reverse("fees_settings") + "?tab=years")
        self.assertContains(page, 'name="statistics_enabled"')
        self.assertNotContains(page, 'name="dashboard_enabled"')
        self.assertNotContains(page, 'name="dashboard_kpis_enabled"')
        self.assertContains(page, 'name="show_bank"')
        self.post("fees_settings", {"tab": "years", "statistics_enabled": "0"})
        self.post("fees_settings", {"tab": "payments", "show_bank": "0"})
        row = FeesSettings.objects.get(profile=self.profile)
        self.assertEqual((row.statistics_enabled, row.show_bank), (False, False))
        self.post("fees_settings", {"tab": "years", "statistics_enabled": ["0", "1"]})
        self.assertTrue(FeesSettings.objects.get(profile=self.profile).statistics_enabled)

    def test_statistics_off_leaves_the_header_and_tabs_and_the_dashboard_address_opens_the_first_page(self):
        _switch(self.profile, statistics_enabled=False)
        nav = _nav(self.client.get(reverse("fees_memos")).content.decode())
        self.assertNotIn(">Dashboard</a>", nav)
        self.assertNotIn(">Statistics</a>", nav)
        self.assertIn(">Memos</a>", nav)
        response = self.client.get(reverse("fees_dashboard"))
        self.assertRedirects(response, reverse("fees_landing"), fetch_redirect_response=False)

    def test_an_opening_page_of_dashboard_opens_memos_when_statistics_is_off_and_is_not_offered(self):
        prefs.set_personal(self.profile, self.editor, {"default_tab": "dashboard"})
        self.assertRedirects(self.client.get(reverse("fees_landing")), reverse("fees_dashboard"), fetch_redirect_response=False)
        _switch(self.profile, statistics_enabled=False)
        self.assertRedirects(self.client.get(reverse("fees_landing")), reverse("fees_memos"), fetch_redirect_response=False)
        form = FeesPersonalForm(profile=self.profile, user=self.editor, fees_settings=FeesSettings.objects.get(profile=self.profile))
        self.assertNotIn("dashboard", [value for value, _label in form.fields["default_tab"].choices])


@override_settings(SECURE_SSL_REDIRECT=False, FEES_ENABLED=True)
class BankSwitchTests(WriteBase):
    def payment_post(self, **over):
        data = {"amount": "900", "tds_rate": "10", "auto_tds": "1", "date_of_payment": "2026-09-01", "payee": "Typed payee",
                "payment_mode": "NEFT"}
        data.update(over)
        return data

    def test_feebook_shows_bank_while_on(self):
        text = self.client.get(reverse("fees_feebook") + "?fy=").content.decode()
        self.assertIn('<select name="bank">', text)
        self.assertIn('<th scope="col">Bank</th>', text)
        self.assertIn("HDFC Current", text)

    def test_feebook_has_no_bank_filter_or_column_when_off_and_ignores_an_old_bank_link(self):
        _switch(self.profile, show_bank=False)
        other_bank = self.seed["bank"].pk + 999
        text = self.client.get(reverse("fees_feebook") + f"?fy=&bank={other_bank}").content.decode()
        self.assertNotIn('name="bank"', text)
        self.assertNotIn('<th scope="col">Bank</th>', text)
        self.assertNotIn("HDFC Current", text)
        self.assertIn("Alpha payer", text)   # the bank in the link was ignored, so the payments still show
        self.assertNotIn("bank_account_id", feebook_filters({"bank": "5"}, with_bank=False))

    def test_payment_form_has_no_bank_box_and_editing_keeps_the_stored_bank(self):
        payment_id = self.seed["single"]["id"]
        bank_id = Payment.objects.get(pk=payment_id).bank_account_id
        self.assertIsNotNone(bank_id)
        _switch(self.profile, show_bank=False)
        form = self.client.get(reverse("fees_payment_edit", args=[payment_id])).content.decode()
        self.assertNotIn('name="bank_account_id"', form)
        settings_page = self.client.get(reverse("fees_settings") + "?tab=payments").content.decode()
        self.assertNotIn("Bank accounts</h3>", settings_page)
        self.assertIn('name="show_bank"', settings_page)   # the switch itself stays, so it can be turned back on
        post = self.payment_post(amount="9000", payee="Alpha payer edited", date_of_payment="2026-08-01", bank_account_id="",
                                 alloc_memo_0=self.seed["memo_a"].memo_number)
        self.post("fees_payment_edit", post, kwargs={"payment_id": payment_id})
        payment = Payment.objects.get(pk=payment_id)
        self.assertEqual(payment.payee, "Alpha payer edited")
        self.assertEqual(payment.bank_account_id, bank_id)

    def test_a_new_payment_saves_without_a_bank_when_off(self):
        _switch(self.profile, show_bank=False)
        self.post("fees_payment_new", self.payment_post(bank_account_id=str(self.seed["bank"].pk)))
        self.assertIsNone(Payment.objects.get(profile=self.profile, payee="Typed payee").bank_account_id)
