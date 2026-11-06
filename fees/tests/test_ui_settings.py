"""Settings screen (T8.8): every section renders, Reader and Editor see different controls."""
from django.urls import reverse

from fees.tests.test_ui_pages import UiPageBase


class SettingsScreenTests(UiPageBase):
    def settings_text(self, user):
        return self.assert_page(self.page("fees_settings", user=user), "settings")

    def test_every_section_renders_for_an_editor(self):
        text = self.settings_text(self.editor)
        for heading in ("Default Fees", "Payments", "Memo Text Defaults", "Word memo file names", "Start Years",
                        "Statistics", "Display", "Word template", "Danger zone"):
            self.assertIn(">%s</h2>" % heading, text, heading)
        for tab in ("defaults", "years", "data", "other"):
            self.assertIn('data-settings-tab="%s"' % tab, text, tab)
        self.assertIn("Bank accounts</h3>", text)
        self.assertIn("You have unsaved changes.", text)
        for name in ("export_owner_name", "memo_filename_pattern", "memo_default_name", "memo_default_designation",
                     "memo_default_pan", "initial_financial_year", "memos_start_year", "feebook_start_year",
                     "statistics_enabled", "dashboard_kpis_enabled"):
            self.assertIn('name="%s"' % name, text, name)
        self.assertIn('<textarea name="memo_default_address"', text)
        self.assertIn('<textarea name="default_court_name"', text)
        self.assertIn("Caption <textarea", text)
        self.assertNotIn("default_additional_details_left", text)
        self.assertNotIn("default_additional_details_right", text)
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


class SettingsRound2Tests(UiPageBase):
    def test_tag_download_link_and_builder_markup(self):
        text = self.settings_text(self.editor)
        self.assertIn(reverse("fees_template_tags_download"), text)
        self.assertIn("Download list of template tags (.docx)", text)
        self.assertIn("data-filename-builder", text)
        self.assertIn("data-preset=", text)
        self.assertIn("data-insert=", text)
        self.assertIn("js/fees/filename-builder.js", text)

    def settings_text(self, user):
        return self.assert_page(self.page("fees_settings", user=user), "settings")

    def test_signature_checkbox_only_with_a_signature(self):
        from fees.models import WordTemplate
        self.assertIn('name="memo_signature_default"', self.settings_text(self.editor))
        WordTemplate.objects.filter(profile=self.profile).update(signature_data=None, signature_filename="")
        text = self.settings_text(self.editor)
        self.assertNotIn('name="memo_signature_default"', text)
        self.assertIn("Upload a signature image in the Word template box to use this.", text)

    def test_filename_presets_are_valid_patterns(self):
        from fees.exports.filenames import validate_pattern
        from fees.views_settings import FILENAME_PARTS, FILENAME_PRESETS
        for preset in FILENAME_PRESETS:
            self.assertEqual(validate_pattern(preset["pattern"]), [], preset["label"])
        for part in FILENAME_PARTS:
            self.assertEqual(validate_pattern(part["text"].replace("[]", "[{fy}]")), [], part["label"])

    def test_saving_does_not_blank_the_removed_details_fields(self):
        from fees.models import FeesSettings
        FeesSettings.objects.update_or_create(
            profile=self.profile,
            defaults={"default_additional_details_left": "keep left", "default_additional_details_right": "keep right"},
        )
        self.login(self.editor)
        response = self.client.post(reverse("fees_settings"), {"default_court_name": "Caption\nLine 2", "overdue_days": "30"})
        self.assertEqual(response.status_code, 302)
        row = FeesSettings.objects.get(profile=self.profile)
        self.assertEqual(row.default_additional_details_left, "keep left")
        self.assertEqual(row.default_additional_details_right, "keep right")
        self.assertEqual(row.default_court_name, "Caption\nLine 2")
