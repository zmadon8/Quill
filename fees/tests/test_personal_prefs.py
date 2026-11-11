"""Fee Register Opening page and Items per page are personal (My settings): per user, falling back to the profile's
value and then the standard one. Stored in FeesUserPrefs under the key ``settings`` (no migration)."""
from django.test import override_settings
from django.urls import reverse

from fees.errors import FeesError
from fees.models import FeesSettings, FeesUserPrefs
from fees.services import prefs
from fees.tests.test_views_read import SeededViewsBase


class PersonalServiceTests(SeededViewsBase):
    def test_fallback_chain_user_then_profile_then_default(self):
        FeesSettings.objects.update_or_create(
            profile=self.profile, defaults={"default_tab": "outstanding", "items_per_page": 25}
        )
        config = FeesSettings.objects.get(profile=self.profile)
        self.assertEqual(prefs.personal_default_tab(self.profile, self.editor, config), "outstanding")
        self.assertEqual(prefs.personal_items_per_page(self.profile, self.editor, config), 25)
        prefs.set_personal(self.profile, self.editor, {"default_tab": "dashboard", "items_per_page": 0})
        self.assertEqual(prefs.personal_default_tab(self.profile, self.editor, config), "dashboard")
        self.assertEqual(prefs.personal_items_per_page(self.profile, self.editor, config), 0)  # 0 is All
        # Nothing at all: the standard values.
        self.assertEqual(prefs.personal_default_tab(self.profile, self.reader, None), "memos")
        self.assertEqual(prefs.personal_items_per_page(self.profile, self.reader, None), 50)

    def test_another_users_choice_does_not_affect_you(self):
        prefs.set_personal(self.profile, self.editor, {"default_tab": "dashboard", "items_per_page": 5})
        config = FeesSettings.objects.get(profile=self.profile)
        self.assertEqual(prefs.get_personal(self.profile, self.reader), {})
        self.assertEqual(prefs.personal_default_tab(self.profile, self.reader, config), config.default_tab)
        self.assertEqual(prefs.personal_items_per_page(self.profile, self.reader, config), config.items_per_page)

    def test_a_none_removes_the_choice_so_the_profile_value_applies_again(self):
        prefs.set_personal(self.profile, self.editor, {"default_tab": "dashboard", "items_per_page": 5})
        stored = prefs.set_personal(self.profile, self.editor, {"default_tab": None})
        self.assertEqual(stored, {"items_per_page": 5})

    def test_bad_values_are_refused_and_nothing_is_stored(self):
        for data in ({"default_tab": "nowhere"}, {"items_per_page": "lots"}, {"items_per_page": 5000}):
            with self.assertRaises(FeesError):
                prefs.set_personal(self.profile, self.editor, data)
        self.assertFalse(FeesUserPrefs.objects.filter(user=self.editor, key=prefs.SETTINGS_KEY).exists())

    def test_saving_is_not_memo_data_and_the_row_is_private_to_the_profile(self):
        before = FeesSettings.objects.get(profile=self.profile).data_version
        prefs.set_personal(self.profile, self.editor, {"items_per_page": 10})
        self.assertEqual(FeesSettings.objects.get(profile=self.profile).data_version, before)
        self.assertEqual(prefs.get_personal(self.other_profile, self.editor), {})

    def test_the_prefs_endpoint_cannot_write_this_key(self):
        with self.assertRaises(FeesError):
            prefs.set_pref(self.profile, self.editor, prefs.SETTINGS_KEY, {"default_tab": "memos"})


class PersonalViewsTests(SeededViewsBase):
    def test_landing_follows_my_choice_not_the_profile_and_not_another_user(self):
        # The seed sets the profile's default_tab to "firms".
        prefs.set_personal(self.profile, self.editor, {"default_tab": "outstanding"})
        self.login(self.editor)
        self.assertRedirects(self.client.get(reverse("fees_landing")), reverse("fees_outstanding"),
                             fetch_redirect_response=False)
        self.login(self.reader)
        self.assertRedirects(self.client.get(reverse("fees_landing")), reverse("fees_firms"),
                             fetch_redirect_response=False)

    def test_memo_list_page_size_is_mine(self):
        prefs.set_personal(self.profile, self.editor, {"items_per_page": 1})
        self.login(self.editor)
        mine = len(self.client.get(reverse("fees_memos"), {"fy": ""}).context["items"])
        self.assertEqual(mine, 1)
        self.login(self.reader)
        theirs = len(self.client.get(reverse("fees_memos"), {"fy": ""}).context["items"])
        self.assertGreaterEqual(theirs, mine)


