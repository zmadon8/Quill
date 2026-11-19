"""Owner round (2027-01): the Written Off feature can be switched off in Settings (per profile, Editors).

Off: no Write Off button, "Include Written Off Memos" tick, Written Off legend key or Year End written-off line shows, and a
memo written off earlier counts as unpaid and outstanding (Memos, Outstanding, the payment form, the dashboard, the ledger).
Nothing is deleted: the flag stays on the memo, so turning the switch back on restores the write-offs. On by default.
"""
from django.test import override_settings
from django.urls import reverse

from fees.models import FeesSettings, Memo
from fees.services import excel_backup, ledger, memo_lists, outstanding
from fees.services import settings as settings_service
from fees.services.dashboard import get_dashboard_summary
from fees.services.excel_restore import RESTORE_CONFIRMATION, restore_workbook
from fees.tests import xlsx_support as xs
from fees.tests.test_excel_restore import fees_profile, minimal_sheets
from fees.tests.test_views_write import WriteBase


def _switch(profile, on):
    settings_service.update_settings(profile, {"written_off_enabled": on})


@override_settings(SECURE_SSL_REDIRECT=False, FEES_ENABLED=True)
class WrittenOffSwitchTests(WriteBase):
    def setUp(self):
        super().setUp()
        xs.status_dots_on(self.profile)
        self.memo = Memo.objects.get(pk=self.seed["memo_c"].pk)  # written off by the seed
        self.assertTrue(self.memo.written_off)

    def get(self, name, query="", **kwargs):
        return self.client.get(reverse(name, kwargs=kwargs) + query)

    def outstanding_ids(self):
        groups = outstanding.list_outstanding(self.profile, {})
        return {e["memo_id"] for g in groups for e in g["entries"]}

    def test_on_by_default_and_saved_from_the_settings_page(self):
        self.assertTrue(settings_service.get_settings(self.profile)["written_off_enabled"])
        page = self.get("fees_settings", "?tab=payments")
        self.assertContains(page, 'name="written_off_enabled"')
        self.assertContains(page, "Written off memos")
        self.post("fees_settings", {"tab": "payments", "written_off_enabled": "0"})
        self.assertFalse(FeesSettings.objects.get(profile=self.profile).written_off_enabled)
        self.post("fees_settings", {"tab": "payments", "written_off_enabled": ["0", "1"]})
        self.assertTrue(FeesSettings.objects.get(profile=self.profile).written_off_enabled)

    def test_changing_the_switch_bumps_the_data_version(self):
        before = settings_service.get_settings(self.profile)["data_version"]
        _switch(self.profile, False)
        self.assertGreater(settings_service.get_settings(self.profile)["data_version"], before)

    def test_on_shows_the_write_off_controls_and_the_written_off_status(self):
        detail = self.get("fees_memo_detail", memo_id=self.memo.pk)
        self.assertContains(detail, "Remove The Write-off")
        self.assertContains(self.get("fees_outstanding"), "Include Written Off Memos")
        self.assertContains(self.get("fees_memos", "?fy="), "Written Off</span></span>")  # the last item of the one-line status key
        self.assertContains(self.get("fees_memos", "?fy="), "status-written-off")
        self.assertContains(self.get("fees_statistics_year_end", f"?fy={self.memo.financial_year}"), "Written off")
        self.assertNotIn(self.memo.pk, self.outstanding_ids())

    def test_off_a_written_off_memo_is_unpaid_outstanding_and_payable_and_no_control_shows(self):
        _switch(self.profile, False)
        item = next(i for i in memo_lists.list_memos(self.profile) if i["id"] == self.memo.pk)
        self.assertEqual(item["status"], "Unpaid")
        self.assertFalse(item["written_off"])
        self.assertIn(self.memo.pk, self.outstanding_ids())
        self.assertTrue(
            Memo.objects.get(pk=self.memo.pk).written_off, "nothing is deleted: the flag stays on the memo"
        )

        memos_page = self.get("fees_memos", "?fy=")
        self.assertNotContains(memos_page, "status-written-off")
        self.assertNotContains(memos_page, "Written Off</span>")
        detail = self.get("fees_memo_detail", memo_id=self.memo.pk)
        self.assertNotContains(detail, "Remove The Write-off")
        self.assertNotContains(detail, "Write Off As A Bad Debt")
        self.assertNotContains(detail, "status-written-off")
        for name in ("fees_outstanding", "fees_outstanding_detail"):
            self.assertNotContains(self.get(name), "Include Written Off Memos")
        self.assertContains(self.get("fees_outstanding_detail"), self.memo.memo_number)
        self.assertNotContains(self.get("fees_statistics_year_end", f"?fy={self.memo.financial_year}"), "Written off")

        form = self.get("fees_payment_new")
        self.assertContains(form, '<option value="%s"' % self.memo.memo_number)

    def test_off_a_write_off_cannot_be_made_and_the_ledger_and_dashboard_ignore_it(self):
        _switch(self.profile, False)
        response = self.post("fees_memo_write_off", {"written_off": "0"}, {"memo_id": self.memo.pk})
        self.assertNotEqual(response.status_code, 500)
        self.assertTrue(Memo.objects.get(pk=self.memo.pk).written_off)
        self.assertFalse(any("(written off)" in str(e) for e in ledger.build_ledger(self.profile)))
        statement = ledger.build_statement(self.profile)
        self.assertFalse(any(row["status"] == "Written Off" for row in statement["rows"]))
        self.assertEqual(get_dashboard_summary(self.profile)["written_off_total"], 0)

    def test_the_payment_form_leaves_a_written_off_memo_out_while_on(self):
        self.assertNotContains(self.get("fees_payment_new"), '<option value="%s"' % self.memo.memo_number)

    def test_turning_it_back_on_restores_the_write_offs(self):
        _switch(self.profile, False)
        _switch(self.profile, True)
        self.assertNotIn(self.memo.pk, self.outstanding_ids())
        item = next(i for i in memo_lists.list_memos(self.profile) if i["id"] == self.memo.pk)
        self.assertTrue(item["written_off"])
        self.assertContains(self.get("fees_memos", "?fy="), "status-written-off")
        self.assertContains(self.get("fees_memo_detail", memo_id=self.memo.pk), "Remove The Write-off")


class WrittenOffBackupTests(WriteBase):
    def test_the_switch_is_in_the_backup_and_round_trips(self):
        self.assertIn("written_off_enabled", excel_backup.WEB_SETTINGS_KEYS)
        profile = fees_profile("WO-Off")
        sheets = minimal_sheets(0)
        sheets["WebSettings"] = [["key", "value"], ["written_off_enabled", 0]]
        restore_workbook(profile, xs.build_workbook(sheets), RESTORE_CONFIRMATION, backup_func=xs.no_backup)
        self.assertFalse(FeesSettings.objects.get(profile=profile).written_off_enabled)

    def test_an_old_backup_without_the_key_keeps_it_on(self):
        profile = fees_profile("WO-Old")
        _switch(profile, False)
        sheets = minimal_sheets(0)
        sheets["WebSettings"] = [["key", "value"], ["statistics_enabled", 1]]
        restore_workbook(profile, xs.build_workbook(sheets), RESTORE_CONFIRMATION, backup_func=xs.no_backup)
        self.assertTrue(FeesSettings.objects.get(profile=profile).written_off_enabled)
