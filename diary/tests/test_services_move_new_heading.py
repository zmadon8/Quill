"""Move to a new Topic or Sub-topic (round 11): rules, validation, one Undo step, previews, views."""
from django.test import override_settings
from django.urls import reverse

from diary import services as svc
from diary.models import Subtopic, Topic, VersionHistory
from diary.tests.helpers import join_main
from diary.tests.service_helpers import ServiceTestCase


class NewHeadingServiceTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.build_topic()

    def kinds(self, obj):
        return [o["kind"] for o in svc.new_heading_options(self.profile, self.user, obj)]

    def test_item_in_a_topic_is_offered_both(self):
        self.assertEqual(self.kinds(self.one), ["topic", "subtopic"])
        self.assertEqual(self.kinds(self.sec), ["topic", "subtopic"])

    def test_topic_gets_neither(self):
        self.assertEqual(self.kinds(self.topic), [])

    def test_subtopic_gets_only_a_new_topic(self):
        sub = self.make("subtopic", ("topic", self.topic.pk), name="Sub")
        self.assertEqual(self.kinds(sub), ["topic"])

    def test_item_in_a_subtopic_is_offered_the_topic_the_subtopic_sits_in(self):
        sub = self.make("subtopic", ("topic", self.topic.pk), name="Sub")
        item = self.make("item", ("subtopic", sub.pk), text="deep")
        options = {o["kind"]: o for o in svc.new_heading_options(self.profile, self.user, item)}
        self.assertEqual(options["subtopic"]["parent"].pk, self.topic.pk)
        self.assertEqual(options["topic"]["parent"].pk, self.subject.pk)

    def test_subject_holding_subtopics_directly_offers_no_new_topic(self):
        other = self.make("subject", name="Others")
        sub = self.make("subtopic", ("subject", other.pk), name="Direct")
        item = self.make("item", ("subtopic", sub.pk), text="in direct")
        self.assertEqual(self.kinds(item), [])
        self.assertEqual(self.kinds(sub), [])

    def test_move_into_a_new_topic(self):
        result = svc.move_to_new_heading(self.profile, self.user, "item", self.one.pk, "topic", "  Zed   Topic ")
        new = Topic.objects.get(subject=self.subject, name="Zed Topic")
        self.assertEqual(self.get(self.one).topic_id, new.pk)
        self.assertEqual(result.info["heading"].pk, new.pk)
        self.assertEqual(self.numbered(self.topic), [("(1)", "two"), ("(a)", "S"), ("(1)", "three"), ("(2)", "four")])

    def test_move_into_a_new_subtopic(self):
        svc.move_to_new_heading(self.profile, self.user, "section", self.sec.pk, "subtopic", "Fresh")
        new = Subtopic.objects.get(topic=self.topic, name="Fresh")
        self.assertEqual(self.get(self.sec).subtopic_id, new.pk)
        self.assertIsNone(self.get(self.sec).topic_id)

    def test_subtopic_moves_into_a_new_topic(self):
        sub = self.make("subtopic", ("topic", self.topic.pk), name="Sub")
        svc.move_to_new_heading(self.profile, self.user, "subtopic", sub.pk, "topic", "Elsewhere")
        new = Topic.objects.get(subject=self.subject, name="Elsewhere")
        self.assertEqual(self.get(sub).topic_id, new.pk)

    def test_whole_action_is_one_undo_group(self):
        result = svc.move_to_new_heading(self.profile, self.user, "item", self.one.pk, "topic", "Zed")
        self.assertIsNotNone(result.group)
        rows = VersionHistory.objects.filter(profile=self.profile, group=result.group)
        self.assertLessEqual({"topic", "item"}, {r.record_type for r in rows})  # renumbered Sections share the group too
        svc.undo_group(self.profile, self.user, result.group)
        self.assertEqual(self.get(self.one).topic_id, self.topic.pk)
        self.assertFalse(Topic._base_manager.filter(subject=self.subject, name="Zed", deleted_at__isnull=True).exists())

    def test_name_is_required_and_unique_among_siblings_case_insensitively(self):
        from diary.services.errors import ValidationFailed

        for bad in ("", "   "):
            with self.assertRaises(ValidationFailed):
                svc.move_to_new_heading(self.profile, self.user, "item", self.one.pk, "topic", bad)
        with self.assertRaises(ValidationFailed):
            svc.move_to_new_heading(self.profile, self.user, "item", self.one.pk, "topic", "formation")
        with self.assertRaises(ValidationFailed):
            svc.move_to_new_heading(self.profile, self.user, "item", self.one.pk, "topic", "FORMATION ")
        self.assertEqual(self.get(self.one).topic_id, self.topic.pk)
        self.assertEqual(Topic.objects.filter(subject=self.subject).count(), 1)

    def test_a_kind_that_is_not_offered_is_refused(self):
        from diary.services.errors import Refused

        with self.assertRaises(Refused):
            svc.move_to_new_heading(self.profile, self.user, "topic", self.topic.pk, "topic", "No")
        sub = self.make("subtopic", ("topic", self.topic.pk), name="Sub")
        with self.assertRaises(Refused):
            svc.move_to_new_heading(self.profile, self.user, "subtopic", sub.pk, "subtopic", "No")

    def test_a_stale_version_changes_nothing(self):
        from diary.services.errors import Conflict

        with self.assertRaises(Conflict):
            svc.move_to_new_heading(self.profile, self.user, "item", self.one.pk, "topic", "Zed", expected_version=99)
        self.assertFalse(Topic.objects.filter(name="Zed").exists())

    def test_preview_writes_nothing_and_lists_renumbering(self):
        before = VersionHistory.objects.count()
        preview = svc.preview_move_to_new_heading(self.profile, self.user, "item", self.one.pk, "topic", "Zed")
        self.assertEqual(preview["heading"], "Zed")
        changes = {c["id"]: (c["before"], c["after"]) for c in preview["changes"] if c["type"] == "item"}
        self.assertEqual(changes[self.two.pk], ("(2)", "(1)"))
        topic_change = [c for c in preview["changes"] if c["type"] == "topic"]
        self.assertEqual(topic_change, [])  # "Formation" stays A, "Zed" comes after it
        self.assertEqual(VersionHistory.objects.count(), before)
        self.assertFalse(Topic.objects.filter(name="Zed").exists())
        self.assertEqual(self.get(self.one).topic_id, self.topic.pk)

    def test_preview_shows_a_topic_letter_change(self):
        preview = svc.preview_move_to_new_heading(self.profile, self.user, "item", self.one.pk, "topic", "Aardvark")
        topic_change = [(c["before"], c["after"]) for c in preview["changes"] if c["type"] == "topic"]
        self.assertEqual(topic_change, [("A", "B")])


