"""My settings: the opening page, the number formats and their preview, and last page tracking."""
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, User
from accounts.profiles import set_user_profile
from diary.models import Item, Subject, Subtopic, Topic, UserSettings
from diary.sample_data import SAMPLE_PREFIX, load_sample_data
from diary.tests.helpers import join_main, main_profile

PASSWORD = "x-long-pass-123"

ALL_FORMATS = {
    "topic_format": "upper_roman",
    "subtopic_format": "paren_upper_alpha",
    "section_format": "section_n",
    "item_format": "lower_roman",
    "multi_citation_format": "decimal",
}


@override_settings(SECURE_SSL_REDIRECT=False)
class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        load_sample_data(main_profile())
        cls.editor = join_main(User.objects.create_user("ed", password=PASSWORD), "editor")
        cls.reader = join_main(User.objects.create_user("rita", password=PASSWORD), "reader")
        cls.loner = User.objects.create_user("loner", password=PASSWORD)
        cls.contract = Subject.objects.get(name=SAMPLE_PREFIX + "Contract Law")
        cls.offer = Subtopic.objects.get(name="Offer")
        cls.remedies = Topic.objects.get(name="Remedies")
        cls.elsewhere = Profile.objects.create(program="diary", name="Elsewhere")
        cls.foreign = Subject.objects.create(profile=cls.elsewhere, name="Foreign Subject")

    def settings_of(self, user):
        return UserSettings.objects.filter(user=user).first()


