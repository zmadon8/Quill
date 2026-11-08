"""Round 9, item 2: Profile.display_name (header brand, page title, Home button, settings, Admin screen)."""
from django.test import override_settings
from django.urls import reverse

from accounts.models import Profile
from accounts.profiles import ensure_default_profile
from accounts.tests.test_accounts import BaseCase


@override_settings(SECURE_SSL_REDIRECT=False)
class DisplayNameTests(BaseCase):
    def main(self):
        return Profile.objects.get(pk=ensure_default_profile().pk)

    def set_name(self, value):
        Profile.objects.filter(pk=self.main().pk).update(display_name=value)

    def test_blank_by_default_and_the_header_keeps_program_and_profile_name(self):
        self.assertEqual(self.main().display_name, "")
        self.client.force_login(self.user)
        resp = self.client.get(reverse("diary_home"))
        self.assertContains(resp, 'class="profile-name">&middot; Main</span>')
        self.assertContains(resp, "<title>Home - Case Law Diary</title>")

    def test_display_name_replaces_the_header_brand_title_and_aria_label(self):
        self.set_name("Madon's Case Law")
        self.client.force_login(self.user)
        for name in ("diary_home", "flags"):  # the Diary settings tab uses the Home header (D93)
            resp = self.client.get(reverse(name))
            self.assertContains(resp, 'aria-label="Madon&#x27;s Case Law: Home">Madon&#x27;s Case Law</a>', msg_prefix=name)
            self.assertNotContains(resp, 'class="profile-name"', msg_prefix=name)
            self.assertNotContains(resp, "Case Law Diary: Home", msg_prefix=name)
        self.assertContains(self.client.get(reverse("diary_home")), "<title>Home - Madon&#x27;s Case Law</title>")

    def test_header_brand_still_links_to_the_program_index(self):
        self.set_name("Mine")
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("flags")), 'href="%s" title="Mine" aria-label="Mine: Home"' % reverse("diary_home"))

    def test_header_name_shows_in_the_header_and_the_home_page_name_on_hover_and_home(self):
        Profile.objects.filter(pk=self.main().pk).update(display_name="Madon Chambers Case Law", header_name="Madon")
        self.client.force_login(self.user)
        resp = self.client.get(reverse("flags"))
        self.assertContains(resp, 'title="Madon Chambers Case Law" aria-label="Madon: Home">Madon</a>')
        self.assertNotContains(resp, 'class="profile-name"')
        home = self.client.get(reverse("home") + "?home=1")
        self.assertContains(home, 'class="program-link" href="/caselaw/subjects/">Madon Chambers Case Law</a>')

    def test_header_name_alone_hovers_with_the_program_and_profile_name(self):
        Profile.objects.filter(pk=self.main().pk).update(header_name="Short")
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("flags")), 'title="Case Law Diary \u00b7 Main" aria-label="Short: Home">Short</a>')
        self.assertContains(self.client.get(reverse("home") + "?home=1"), 'class="program-link" href="/caselaw/subjects/">Case Law Diary</a>')

    def test_editor_sets_the_header_name_trimmed(self):
        self.client.force_login(self.admin)
        self.display({"diary-display_name": "Long Name", "diary-header_name": "  Short   One "})
        main = self.main()
        self.assertEqual((main.display_name, main.header_name), ("Long Name", "Short One"))

    def test_home_picker_button_shows_display_name_else_program_name(self):
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("home") + "?home=1"), 'class="program-link" href="/caselaw/subjects/">Case Law Diary</a>')
        self.set_name("Mine")
        self.assertContains(self.client.get(reverse("home") + "?home=1"), 'class="program-link" href="/caselaw/subjects/">Mine</a>')

    # The Display Name is on Case Law Diary settings > Reading (fields prefixed "diary-").
    def display(self, data=None):
        if data is None:
            return self.client.get(reverse("profile_settings") + "?tab=reading")
        # Round 19: the Display tab's required Yes/No toggle must be posted too, or the profile form fails validation
        # and the Display Name is not saved. Keeping reading_all_mode on "remember" means the toggle does not change
        # the stored mode, so these Display Name assertions are unaffected.
        return self.client.post(
            reverse("profile_settings"),
            {"tab": "reading", "diary-reading_all_mode": "remember", "diary-view_whole_subject": "no", **data},
        )

    def test_editor_sets_it_trimmed_and_clearing_falls_back(self):
        self.client.force_login(self.admin)  # Editor of Main
        resp = self.display({"diary-display_name": "  Madon's   Cases "})
        self.assertRedirects(resp, reverse("profile_settings") + "?tab=reading")
        self.assertEqual(self.main().display_name, "Madon's Cases")
        self.assertEqual(self.main().export_name, "")  # export_name is unchanged
        self.display({"diary-display_name": ""})
        self.assertEqual(self.main().display_name, "")
        self.assertContains(self.client.get(reverse("diary_home")), 'class="profile-name">&middot; Main</span>')

    def test_too_long_is_refused_and_the_header_is_not_changed(self):
        self.client.force_login(self.admin)
        resp = self.display({"diary-display_name": "x" * 81})
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'aria-label="%s: Home"' % ("x" * 81))
        self.assertEqual(self.main().display_name, "")

    def test_reader_sees_it_but_cannot_change_it(self):
        self.set_name("Mine")
        self.client.force_login(self.user)
        resp = self.display()
        self.assertContains(resp, "<strong>Mine</strong>")
        self.assertNotContains(resp, 'name="diary-display_name"')
        self.display({"diary-display_name": "Hacked"})
        self.assertEqual(self.main().display_name, "Mine")

    def test_editor_form_shows_the_field(self):
        self.client.force_login(self.admin)
        resp = self.display()
        self.assertContains(resp, 'name="diary-display_name"')
        self.assertContains(resp, "Display Name")

    def test_profiles_are_isolated(self):
        junior = Profile.objects.create(program="diary", name="Junior")
        self.client.force_login(self.admin)
        self.display({"diary-display_name": "Mine"})
        junior.refresh_from_db()
        self.assertEqual(junior.display_name, "")

    def test_admin_sets_it_on_the_profiles_screen(self):
        profile = Profile.objects.create(program="diary", name="Junior")
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("profile_edit", args=[profile.pk]), {"name": "Junior", "display_name": " Junior's Law "})
        self.assertRedirects(resp, reverse("profile_list"))
        profile.refresh_from_db()
        self.assertEqual(profile.display_name, "Junior's Law")
        self.assertContains(self.client.get(reverse("profile_list")), "Junior&#x27;s Law")
        self.assertContains(self.client.get(reverse("profile_edit", args=[profile.pk])), 'name="display_name"')

    def test_admin_can_create_a_profile_with_a_display_name(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("profile_create"), {"name": "Third", "display_name": "The Third"})
        self.assertEqual(Profile.objects.get(name="Third").display_name, "The Third")

    def test_non_admin_cannot_use_the_profiles_screen(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(reverse("profile_edit", args=[self.main().pk]), {"name": "Main", "display_name": "X"}).status_code, 403)
        self.assertEqual(self.main().display_name, "")
