from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from diary import reading
from diary.models import Item, Note, NoteLink, Section, Subject, Subtopic, Topic
from diary.sample_data import SAMPLE_PREFIX, load_sample_data, remove_sample_data


@override_settings(SECURE_SSL_REDIRECT=False)
class DiaryTests(TestCase):
    def test_home_requires_login(self):
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith(reverse("login")))

    def test_home_shows_title_and_username(self):
        user = get_user_model().objects.create_user("alice", password="x-long-pass-123")
        self.client.force_login(user)
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, "Judgment Diary")
        self.assertContains(resp, "alice")

    def test_healthz_without_login(self):
        resp = self.client.get("/healthz/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b"ok")


PASSWORD = "x-long-pass-123"


@override_settings(SECURE_SSL_REDIRECT=False)
class ReadingScreenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        load_sample_data()
        cls.users = {
            role: User.objects.create_user(role, password=PASSWORD, role=role)
            for role in ("reader", "editor", "admin")
        }
        cls.contract = Subject.objects.get(name=SAMPLE_PREFIX + "Contract Law")
        cls.longs = Subject.objects.get(name=SAMPLE_PREFIX + "Long Lists")
        cls.other = Subject.objects.get(name=SAMPLE_PREFIX + "Other Subject (Sample Act)")
        cls.clause = Subtopic.objects.get(name="Clause 12: Leave to Sue")
        cls.offer = Subtopic.objects.get(name="Offer")

    def urls(self):
        return [
            reverse("home"),
            reverse("other_subjects"),
            reverse("search"),
            reverse("subject_contents", args=[self.contract.pk]),
            reverse("read_subject", args=[self.contract.pk]),
            reverse("read_topic", args=[Topic.objects.get(name="Remedies").pk]),
            reverse("read_subtopic", args=[self.clause.pk]),
            reverse("read_subject", args=[self.other.pk]),
        ]

    def test_every_role_can_read_every_screen(self):
        for role, user in self.users.items():
            self.client.force_login(user)
            for url in self.urls():
                self.assertEqual(self.client.get(url).status_code, 200, f"{role} {url}")
            self.client.logout()

    def test_anonymous_is_sent_to_login(self):
        for url in self.urls():
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302, url)
            self.assertTrue(resp["Location"].startswith(reverse("login")), url)

    def test_unknown_and_deleted_records_are_404(self):
        self.client.force_login(self.users["reader"])
        self.assertEqual(self.client.get(reverse("read_subject", args=[999999])).status_code, 404)
        from django.utils import timezone

        Subject.objects.filter(pk=self.longs.pk).update(deleted_at=timezone.now())
        self.assertEqual(self.client.get(reverse("read_subject", args=[self.longs.pk])).status_code, 404)
        topic = Topic.objects.filter(subject=self.longs).first()
        self.assertEqual(self.client.get(reverse("read_topic", args=[topic.pk])).status_code, 404)

    def test_landing_respects_show_on_landing(self):
        self.client.force_login(self.users["reader"])
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, "Contract Law")
        self.assertContains(resp, "Other Subjects")
        self.assertNotContains(resp, "Sample Act")
        resp = self.client.get(reverse("other_subjects"))
        self.assertContains(resp, "Sample Act")
        self.assertNotContains(resp, "Contract Law")

    def test_contents_lists_topics_and_subtopics(self):
        self.client.force_login(self.users["reader"])
        resp = self.client.get(reverse("subject_contents", args=[self.contract.pk]))
        self.assertContains(resp, "View whole Subject")
        self.assertContains(resp, "Formation")
        self.assertContains(resp, "Acceptance")

    def test_other_subject_lists_subtopics_directly(self):
        self.client.force_login(self.users["reader"])
        resp = self.client.get(reverse("subject_contents", args=[self.other.pk]))
        self.assertContains(resp, "Sample provision 1")
        self.assertContains(resp, "Sample provision 3")

    def test_reading_view_shows_expected_features(self):
        self.client.force_login(self.users["reader"])
        resp = self.client.get(reverse("read_subject", args=[self.contract.pk]))
        self.assertContains(resp, '<em class="citation">Harvey v. Facey [1893] AC 552</em>', html=False)
        self.assertContains(resp, "flagged")
        self.assertContains(resp, "Overruled by New v. Law (1990)")
        self.assertContains(resp, "For review: Check the citation against the report.")
        self.assertContains(resp, "See also: ")
        self.assertContains(resp, "Carlill v. Carbolic Smoke Ball Co")
        self.assertContains(resp, " ; ")
        self.assertContains(resp, "View whole Subject")

    def test_topic_and_subtopic_views_show_correct_buttons_and_numbers(self):
        self.client.force_login(self.users["reader"])
        resp = self.client.get(reverse("read_subtopic", args=[self.clause.pk]))
        self.assertContains(resp, "View this Topic")
        self.assertContains(resp, "View this Sub-topic")
        self.assertContains(resp, "Clause 12: Leave to Sue")
        # Remedies is the second Topic and Clause 12 the first Sub-topic, even when read alone.
        self.assertContains(resp, "(viii)")

    def test_user_formats_are_used(self):
        from diary.models import UserSettings

        UserSettings.objects.create(user=self.users["editor"], section_format="section_n", item_format="decimal")
        self.client.force_login(self.users["editor"])
        resp = self.client.get(reverse("read_subtopic", args=[self.clause.pk]))
        self.assertContains(resp, "Section 1")
        self.assertContains(resp, "Section 2")


class ReadingNumberingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        load_sample_data()

    def labels(self, subtopic):
        """Labels of the Items and Sections shown directly in one Sub-topic, in order."""
        subject = subtopic.topic.subject if subtopic.topic_id else subtopic.subject
        ctx = reading.build_reading(subject, None, "subtopic", subtopic)
        return [b["label"] for b in ctx["blocks"] if b["kind"] in ("item", "section")]

    def test_clause_12_example(self):
        clause = Subtopic.objects.get(name="Clause 12: Leave to Sue")
        self.assertEqual(
            self.labels(clause),
            ["(i)", "(ii)", "(A)", "(i)", "(ii)", "(B)"] + ["(i)", "(ii)", "(iii)", "(iv)", "(v)", "(vi)", "(vii)", "(viii)"],
        )

    def test_long_lists_continue_correctly(self):
        many = Subtopic.objects.get(name__startswith="Forty-five")
        labels = self.labels(many)
        self.assertEqual(len(labels), 45)
        self.assertIn("(xxxix)", labels)
        self.assertEqual(labels[39], "(xl)")
        self.assertEqual(labels[-1], "(xlv)")
        plenty = Subtopic.objects.get(name__startswith="Thirty Sections")
        sections = self.labels(plenty)
        self.assertEqual(sections[25], "(Z)")
        self.assertEqual(sections[26], "(AA)")
        self.assertEqual(sections[-1], "(AD)")

    def test_topics_and_subtopics_and_nested_bullets(self):
        contract = Subject.objects.get(name=SAMPLE_PREFIX + "Contract Law")
        ctx = reading.build_reading(contract, None)
        headings = [(b["level"], b["label"], b["name"]) for b in ctx["blocks"] if b["kind"] == "heading"]
        self.assertIn(("topic", "A", "Formation"), headings)
        self.assertIn(("topic", "B", "Remedies"), headings)
        self.assertIn(("subtopic", "2", "Acceptance"), headings)
        nested = [b for b in ctx["blocks"] if b["kind"] == "item" and b["is_nested"]][0]
        self.assertEqual([c["label"] for c in nested["children"]], ["\u2022", "\u2022"])
        self.assertEqual(nested["label"], "(iv)")

    def test_deleted_records_are_not_shown_and_do_not_use_numbers(self):
        from django.utils import timezone

        offer = Subtopic.objects.get(name="Offer")
        Item.objects.filter(subtopic=offer, position=1).update(deleted_at=timezone.now())
        labels = self.labels(offer)
        self.assertEqual(labels[0], "(i)")
        self.assertEqual(len(labels), 5)

    def test_note_link_to_deleted_target_has_no_url(self):
        from django.utils import timezone

        acceptance = Subtopic.objects.get(name="Acceptance")
        Subtopic.objects.filter(pk=acceptance.pk).update(deleted_at=timezone.now())
        link = NoteLink.objects.get(subtopic=acceptance)
        path, url = reading.note_target(NoteLink.objects.select_related("subtopic").get(pk=link.pk))
        self.assertIsNone(url)
        self.assertIn("(deleted)", path)


class SampleDataTests(TestCase):
    def test_load_is_idempotent(self):
        self.assertTrue(load_sample_data())
        count = Item.objects.count()
        self.assertFalse(load_sample_data())
        self.assertEqual(Item.objects.count(), count)
        self.assertEqual(Subject.objects.filter(name__startswith=SAMPLE_PREFIX).count(), 3)

    def test_remove_deletes_only_sample_records(self):
        real = Subject.objects.create(name="Real Subject")
        real_topic = Topic.objects.create(subject=real, name="Real Topic")
        real_item = Item.objects.create(topic=real_topic, text="<p>Mine</p>", citation="X")
        real_section = Section.objects.create(topic=real_topic, name="S")
        real_note = Note.objects.create(topic=real_topic, text="<p>n</p>")
        load_sample_data()
        self.assertEqual(remove_sample_data(), 3)
        self.assertEqual(list(Subject.objects.values_list("name", flat=True)), ["Real Subject"])
        self.assertTrue(Item.objects.filter(pk=real_item.pk).exists())
        self.assertTrue(Section.objects.filter(pk=real_section.pk).exists())
        self.assertTrue(Note.objects.filter(pk=real_note.pk).exists())
        self.assertEqual(Item.objects.count(), 1)
        self.assertEqual(NoteLink.objects.count(), 0)
        self.assertEqual(remove_sample_data(), 0)

    def test_commands_run(self):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("load_sample_data", stdout=out)
        call_command("load_sample_data", stdout=out)
        self.assertIn("already loaded", out.getvalue())
        call_command("remove_sample_data", stdout=out)
        self.assertEqual(Subject.objects.count(), 0)