class SettingsPageTests(Base):
    def test_page_shows_both_sections(self):
        self.client.force_login(self.editor)
        resp = self.client.get(reverse("my_settings"))
        self.assertContains(resp, "Open after login")
        self.assertContains(resp, "Number formats")
        self.assertContains(resp, "Preview")
        for name in ALL_FORMATS:
            self.assertContains(resp, f'name="{name}"')
        self.assertContains(resp, "never your stored data")
        self.assertContains(resp, "Use the standard formats")
        self.assertContains(resp, 'data-default="upper_alpha"')
        self.assertContains(resp, 'data-default="paren_decimal"')
        self.assertNotContains(resp, 'name="nested_item_format"')
        self.assertContains(resp, 'name="opening_page"')
        self.assertContains(resp, "Index of Subjects")

    def test_preview_is_rendered_on_the_page_with_the_saved_formats(self):
        UserSettings.objects.create(user=self.editor, topic_format="upper_roman")
        self.client.force_login(self.editor)
        resp = self.client.get(reverse("my_settings"))
        self.assertContains(resp, '<span class="num">II.</span>')
        self.assertContains(resp, "Sample Subject")

    def test_user_without_a_diary_profile_has_no_diary_section(self):
        self.client.force_login(self.loner)
        resp = self.client.get(reverse("my_settings"))
        self.assertContains(resp, "Open after login")
        self.assertNotContains(resp, "Number formats")
        self.assertNotContains(resp, 'name="topic_format"')

    def test_diary_fields_are_ignored_without_a_profile(self):
        self.client.force_login(self.loner)
        resp = self.client.post(reverse("my_settings"), {"landing_program": "", **ALL_FORMATS})
        self.assertRedirects(resp, reverse("my_settings"))
        self.assertIsNone(self.settings_of(self.loner))

    def test_saving_formats_changes_labels_but_not_stored_data(self):
        def stored():
            return list(Item.objects.filter(subtopic=self.offer).order_by("pk").values_list("pk", "text", "position", "version"))

        before = stored()
        self.client.force_login(self.editor)
        url = reverse("read_subtopic", args=[self.offer.pk])
        self.client.cookies["quill_in_context"] = "0"
        self.assertContains(self.client.get(url), '<span class="num">(1)</span>')
        resp = self.client.post(reverse("my_settings"), {"landing_program": "", **ALL_FORMATS})
        self.assertRedirects(resp, reverse("my_settings"))
        row = self.settings_of(self.editor)
        for name, value in ALL_FORMATS.items():
            self.assertEqual(getattr(row, name), value)
        resp = self.client.get(url)
        self.assertContains(resp, '<span class="num">i.</span>')
        self.assertNotContains(resp, '<span class="num">(1)</span>')
        self.assertEqual(stored(), before)

    def test_section_n_shows_on_the_reading_page(self):
        self.client.force_login(self.editor)
        self.client.post(reverse("my_settings"), {"section_format": "section_n"})
        clause = Subtopic.objects.get(name="Clause 12: Leave to Sue")
        self.client.cookies["quill_in_context"] = "0"
        self.assertContains(self.client.get(reverse("read_subtopic", args=[clause.pk])), "Section 1")

    def test_invalid_format_is_rejected_and_nothing_is_saved(self):
        self.client.force_login(self.editor)
        resp = self.client.post(reverse("my_settings"), {"landing_program": "diary", "item_format": "zzz", "topic_format": "decimal"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Select a valid choice")
        self.assertIsNone(self.settings_of(self.editor))
        self.editor.refresh_from_db()
        self.assertEqual(self.editor.landing_program, "")

    def test_section_n_is_not_allowed_for_items(self):
        self.client.force_login(self.editor)
        resp = self.client.post(reverse("my_settings"), {"item_format": "section_n"})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(self.settings_of(self.editor))

    def test_reader_can_save_own_settings(self):
        self.client.force_login(self.reader)
        resp = self.client.post(reverse("my_settings"), {"landing_program": "diary", "topic_format": "decimal"})
        self.assertRedirects(resp, reverse("my_settings"))
        self.assertEqual(self.settings_of(self.reader).topic_format, "decimal")

    def test_only_own_settings_change(self):
        UserSettings.objects.create(user=self.editor, topic_format="lower_alpha")
        self.client.force_login(self.reader)
        self.client.post(reverse("my_settings"), {"topic_format": "decimal", "user": self.editor.pk, "id": self.editor.pk})
        self.assertEqual(self.settings_of(self.editor).topic_format, "lower_alpha")

    def test_old_post_with_only_landing_program_keeps_other_settings(self):
        UserSettings.objects.create(user=self.editor, item_format="decimal", opening_page="search")
        self.client.force_login(self.editor)
        resp = self.client.post(reverse("my_settings"), {"landing_program": "diary"})
        self.assertRedirects(resp, reverse("my_settings"))
        row = self.settings_of(self.editor)
        self.assertEqual(row.item_format, "decimal")
        self.assertEqual(row.opening_page, "search")
        self.editor.refresh_from_db()
        self.assertEqual(self.editor.landing_program, "diary")

    def test_chosen_subject_page_needs_a_subject(self):
        self.client.force_login(self.editor)
        resp = self.client.post(reverse("my_settings"), {"opening_page": "subject"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Choose a Subject")
        self.assertIsNone(self.settings_of(self.editor))

    def test_chosen_subject_is_saved(self):
        self.client.force_login(self.editor)
        resp = self.client.post(reverse("my_settings"), {"opening_page": "subject", "opening_subject": self.contract.pk})
        self.assertRedirects(resp, reverse("my_settings"))
        row = self.settings_of(self.editor)
        self.assertEqual((row.opening_page, row.opening_subject_id), ("subject", self.contract.pk))

    def test_subject_of_another_profile_is_rejected(self):
        self.client.force_login(self.editor)
        resp = self.client.post(reverse("my_settings"), {"opening_page": "subject", "opening_subject": self.foreign.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(self.settings_of(self.editor))

    def test_legacy_other_subjects_is_shown_as_home_and_kept(self):
        UserSettings.objects.create(user=self.editor, opening_page="other_subjects")
        self.client.force_login(self.editor)
        self.assertContains(self.client.get(reverse("my_settings")), '<option value="home" selected>')
        self.client.post(reverse("my_settings"), {"opening_page": "home", "topic_format": "decimal"})
        self.assertEqual(self.settings_of(self.editor).opening_page, "other_subjects")
        self.client.post(reverse("my_settings"), {"opening_page": "search"})
        self.assertEqual(self.settings_of(self.editor).opening_page, "search")


class PreviewEndpointTests(Base):
    def test_requires_sign_in_and_get(self):
        self.assertEqual(self.client.get(reverse("format_preview")).status_code, 302)
        self.client.force_login(self.editor)
        self.assertEqual(self.client.post(reverse("format_preview")).status_code, 405)

    def test_defaults(self):
        self.client.force_login(self.editor)
        resp = self.client.get(reverse("format_preview"))
        self.assertContains(resp, '<span class="num">A.</span>')
        self.assertContains(resp, '<span class="num">(1)</span>')
        self.assertNotContains(resp, "<html")

    def test_requested_formats_are_used(self):
        self.client.force_login(self.editor)
        resp = self.client.get(reverse("format_preview"), {"topic_format": "decimal", "section_format": "section_n"})
        self.assertContains(resp, '<span class="num">1.</span>')
        self.assertContains(resp, "Section 2.")
        self.assertNotContains(resp, '<span class="num">A.</span>')

    def test_junk_falls_back_to_the_saved_or_standard_formats(self):
        UserSettings.objects.create(user=self.editor, topic_format="upper_roman")
        self.client.force_login(self.editor)
        resp = self.client.get(reverse("format_preview"), {"topic_format": "<script>", "item_format": "section_n", "bogus": "x"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "<script>")
        self.assertContains(resp, '<span class="num">II.</span>')  # topic: junk, so the saved format
        self.assertContains(resp, '<span class="num">(1)</span>')  # item: not allowed, so the standard format

    def test_works_without_a_diary_profile(self):
        self.client.force_login(self.loner)
        self.assertContains(self.client.get(reverse("format_preview"), {"topic_format": "decimal"}), "Sample Topic")


class OpeningPageTests(Base):
    def choose(self, user, page="home", subject=None, program="diary"):
        UserSettings.objects.update_or_create(user=user, defaults={"opening_page": page, "opening_subject": subject})
        User.objects.filter(pk=user.pk).update(landing_program=program)

    def login(self, next_url=None):
        data = {"username": "ed", "password": PASSWORD}
        if next_url is not None:
            data["next"] = next_url
        return self.client.post(reverse("login"), data)

    def expect(self, location):
        """Both ways in: signing in, and the bare entry visit to /."""
        self.assertEqual(self.login()["Location"], location)
        self.client.logout()
        self.client.force_login(User.objects.get(username="ed"))
        self.assertEqual(self.client.get(reverse("home"))["Location"], location)
        self.client.logout()

    def test_each_option_opens_the_right_page(self):
        self.choose(self.editor, "home")
        self.expect(reverse("diary_home"))
        self.choose(self.editor, "other_subjects")
        self.expect(reverse("diary_home") + "#other-subjects")
        self.choose(self.editor, "search")
        self.expect(reverse("search"))
        self.choose(self.editor, "subject", self.contract)
        self.expect(reverse("read_subject", args=[self.contract.pk]))

    def test_last_page_opens_the_last_viewed_page(self):
        self.choose(self.editor, "last")
        path = reverse("read_topic", args=[self.remedies.pk])
        User.objects.filter(pk=self.editor.pk).update(last_diary_path=path)
        self.expect(path)

    def test_last_page_with_a_query_is_kept(self):
        self.choose(self.editor, "last")
        path = reverse("search") + "?q=duty"
        User.objects.filter(pk=self.editor.pk).update(last_diary_path=path)
        self.expect(path)

    def test_last_page_falls_back_when_blank_or_invalid(self):
        self.choose(self.editor, "last")
        for bad in ("", "/users/", "//evil.example.com/caselaw/", "/caselaw/nonsense/", "https://evil.example.com/caselaw/subjects/",
                    reverse("edit_add"), reverse("read_topic", args=[999999])):
            User.objects.filter(pk=self.editor.pk).update(last_diary_path=bad)
            self.expect(reverse("diary_home"))

    def test_last_page_falls_back_when_the_subject_is_in_trash(self):
        self.choose(self.editor, "last")
        subject = Subject.objects.create(profile=main_profile(), name="Short lived")
        User.objects.filter(pk=self.editor.pk).update(last_diary_path=reverse("read_subject", args=[subject.pk]))
        self.expect(reverse("read_subject", args=[subject.pk]))
        Subject.objects.filter(pk=subject.pk).update(deleted_at=timezone.now())
        self.expect(reverse("diary_home"))

    def test_last_page_of_another_profile_is_not_followed(self):
        self.choose(self.editor, "last")
        User.objects.filter(pk=self.editor.pk).update(last_diary_path=reverse("read_subject", args=[self.foreign.pk]))
        self.expect(reverse("diary_home"))

    def test_chosen_subject_from_another_profile_is_ignored(self):
        self.choose(self.editor, "subject", self.foreign)
        self.expect(reverse("diary_home"))

    def test_chosen_subject_in_trash_is_ignored(self):
        subject = Subject.objects.create(profile=main_profile(), name="Gone", deleted_at=timezone.now())
        self.choose(self.editor, "subject", subject)
        self.expect(reverse("diary_home"))

    def test_home_is_still_reachable(self):
        self.choose(self.editor, "search")
        self.client.force_login(self.editor)
        self.assertEqual(self.client.get(reverse("home"), {"home": "1"}).status_code, 200)
        self.assertEqual(self.client.get(reverse("home"), HTTP_REFERER="http://testserver/caselaw/subjects/").status_code, 200)

    def test_safe_next_wins_and_unsafe_next_is_ignored(self):
        self.choose(self.editor, "search")
        self.assertEqual(self.login(next_url=reverse("my_settings"))["Location"], reverse("my_settings"))
        self.client.logout()
        self.assertEqual(self.login(next_url="https://evil.example.com/x")["Location"], reverse("search"))

    def test_home_choice_in_my_settings_ignores_the_diary_page(self):
        self.choose(self.editor, "search", program="")
        self.assertEqual(self.login()["Location"], reverse("home"))

    def test_user_without_profile_goes_home(self):
        UserSettings.objects.create(user=self.loner, opening_page="search")
        User.objects.filter(pk=self.loner.pk).update(landing_program="diary")
        data = {"username": "loner", "password": PASSWORD}
        self.assertEqual(self.client.post(reverse("login"), data)["Location"], reverse("home"))


class LastPageTrackingTests(Base):
    def last(self):
        return User.objects.get(pk=self.editor.pk).last_diary_path

    def setUp(self):
        self.client.force_login(self.editor)
        self.client.cookies["quill_in_context"] = "0"

    def test_viewed_pages_are_remembered(self):
        urls = [
            reverse("diary_home"),
            reverse("subject_contents", args=[self.contract.pk]),
            reverse("read_subject", args=[self.contract.pk]),
            reverse("read_topic", args=[self.remedies.pk]),
            reverse("read_subtopic", args=[self.offer.pk]),
            reverse("search") + "?q=duty",
            reverse("flags"),
            reverse("flag_links"),
        ]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200, url)
            self.assertEqual(self.last(), url)

    def test_edit_mode_is_not_remembered(self):
        url = reverse("read_subject", args=[self.contract.pk])
        self.client.get(url)
        self.client.get(url + "?edit=1")
        self.assertEqual(self.last(), url)

    def test_post_and_errors_are_not_remembered(self):
        url = reverse("read_subject", args=[self.contract.pk])
        self.client.get(url)
        self.client.post(reverse("read_topic", args=[self.remedies.pk]))
        self.assertEqual(self.last(), url)
        self.assertEqual(self.client.get(reverse("read_topic", args=[999999])).status_code, 404)
        self.assertEqual(self.last(), url)

    def test_other_pages_are_not_remembered(self):
        url = reverse("search")
        self.client.get(url)
        for other in (reverse("my_settings"), reverse("profile_settings"), reverse("trash")):
            self.client.get(other)
        self.assertEqual(self.last(), url)

    def test_very_long_address_is_not_remembered(self):
        url = reverse("search")
        self.client.get(url)
        self.client.get(url, {"q": "x" * 600})
        self.assertEqual(self.last(), url)

    def test_unchanged_page_does_not_write_again(self):
        url = reverse("search")
        self.client.get(url)
        with self.assertNumQueries(self._queries_of(url)):
            self.client.get(url)

    def _queries_of(self, url):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            self.client.get(url)
        return len(ctx)

    def test_reader_pages_are_remembered_too(self):
        self.client.force_login(self.reader)
        url = reverse("read_subject", args=[self.contract.pk])
        self.client.get(url)
        self.assertEqual(User.objects.get(pk=self.reader.pk).last_diary_path, url)

    def test_each_user_keeps_their_own(self):
        set_user_profile(self.loner, self.elsewhere, "reader")
        self.client.get(reverse("search"))
        self.client.force_login(self.loner)
        self.client.get(reverse("read_subject", args=[self.foreign.pk]))
        self.assertEqual(self.last(), reverse("search"))
        self.assertEqual(User.objects.get(pk=self.loner.pk).last_diary_path, reverse("read_subject", args=[self.foreign.pk]))