@override_settings(SECURE_SSL_REDIRECT=False)
class NewHeadingViewTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        join_main(self.user, "editor")
        self.build_topic()
        self.client.force_login(self.user)
        self.next = reverse("read_subject", args=[self.subject.pk]) + "?edit=1"

    def post(self, **extra):
        data = {"kind": "item", "id": self.one.pk, "version": self.get(self.one).version, "next": self.next,
                "new_heading": "topic", **extra}
        return self.client.post(reverse("edit_move_new"), data)

    def test_picker_lists_the_new_options_first_and_hides_them_for_a_topic(self):
        page = self.client.post(reverse("edit_move_to"), {"kind": "item", "id": self.one.pk, "next": self.next}).content.decode()
        self.assertIn("+ New Topic in this Subject", page)
        self.assertIn("+ New Sub-topic in this Topic", page)
        topic_page = self.client.post(reverse("edit_move_to"), {"kind": "topic", "id": self.topic.pk, "next": self.next}).content.decode()
        self.assertNotIn("New Topic in this Subject", topic_page)
        self.assertNotIn("New Sub-topic in this Topic", topic_page)

    def test_name_form_then_validation_error_then_preview_then_done(self):
        self.assertContains(self.post(), 'name="name"')
        empty = self.post(name_given="1", name="  ")
        self.assertRegex(empty.content.decode(), r'(?s)<p class="error" role="alert">[^<]*required[^<]*</p>')
        self.assertContains(empty, 'name="name"')
        clash = self.post(name_given="1", name="formation")
        self.assertContains(clash, "already exists")
        preview = self.post(name_given="1", name="Zed")
        self.assertContains(preview, "Make it and move")
        self.assertEqual(self.get(self.one).topic_id, self.topic.pk)
        done = self.post(name_given="1", name="Zed", confirmed="1")
        self.assertEqual(done.status_code, 302)
        self.assertEqual(self.get(self.one).topic.name, "Zed")

    def test_a_reader_gets_403(self):
        from accounts.models import User

        reader = User.objects.create_user("reader", password="x")
        join_main(reader, "reader")
        self.client.force_login(reader)
        self.assertEqual(self.post().status_code, 403)
