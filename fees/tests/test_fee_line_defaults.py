"""Owner round 2026-11: Settings > Memos has one "on in a new memo" switch per fee line (Appearances, Conferences, Drafts / Misc)
instead of the single "Fee lines on by default"."""
from django.test import override_settings
from django.urls import reverse

from fees.models import FeesSettings
from fees.services import excel_backup
from fees.services import settings as settings_service
from fees.services.excel_restore import RESTORE_CONFIRMATION, restore_workbook
from fees.tests import xlsx_support as xs
from fees.tests.test_excel_restore import fees_profile, minimal_sheets
from fees.tests.test_views_write import WriteBase

KEYS = ("default_line_appearances", "default_line_conferences", "default_line_misc")


@override_settings(SECURE_SSL_REDIRECT=False, FEES_ENABLED=True)
class FeeLineDefaultsTests(WriteBase):
    def test_three_switches_replace_the_single_one(self):
        page = self.client.get(reverse("fees_settings") + "?tab=memos").content.decode()
        self.assertNotIn("Fee lines on by default", page)
        self.assertNotIn('name="default_lines_enabled"', page)
        for key, label in zip(KEYS, ("Appearances", "Conferences", "Drafts / Misc")):
            self.assertIn(f'name="{key}" value="1" checked> {label}', page)

    def test_saving_one_line_off(self):
        self.post("fees_settings", {"tab": "memos", "default_line_appearances": ["0", "1"], "default_line_conferences": "0",
                                    "default_line_misc": ["0", "1"]})
        row = FeesSettings.objects.get(profile=self.profile)
        self.assertEqual((row.default_line_appearances, row.default_line_conferences, row.default_line_misc), (True, False, True))
        self.assertTrue(row.default_lines_enabled)             # the desktop file's switch: on while any line is on
        form = self.client.get(reverse("fees_memo_new")).content.decode()
        self.assertIn('data-line-default-appearances="1"', form)
        self.assertIn('data-line-default-conferences="0"', form)
        self.assertIn('data-line-default-misc="1"', form)
        settings_service.update_settings(self.profile, {k: False for k in KEYS})
        self.assertFalse(FeesSettings.objects.get(profile=self.profile).default_lines_enabled)


class FeeLineDefaultsBackupTests(WriteBase):
    def test_in_the_backup_and_an_older_file_follows_the_single_switch(self):
        for key in KEYS:
            self.assertIn(key, excel_backup.WEB_SETTINGS_KEYS)
        profile = fees_profile("Lines-New")
        sheets = minimal_sheets(0)
        sheets["WebSettings"] = [["key", "value"], ["default_line_conferences", 0]]
        restore_workbook(profile, xs.build_workbook(sheets), RESTORE_CONFIRMATION, backup_func=xs.no_backup)
        row = FeesSettings.objects.get(profile=profile)
        self.assertFalse(row.default_line_conferences)
        self.assertEqual((row.default_line_appearances, row.default_line_misc), (row.default_lines_enabled, row.default_lines_enabled))
