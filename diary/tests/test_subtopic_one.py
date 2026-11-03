"""Round 14: Sub-topics that sit directly under a Subject are housed in a Topic called "1" (docs/DESIGN.md D82).

The mapping module diary/subtopic_one.py on a backup document (pure) and on the live database, and its order with
diary/topic_one.py (loose Items of such a Subject end up in the same Topic "1")."""
from django.apps import apps
from django.test import SimpleTestCase, TestCase

from diary import subtopic_one, topic_one
from diary.models import Item, Note, Subject, Subtopic, Topic, VersionHistory
from diary.tests.helpers import main_profile


def rec(model, pk, **fields):
    return {"model": model, "pk": pk, "fields": fields}


BASE = {"profile": 1, "created_by": None, "updated_by": None, "deleted_at": None, "delete_batch": None, "version": 1}


def document():
    place = {"subject": None, "topic": None, "subtopic": None}
    return {
        "diary.Subject": [rec("diary.subject", 1, name="Acts", **BASE), rec("diary.subject", 2, name="Tidy", **BASE)],
        "diary.Topic": [rec("diary.topic", 5, subject=2, name="Formation", position=1, original_line="", import_ref="", **BASE)],
        "diary.Subtopic": [
            rec("diary.subtopic", 1, subject=1, topic=None, name="Zeta", position=2, **BASE),
            rec("diary.subtopic", 2, subject=1, topic=None, name="Alpha", position=1, **BASE),
            rec("diary.subtopic", 3, subject=None, topic=5, name="Inside", position=1, **BASE),
        ],
        "diary.Item": [
            rec("diary.item", 1, **{**place, "subtopic": 1}, text="in zeta", position=1, kind="plain", **BASE),
            rec("diary.item", 2, **{**place, "subject": 1}, text="loose", position=1, kind="plain", **BASE),
        ],
        "diary.Section": [],
        "diary.VersionHistory": [],
    }


class DocumentTests(SimpleTestCase):
    def test_direct_subtopics_go_into_one_new_topic_1_in_order(self):
        doc = document()
        stats = subtopic_one.house_document(doc, "2026-01-01T00:00:00")
        self.assertEqual((stats["subjects_housed"], stats["topics_made"], stats["subtopics_moved"]), (1, 1, 2))
        topic = next(t for t in doc["diary.Topic"] if t["fields"]["subject"] == 1)
        self.assertEqual((topic["pk"], topic["fields"]["name"]), (6, "1"))
        subs = {r["pk"]: r["fields"] for r in doc["diary.Subtopic"]}
        self.assertEqual((subs[2]["topic"], subs[2]["subject"], subs[2]["position"], subs[2]["version"]), (6, None, 1, 2))
        self.assertEqual((subs[1]["topic"], subs[1]["position"]), (6, 2))
        self.assertEqual((subs[3]["topic"], subs[3]["version"]), (5, 1))  # already in a Topic: untouched
        self.assertEqual(doc["diary.Item"][0]["fields"]["subtopic"], 1)  # Items stay in their Sub-topic (same id)
        self.assertEqual({(r["fields"]["record_type"], r["fields"]["record_id"]) for r in doc["diary.VersionHistory"]},
                         {("topic", 6), ("subtopic", 1), ("subtopic", 2)})

    def test_then_the_loose_item_joins_the_same_topic_1(self):
        doc = document()
        subtopic_one.house_document(doc, "2026-01-01T00:00:00")
        stats = topic_one.house_document(doc, "2026-01-01T00:00:00")
        self.assertEqual((stats["topics_made"], stats["topics_reused"], stats["items_moved"]), (0, 1, 1))
        self.assertEqual(doc["diary.Item"][1]["fields"]["topic"], 6)

    def test_only_trashed_direct_subtopics_are_left_alone(self):
        doc = document()
        for r in doc["diary.Subtopic"][:2]:
            r["fields"]["deleted_at"] = "2025-01-01T00:00:00"
        stats = subtopic_one.house_document(doc, "2026-01-01T00:00:00")
        self.assertEqual(stats["subtopics_moved"], 0)
        self.assertEqual(doc["diary.Subtopic"][0]["fields"]["subject"], 1)

    def test_a_trashed_one_beside_a_live_one_moves_and_keeps_its_trash_state(self):
        doc = document()
        doc["diary.Subtopic"][0]["fields"].update(deleted_at="2025-01-01T00:00:00", delete_batch="b")
        subtopic_one.house_document(doc, "2026-01-01T00:00:00")
        gone = doc["diary.Subtopic"][0]["fields"]
        self.assertEqual((gone["topic"], gone["subject"], gone["deleted_at"]), (6, None, "2025-01-01T00:00:00"))

    def test_an_existing_topic_1_is_reused(self):
        doc = document()
        doc["diary.Topic"].append(rec("diary.topic", 9, subject=1, name="1", position=1, original_line="", import_ref="", **BASE))
        stats = subtopic_one.house_document(doc, "2026-01-01T00:00:00")
        self.assertEqual((stats["topics_made"], stats["topics_reused"]), (0, 1))
        self.assertEqual(doc["diary.Subtopic"][1]["fields"]["topic"], 9)

    def test_running_twice_changes_nothing_more(self):
        doc = document()
        subtopic_one.house_document(doc, "2026-01-01T00:00:00")
        again = subtopic_one.house_document(doc, "2026-01-02T00:00:00")
        self.assertEqual(again["subtopics_moved"], 0)

    def test_describe(self):
        doc = document()
        self.assertIn("2 Sub-topic(s)", subtopic_one.describe(subtopic_one.house_document(doc, "2026-01-01T00:00:00")))
        self.assertEqual(subtopic_one.describe(subtopic_one.new_stats()), "")


