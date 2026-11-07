"""Settings screen (T8.8): every section renders, Reader and Editor see different controls."""
from django.urls import reverse

from fees.tests.test_ui_pages import UiPageBase


class SettingsScreenTests(UiPageBase):
    def settings_text(self, user):
        return self.assert_page(self.page("fees_settings", user=user), "settings")

    def test_every_section_renders_for_an_editor(self):
        text = self.settings_text(self.editor)
        self.assertNotIn(">Danger zone</h3>", text)  # restore, import and clear-all are Admin only
        text = self.settings_text(self.admin)
        for heading in ("Memos", "Payments", "Word documents", "Years and statistics", "Display", "Data",
                        "Word template", "Edit Statistics"):
            self.assertIn(">%s</h2>" % heading, text, heading)
        for heading in ("Default fees", "Memo text defaults", "Danger zone"):
            self.assertIn(">%s</h3>" % heading, text, heading)
        for key in ("memos", "payments", "word", "years", "display", "data"):
            self.assertIn('data-section="%s"' % key, text, key)
            self.assertIn('data-section-link="%s"' % key, text, key)
        self.assertIn("1 Memos</a>", text)
        self.assertIn("6 Data</a>", text)
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

    def test_each_section_is_its_own_form_with_its_own_save_and_warning(self):
        text = self.settings_text(self.editor)
        self.assertEqual(text.count("data-section-form"), 5)  # Data has no settings form, only downloads
        self.assertEqual(text.count("You have unsaved changes."), 5)
        for key in ("memos", "payments", "word", "years", "display"):
            self.assertIn('<input type="hidden" name="tab" value="%s">' % key, text, key)
        self.assertIn("js/settings-sections.js", text)

    def test_every_setting_has_a_help_line_and_a_who_tag(self):
        text = self.settings_text(self.editor)
        self.assertGreaterEqual(text.count('class="setting-row"'), 25)
        self.assertGreaterEqual(text.count("Everyone in this profile"), 25)
        self.assertNotIn('class="who-tag who-you"', text)  # nothing here is personal: that is on My settings
        for row in text.split('class="setting-row"')[1:]:
            self.assertIn("setting-help", row.split("</div>")[0], row[:80])

    def test_opening_page_and_items_per_page_use_the_shared_names(self):
        text = self.settings_text(self.editor)
        self.assertIn("Opening page <select", text)
        self.assertIn("Items per page <input", text)
        self.assertIn(reverse("my_settings") + "?tab=fees", text)

    def test_signature_upload_sits_in_the_word_template_box(self):
        text = self.settings_text(self.editor)
        start = text.index('<section class="settings-box')  # the box also carries the settings-card class
        box = text[start:text.index("</section>", start)]
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
        self.assertNotIn(">Save</button>", text)
        self.assertNotIn("You have unsaved changes.", text)
        self.assertIn("<fieldset class=\"section-fields\" disabled>", text)
        for url in ("fees_template_upload", "fees_signature_upload", "fees_bank_account_add", "fees_backup", "fees_import"):
            self.assertNotIn('"%s"' % reverse(url), text, url)

    def test_a_reader_cannot_save_a_section(self):
        self.login(self.reader)
        for tab in ("memos", "display"):
            response = self.client.post(reverse("fees_settings"), {"tab": tab, "overdue_days": "99"})
            self.assertEqual(response.status_code, 403, tab)
        from fees.models import FeesSettings
        self.assertNotEqual(FeesSettings.objects.get(profile=self.profile).overdue_days, 99)

    def test_saving_a_section_returns_to_it_and_changes_only_its_fields(self):
        from fees.models import FeesSettings
        before = FeesSettings.objects.get(profile=self.profile)
        self.login(self.editor)
        response = self.client.post(reverse("fees_settings"), {"tab": "payments", "overdue_days": "77"})
        self.assertRedirects(response, reverse("fees_settings") + "?tab=payments", fetch_redirect_response=False)
        after = FeesSettings.objects.get(profile=self.profile)
        self.assertEqual(after.overdue_days, 77)
        self.assertEqual(after.default_court_name, before.default_court_name)
        self.assertEqual(after.items_per_page, before.items_per_page)

    def test_a_failed_save_shows_the_error_and_keeps_the_section(self):
        self.login(self.editor)
        response = self.client.post(reverse("fees_settings"), {"tab": "payments", "overdue_days": "many"})
        self.assertEqual(response.status_code, 422)
        self.assertIn('data-initial="payments"', response.content.decode())

    def test_editor_sees_save_backup_and_import_is_admin_only(self):
        text = self.settings_text(self.editor)
        self.assertIn(">Save</button>", text)
        self.assertIn(reverse("fees_backup"), text)
        self.assertIn(reverse("fees_backup_download"), text)
        self.assertIn(reverse("fees_bank_account_add"), text)
        # Import and clear-all are for the Admin only, so an Editor does not see those controls.
        self.assertNotIn('"%s"' % reverse("fees_import"), text)
        self.assertNotIn("Clear All Data", text)
        self.assertNotIn("red-box", text)

    def test_admin_sees_import_and_clear_all_in_a_red_box_at_the_bottom_of_data(self):
        text = self.settings_text(self.admin)
        self.assertIn(reverse("fees_import"), text)
        self.assertIn("Clear All Data", text)
        data = text.split('data-section="data"')[1]
        self.assertIn('class="red-box danger-zone"', data)
        self.assertLess(data.index("Download an Excel backup"), data.index("red-box"))

    def test_reader_cannot_open_backup_or_import(self):
        for name in ("fees_backup", "fees_import"):
            self.assertEqual(self.page(name).status_code, 403, name)
        self.assertEqual(self.page("fees_backup", user=self.editor).status_code, 200)
        self.assertEqual(self.page("fees_import", user=self.editor).status_code, 403)
        self.assertEqual(self.page("fees_import", user=self.admin).status_code, 200)

    def test_editor_backup_page_has_the_download_but_no_restore_or_clear(self):
        text = self.html(self.page("fees_backup", user=self.editor))
        self.assertIn(reverse("fees_backup_download"), text)
        self.assertNotIn('"%s"' % reverse("fees_backup_restore"), text)
        self.assertNotIn('"%s"' % reverse("fees_backup_clear"), text)


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