class MySettingsFeesSectionTests(SeededViewsBase):
    def post(self, user, data, tab="fees"):
        self.login(user)
        return self.client.post(reverse("my_settings"), {"tab": tab, **data})

    def start(self):
        return self.client.get(reverse("my_settings"), {"tab": "start"}).content.decode()

    def display(self):
        return self.client.get(reverse("fees_settings"), {"tab": "display"}).content.decode()

    def test_the_choices_are_there_for_a_fee_register_user_and_tagged_only_you(self):
        self.login(self.reader)
        html = self.start()
        self.assertIn('data-section="fees"', html)
        section = html.split('data-section="fees"')[1]
        self.assertIn('name="fees-default_tab"', section)
        self.assertNotIn('name="fees-items_per_page"', section)  # Items per page is on the Fee Register settings page
        self.assertIn(">Opening page</label>", section)
        self.assertIn("Only you", section)
        page = self.display()
        self.assertIn('name="fees-items_per_page"', page)
        self.assertIn("My items per page", page)
        self.assertNotIn('name="fees-default_tab"', page)  # Opening page is on Start Screens

    @override_settings(FEES_ENABLED=False)
    def test_the_section_is_hidden_when_the_fee_register_is_switched_off(self):
        self.login(self.reader)
        html = self.start()
        self.assertNotIn('data-section="fees"', html)
        self.assertNotIn(reverse("fees_settings"), html)

    def test_a_user_without_a_fee_register_profile_has_no_section(self):
        self.login(self.outsider)
        self.assertNotIn('data-section="fees"', self.start())

    def test_a_reader_may_save_their_own_choices(self):
        resp = self.post(self.reader, {"fees-default_tab": "dashboard", "fees-items_per_page": "All"})
        self.assertRedirects(resp, reverse("fees_settings") + "?tab=display", fetch_redirect_response=False)
        self.assertEqual(prefs.get_personal(self.profile, self.reader), {"default_tab": "dashboard", "items_per_page": 0})
        self.assertEqual(prefs.get_personal(self.profile, self.editor), {})
        # The profile's own values are not changed by a personal save.
        config = FeesSettings.objects.get(profile=self.profile)
        self.assertEqual(config.default_tab, "firms")

    def test_the_opening_page_is_saved_from_start_screens_and_keeps_items_per_page(self):
        self.post(self.editor, {"fees-items_per_page": "10"})
        resp = self.post(self.editor, {"fees-default_tab": "feebook"}, tab="start")
        self.assertRedirects(resp, reverse("my_settings") + "?tab=start", fetch_redirect_response=False)
        self.assertEqual(prefs.get_personal(self.profile, self.editor), {"default_tab": "feebook", "items_per_page": 10})
        self.post(self.editor, {"fees-items_per_page": "20"})  # not posted: the opening page stays
        self.assertEqual(prefs.get_personal(self.profile, self.editor), {"default_tab": "feebook", "items_per_page": 20})

    def test_blank_boxes_go_back_to_the_profile_value(self):
        self.post(self.editor, {"fees-default_tab": "dashboard", "fees-items_per_page": "10"})
        self.post(self.editor, {"fees-default_tab": "", "fees-items_per_page": ""})
        self.assertEqual(prefs.get_personal(self.profile, self.editor), {})

    def test_a_bad_value_is_refused_with_a_message(self):
        resp = self.post(self.editor, {"fees-items_per_page": "many"})
        self.assertRedirects(resp, reverse("fees_settings") + "?tab=display", fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("fees_settings"), {"tab": "display"}), "Items per page must be a whole number")
        self.assertEqual(prefs.get_personal(self.profile, self.editor), {})

    def test_saving_this_section_leaves_the_other_sections_alone(self):
        self.editor.justify_text = True
        self.editor.save()
        self.post(self.editor, {"fees-default_tab": "memos", "fees-items_per_page": "20"})
        self.editor.refresh_from_db()
        self.assertTrue(self.editor.justify_text)

    def test_the_forms_show_what_is_saved(self):
        self.post(self.editor, {"fees-default_tab": "feebook", "fees-items_per_page": "20"})
        self.assertIn('<option value="feebook" selected>', self.start())
        self.assertIn('value="20"', self.display())