class DatabaseTests(TestCase):
    def setUp(self):
        self.profile = main_profile()
        kw = {"profile": self.profile}
        self.acts = Subject.objects.create(name="Acts", show_on_landing=False, **kw)
        self.zeta = Subtopic.objects.create(subject=self.acts, name="Zeta", position=1, **kw)
        self.item = Item.objects.create(subtopic=self.zeta, text="<p>in zeta</p>", position=1, **kw)
        self.loose = Item.objects.create(subject=self.acts, text="<p>loose</p>", position=1, **kw)
        self.note = Note.objects.create(subtopic=self.zeta, text="<p>n</p>", position=1, **kw)

    def test_the_live_database_is_housed_then_loose_items_follow(self):
        stats = subtopic_one.migrate_direct(apps)
        self.assertEqual((stats["topics_made"], stats["subtopics_moved"]), (1, 1))
        topic = Topic.objects.get(subject=self.acts)
        self.assertEqual(topic.name, "1")
        zeta = Subtopic.objects.get(pk=self.zeta.pk)
        self.assertEqual((zeta.subject_id, zeta.topic_id, zeta.version), (None, topic.pk, 2))
        self.assertEqual(Item.objects.get(pk=self.item.pk).subtopic_id, self.zeta.pk)
        self.assertEqual(Note.objects.get(pk=self.note.pk).subtopic_id, self.zeta.pk)
        self.assertTrue(VersionHistory.objects.filter(record_type="subtopic", record_id=self.zeta.pk, change_kind="migrate").exists())
        topic_one.migrate_loose(apps)
        self.assertEqual(Item.objects.get(pk=self.loose.pk).topic_id, topic.pk)
        self.assertEqual(Topic.objects.filter(subject=self.acts).count(), 1)

    def test_running_twice_changes_nothing_more(self):
        subtopic_one.migrate_direct(apps)
        rows = VersionHistory.objects.count()
        self.assertEqual(subtopic_one.migrate_direct(apps)["subtopics_moved"], 0)
        self.assertEqual(VersionHistory.objects.count(), rows)
