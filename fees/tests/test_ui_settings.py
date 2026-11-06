"""Settings screen (T8.8): every section renders, Reader and Editor see different controls."""
from django.urls import reverse

from fees.tests.test_ui_pages import UiPageBase


class SettingsScreenTests(UiPageBase):
    def settings_text(self, user):
        return self.assert_page(self.page("fees_settings", user=user), "settings")

    def test_every_section_renders_for_an_editor(self):
        text = self.settings_text(self.editor)
        for legend in ("Memo defaults", "Payments and reminders", "Display", "Word memo file names", "Memo text defaults"):
            self.assertIn("<legend>%s</legend>" % legend, text, legend)
        for heading in ("Word template", "Bank accounts"):
            self.assertIn(">%s</h2>" % heading, text, heading)
        for name in ("export_owner_name", "memo_filename_pattern", "memo_default_name", "memo_default_designation",
                     "memo_default_pan", "initial_financial_year", "memos_start_year", "feebook_start_year",
                     "statistics_enabled", "dashboard_kpis_enabled"):
            self.assertIn('name="%s"' % name, text, name)
        self.assertIn('<textarea name="memo_default_address"', text)
        self.assertIn('<textarea name="memo_default_bank_details"', text)

    def test_signature_upload_sits_in_the_word_template_box(self):
        text = self.settings_text(self.editor)
        box = text[text.index('<section class="settings-box"'):text.index("</section>")]
        self.assertIn(reverse("fees_template_upload"), box)
        self.assertIn(reverse("fees_signature_upload"), box)
        self.assertIn(reverse("fees_template_download"), box)
        self.assertIn(reverse("fees_signature_download"), box)

    def test_filename_preview_is_progressive(self):
        text = self.settings_text(self.reader)
        self.assertIn("js/fees/filename-preview.js", text)
        self.assertIn("data-filename-pattern", text)
        self.assertIn(reverse("fees_filename_preview") + "?pattern=", text)  # works without JavaScript

    def test_reader_sees_values_but_no_editing_controls(self):
        text = self.settings_text(self.reader)
        self.assertIn("You can read the settings but not change them.", text)
        self.assertNotIn("Save settings", text)
        for url in ("fees_template_upload", "fees_signature_upload", "fees_bank_account_add", "fees_backup", "fees_import"):
            self.assertNotIn('"%s"' % reverse(url), text, url)

    def test_editor_sees_save_backup_and_import(self):
        text = self.settings_text(self.editor)
        self.assertIn("Save settings", text)
        self.assertIn(reverse("fees_backup"), text)
        self.assertIn(reverse("fees_import"), text)
        self.assertIn(reverse("fees_bank_account_add"), text)

    def test_reader_cannot_open_backup_or_import(self):
        for name in ("fees_backup", "fees_import"):
            self.assertEqual(self.page(name).status_code, 403, name)
            self.assertEqual(self.page(name, user=self.editor).status_code, 200, name)
