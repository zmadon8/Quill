"""Per-kind choice of logging corporate actions automatically or asking for approval (Settings > Investments > General)."""
from datetime import date as d, timedelta
from decimal import Decimal as D

from django.urls import reverse

from investments.models import CorporateActionResponse, Dividend, DividendSignal, InvestmentSettings
from investments.services import core, corporate, dividends, holdings, masters
from investments.tests.base import InvTestCase


class CorporateAutoTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.buy(d(2023, 1, 1), 10, 1000)
        self.client.force_login(self.user)

    def post(self, name, data):
        return self.client.post(reverse(name), data)

    def switch(self, **kinds):
        masters.update_settings(self.profile, self.user, corporate_auto=kinds)

    def record_split(self):
        return corporate.record(None, None, instrument=self.reliance, ex_date=d(2024, 1, 1), kind="split", ratio_old=1, ratio_new=5, detected=True)

    def test_default_is_ask_for_every_kind(self):
        row = core.get_settings(self.profile)
        self.assertEqual(row.corporate_auto, {})
        for kind in ("dividend", "split", "bonus", "demerger", "other"):
            self.assertFalse(corporate.auto_apply(self.profile, kind))

    def test_split_waits_for_approval_when_off(self):
        action = self.record_split()
        self.assertFalse(CorporateActionResponse.objects.filter(profile=self.profile, action=action).exists())
        self.assertEqual([a.pk for a in corporate.pending(self.profile)], [action.pk])

    def test_split_is_applied_without_a_click_when_on(self):
        self.switch(split=True)
        action = self.record_split()
        response = CorporateActionResponse.objects.get(profile=self.profile, action=action)
        self.assertEqual(response.status, corporate.STATUS_APPLIED)
        self.assertEqual(corporate.pending(self.profile), [])
        rows, _totals = holdings.compute(self.profile, as_of=d(2024, 6, 1))
        self.assertEqual(rows[0].units, D(50))

    def test_other_kinds_stay_pending_when_only_split_is_on(self):
        self.switch(split=True)
        bonus = corporate.record(None, None, instrument=self.reliance, ex_date=d(2024, 5, 1), kind="bonus", ratio_old=2, ratio_new=1)
        self.assertEqual([a.pk for a in corporate.pending(self.profile)], [bonus.pk])

    def test_switching_on_applies_what_is_already_pending(self):
        action = self.record_split()
        self.switch(split=True)
        corporate.apply_automatic(self.profile)
        self.assertTrue(CorporateActionResponse.objects.filter(profile=self.profile, action=action, status=corporate.STATUS_APPLIED).exists())

    def test_incomplete_other_action_is_applied_but_marked_not_applicable_is_left(self):
        self.switch(other=True)
        action = corporate.record(None, None, instrument=self.reliance, ex_date=d(2024, 3, 1), kind="other", notes="Merger")
        self.assertTrue(CorporateActionResponse.objects.filter(profile=self.profile, action=action, status=corporate.STATUS_APPLIED).exists())

    def test_settings_form_saves_the_choices(self):
        masters.ensure_builtin_indices()
        r = self.post("investments_settings", {
            "sip_mode": "final", "awaiting_treatment": "leave_out", "awaiting_reminder_days": "10", "corporate_action_mode": "tag",
            "long_term_days": "365", "alt_treatment": "averaged", "default_index": "",
            "auto_dividend": "auto", "auto_split": "auto", "auto_bonus": "ask", "auto_demerger": "ask", "auto_other": "ask"})
        self.assertRedirects(r, reverse("investments_settings"))
        row = InvestmentSettings.objects.get(profile=self.profile)
        self.assertEqual(row.corporate_auto, {"dividend": True, "split": True, "bonus": False, "demerger": False, "other": False})
        self.assertContains(self.client.get(reverse("investments_settings")), "Log automatically")


class DividendAutoTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.buy(d.today() - timedelta(days=200), 10, 1000)
        self.signal = DividendSignal.objects.create(instrument=self.reliance, ex_date=d.today() - timedelta(days=10), per_unit=D("2.5"))

    def test_stays_a_suggestion_when_off(self):
        self.assertEqual(dividends.auto_log(self.profile), [])
        self.assertFalse(Dividend.objects.filter(profile=self.profile).exists())
        self.assertEqual(len(dividends.due(self.profile)), 1)

    def test_logged_once_when_on(self):
        masters.update_settings(self.profile, self.user, corporate_auto={"dividend": True})
        made = dividends.auto_log(self.profile)
        self.assertEqual([(m.amount, m.date) for m in made], [(D("25.00"), self.signal.ex_date)])
        self.assertEqual(dividends.due(self.profile), [])
        made[0].delete()
        self.assertEqual(dividends.auto_log(self.profile), [])

    def test_skips_a_dividend_already_recorded(self):
        masters.update_settings(self.profile, self.user, corporate_auto={"dividend": True})
        dividends.add(self.profile, self.user, date=self.signal.ex_date + timedelta(days=2), instrument=self.reliance, portfolio=self.portfolio,
                      broker=self.zerodha, amount="25")
        self.assertEqual(dividends.auto_log(self.profile), [])
        self.assertEqual(Dividend.objects.filter(profile=self.profile).count(), 1)
