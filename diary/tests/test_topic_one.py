"""Round 10, item 6: Items not housed in a Topic are housed in a Topic called "1" (docs/DESIGN.md D61).

Owner: "Any items which are not housed in a Topic will automatically be housed in a topic called \u201c1\u201d".
The service rule (add, quick-add, add-after, Move to, Restore), the mapping module diary/topic_one.py (pure rules,
old backup files) and data migration 0017 on a database at the schema before it."""
from unittest import mock

from django.db import connection
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TransactionTestCase
from django.utils import timezone

from diary import services as svc
from diary import topic_one
from diary.models import Item, Note, Section, Topic, VersionHistory
from diary.tests.service_helpers import ServiceTestCase

BEFORE = [("diary", "0016_remove_nested_items")]


class ServiceRuleTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.subject = self.make("subject", name="Tort")

    def topics(self, subject=None):
        return list(Topic.objects.filter(subject=subject or self.subject, deleted_at__isnull=True))

    def test_an_item_added_under_a_subject_goes_into_topic_1_made_on_demand(self):
        item = self.make("item", ("subject", self.subject.pk), text="first")
        topic = self.topics()[0]
        self.assertEqual(topic.name, "1")
        self.assertEqual((self.get(item).topic_id, self.get(item).subject_id), (topic.pk, None))
        self.assertEqual(self.history_kinds(topic), ["create"])
        self.assertEqual(self.history(topic)[0].group, self.history(item)[0].group)  # one Undo step

    def test_topic_1_is_reused_and_sections_go_there_too(self):
        first = self.make("item", ("subject", self.subject.pk), text="first")
        section = self.make("section", ("subject", self.subject.pk), name="Part")
        second = self.make("item", ("subject", self.subject.pk), text="second", index=0)
        self.assertEqual(len(self.topics()), 1)
        topic = self.topics()[0]
        self.assertEqual({self.get(o).topic_id for o in (first, section, second)}, {topic.pk})
        self.assertEqual(self.numbered(topic)[0], ("(1)", "second"))

    def test_an_existing_topic_called_1_is_reused_whatever_its_case_and_neighbours(self):
        mine = self.make("topic", ("subject", self.subject.pk), name="1")
        self.make("topic", ("subject", self.subject.pk), name="Duty")
        item = self.make("item", ("subject", self.subject.pk), text="x")
        self.assertEqual(self.get(item).topic_id, mine.pk)
        self.assertEqual(len(self.topics()), 2)

    def test_a_subtopic_and_an_item_added_to_a_subject_share_one_topic_1(self):
        # D81, D82: Subjects under Other Subjects follow the same rule, and there is one Topic "1" per Subject.
        sub = self.make("subtopic", ("subject", self.subject.pk), name="Direct")
        item = self.make("item", ("subject", self.subject.pk), text="goes to Topic 1")
        self.assertEqual(len(self.topics()), 1)
        topic = self.topics()[0]
        self.assertEqual(topic.name, "1")
        self.assertEqual((self.get(item).subject_id, self.get(item).topic_id), (None, topic.pk))
        self.assertEqual((self.get(sub).subject_id, self.get(sub).topic_id), (None, topic.pk))

    def test_notes_are_not_housed(self):
        note = self.make("note", ("subject", self.subject.pk), text="about the Subject")
        self.assertEqual((self.get(note).subject_id, self.get(note).topic_id), (self.subject.pk, None))
        self.assertEqual(self.topics(), [])

    def test_topics_headings_and_items_in_topics_are_not_touched(self):
        topic = self.make("topic", ("subject", self.subject.pk), name="Duty")
        item = self.make("item", ("topic", topic.pk), text="here")
        self.assertEqual(self.get(item).topic_id, topic.pk)
        self.assertEqual([t.name for t in self.topics()], ["Duty"])

    def test_the_new_topic_does_not_disturb_the_stored_order_of_the_others(self):
        a = self.make("topic", ("subject", self.subject.pk), name="Zed")
        self.make("item", ("subject", self.subject.pk), text="x")
        self.assertEqual(self.get(a).position, 1)
        self.assertEqual(Topic.objects.get(subject=self.subject, name="1").position, 2)

    def test_move_to_a_subject_lands_in_its_topic_1(self):
        other = self.make("subject", name="Contract")
        topic = self.make("topic", ("subject", other.pk), name="Formation")
        item = self.make("item", ("topic", topic.pk), text="moves")
        svc.move(self.profile, self.user, "item", item.pk, ("subject", self.subject.pk))
        moved = self.get(item)
        self.assertEqual((moved.subject_id, Topic.objects.get(pk=moved.topic_id).name), (None, "1"))
        self.assertEqual(Topic.objects.get(pk=moved.topic_id).subject_id, self.subject.pk)

    def test_move_to_a_subject_with_direct_subtopics_lands_in_its_topic_1(self):
        self.make("subtopic", ("subject", self.subject.pk), name="Direct")
        item = self.make("item", ("subject", self.make("subject", name="Other").pk), text="x")
        svc.move(self.profile, self.user, "item", item.pk, ("subject", self.subject.pk))
        moved = self.get(item)
        self.assertEqual((moved.subject_id, Topic.objects.get(pk=moved.topic_id).name), (None, "1"))

    def test_the_move_preview_writes_nothing(self):
        other = self.make("subject", name="Contract")
        topic = self.make("topic", ("subject", other.pk), name="Formation")
        item = self.make("item", ("topic", topic.pk), text="moves")
        before = Topic.objects.count()
        svc.preview_move(self.profile, self.user, "item", item.pk, ("subject", self.subject.pk))
        self.assertEqual(Topic.objects.count(), before)

    def test_restoring_a_loose_item_from_trash_puts_it_in_topic_1(self):
        item = Item.objects.create(profile=self.profile, subject=self.subject, text="loose", position=1)
        svc.delete(self.profile, self.user, "item", item.pk)
        svc.restore(self.profile, self.user, "item", item.pk)
        restored = self.get(item)
        self.assertIsNone(restored.deleted_at)
        self.assertEqual((restored.subject_id, Topic.objects.get(pk=restored.topic_id).name), (None, "1"))

    def test_undo_of_the_add_takes_the_item_and_the_new_topic_out_together(self):
        result = svc.create(self.profile, self.user, "item", parent=("subject", self.subject.pk), text="x")
        svc.undo_group(self.profile, self.user, result.group)
        self.assertEqual(self.topics(), [])
        self.assertFalse(Item.objects.filter(deleted_at__isnull=True, topic__subject=self.subject).exists())

    def test_nothing_is_made_when_the_subject_is_in_another_profile(self):
        foreign = self.make("subject", profile=self.other_profile, name="Foreign")
        with self.assertRaises(svc.NotFound):
            svc.create(self.profile, self.user, "item", parent=("subject", foreign.pk), text="x")
        self.assertEqual(Topic.objects.filter(subject=foreign).count(), 0)


def rec(model, pk, **fields):
    return {"model": model, "pk": pk, "fields": fields}


def document():
    base = {"profile": 1, "created_by": None, "updated_by": None, "deleted_at": None, "delete_batch": None, "version": 1}
    place = {"subject": None, "topic": None, "subtopic": None}
    return {
        "diary.Subject": [
            rec("diary.subject", 1, name="Plain", **base),
            rec("diary.subject", 2, name="Other", **base),
            rec("diary.subject", 3, name="Tidy", **base),
        ],
        "diary.Topic": [rec("diary.topic", 7, subject=3, name="Formation", position=4, original_line="", import_ref="",
                            **base)],
        "diary.Subtopic": [rec("diary.subtopic", 1, subject=2, topic=None, name="Direct", position=1, **base)],
        "diary.Item": [
            rec("diary.item", 1, **{**place, "subject": 1}, text="b", position=2, kind="plain", **base),
            rec("diary.item", 2, **{**place, "subject": 1}, text="a", position=1, kind="plain", **base),
            rec("diary.item", 3, **{**place, "subject": 2}, text="stays", position=1, kind="plain", **base),
            rec("diary.item", 4, **{**place, "topic": 7}, text="in a topic", position=1, kind="plain", **base),
        ],
        "diary.Section": [rec("diary.section", 1, **{**place, "subject": 1}, name="S", position=2, **base)],
        "diary.VersionHistory": [],
    }


class DocumentTests(SimpleTestCase):
    def test_loose_records_move_in_order_into_a_new_topic_1(self):
        doc = document()
        stats = topic_one.house_document(doc, "2026-01-01T00:00:00")
        self.assertEqual((stats["subjects_housed"], stats["topics_made"], stats["items_moved"],
                          stats["sections_moved"], stats["left_under_subjects_with_subtopics"]), (1, 1, 2, 1, 1))
        topic = next(t for t in doc["diary.Topic"] if t["fields"]["subject"] == 1)
        self.assertEqual((topic["fields"]["name"], topic["fields"]["position"], topic["pk"]), ("1", 1, 8))
        by_pk = {r["pk"]: r["fields"] for r in doc["diary.Item"]}
        self.assertEqual((by_pk[2]["topic"], by_pk[2]["subject"], by_pk[2]["position"]), (8, None, 1))  # "a" came first
        self.assertEqual(by_pk[1]["position"], 3)  # the Section sits between them: position 2 before, (a)=1, S=2, b=3
        self.assertEqual(doc["diary.Section"][0]["fields"]["position"], 2)
        self.assertEqual((by_pk[3]["subject"], by_pk[3]["topic"]), (2, None))  # the Subject with a Sub-topic keeps it
        self.assertEqual(by_pk[4]["topic"], 7)
        self.assertEqual(by_pk[1]["version"], 2)

    def test_history_rows_are_added(self):
        doc = document()
        topic_one.house_document(doc, "2026-01-01T00:00:00")
        rows = doc["diary.VersionHistory"]
        self.assertEqual({(r["fields"]["record_type"], r["fields"]["record_id"]) for r in rows},
                         {("topic", 8), ("item", 1), ("item", 2), ("section", 1)})
        self.assertEqual({r["fields"]["change_kind"] for r in rows}, {"migrate"})

    def test_an_existing_topic_1_is_reused_and_records_follow_its_own(self):
        doc = document()
        doc["diary.Topic"].append(rec("diary.topic", 9, subject=1, name="1", position=1, original_line="", import_ref="",
                                      profile=1, created_by=None, updated_by=None, deleted_at=None, delete_batch=None,
                                      version=1))
        doc["diary.Item"].append(rec("diary.item", 5, subject=None, topic=9, subtopic=None, text="there", position=1,
                                     kind="plain", profile=1, created_by=None, updated_by=None, deleted_at=None,
                                     delete_batch=None, version=1))
        stats = topic_one.house_document(doc, "2026-01-01T00:00:00")
        self.assertEqual((stats["topics_made"], stats["topics_reused"]), (0, 1))
        by_pk = {r["pk"]: r["fields"] for r in doc["diary.Item"]}
        self.assertEqual((by_pk[2]["topic"], by_pk[2]["position"]), (9, 2))  # after the record already in Topic "1"

    def test_a_trashed_record_moves_with_the_live_ones_and_keeps_its_trash_state(self):
        doc = document()
        doc["diary.Item"][0]["fields"].update(deleted_at="2025-01-01T00:00:00", delete_batch="b")
        topic_one.house_document(doc, "2026-01-01T00:00:00")
        trashed = doc["diary.Item"][0]["fields"]
        self.assertEqual((trashed["topic"], trashed["deleted_at"], trashed["delete_batch"], trashed["position"]),
                         (8, "2025-01-01T00:00:00", "b", 2))

    def test_a_subject_with_only_trashed_loose_records_is_left_alone(self):
        doc = document()
        for r in doc["diary.Item"][:2] + doc["diary.Section"]:
            r["fields"]["deleted_at"] = "2025-01-01T00:00:00"
        stats = topic_one.house_document(doc, "2026-01-01T00:00:00")
        self.assertEqual((stats["topics_made"], stats["items_moved"]), (0, 0))
        self.assertEqual(doc["diary.Item"][0]["fields"]["subject"], 1)

    def test_a_trashed_subject_gets_a_trashed_topic_1(self):
        doc = document()
        doc["diary.Subject"][0]["fields"].update(deleted_at="2025-01-01T00:00:00", delete_batch="b")
        topic_one.house_document(doc, "2026-01-01T00:00:00")
        topic = next(t for t in doc["diary.Topic"] if t["fields"]["subject"] == 1)
        self.assertEqual((topic["fields"]["deleted_at"], topic["fields"]["delete_batch"]), ("2025-01-01T00:00:00", "b"))

    def test_housed_file_is_left_alone_the_second_time(self):
        doc = document()
        topic_one.house_document(doc, "2026-01-01T00:00:00")
        again = topic_one.house_document(doc, "2026-01-02T00:00:00")
        self.assertEqual((again["subjects_housed"], again["items_moved"]), (0, 0))

    def test_describe(self):
        doc = document()
        stats = topic_one.house_document(doc, "2026-01-01T00:00:00")
        self.assertIn("2 Item(s) and 1 Section(s)", topic_one.describe(stats))
        self.assertEqual(topic_one.describe(topic_one.new_stats()), "")


class MigrationTests(TransactionTestCase):
    """Data migration 0017 on a database at the schema before it."""

    def setUp(self):
        executor = MigrationExecutor(connection)
        executor.migrate(BEFORE)  # an empty database: reversing 0017 is allowed
        self.old_apps = executor.loader.project_state(BEFORE).apps
        self.build()

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def model(self, name):
        return self.old_apps.get_model("diary", name)

    def build(self):
        from accounts.models import Profile  # the real model: the accounts table has columns the old state lacks

        self.profile = Profile.objects.create(program="diary", name="Mig")
        kw = {"profile_id": self.profile.pk}
        Subject, Topic_, Subtopic, Item_, Section_, Note_ = (
            self.model(n) for n in ("Subject", "Topic", "Subtopic", "Item", "Section", "Note"))
        self.plain = Subject.objects.create(name="Plain", **kw)
        self.holder = Subject.objects.create(name="Holder", **kw)
        self.tidy = Subject.objects.create(name="Tidy", **kw)
        Subtopic.objects.create(subject=self.holder, name="Direct", **kw)
        self.formation = Topic_.objects.create(subject=self.tidy, name="Formation", position=5, **kw)
        self.i1 = Item_.objects.create(subject=self.plain, text="<p>b</p>", position=2, **kw)
        self.i2 = Item_.objects.create(subject=self.plain, text="<p>a</p>", position=1, **kw)
        self.sec = Section_.objects.create(subject=self.plain, name="S", position=3, **kw)
        self.gone = Item_.objects.create(subject=self.plain, text="<p>old</p>", position=4, deleted_at=timezone.now(), **kw)
        self.kept = Item_.objects.create(subject=self.holder, text="<p>stays</p>", position=1, **kw)
        self.inside = Item_.objects.create(topic=self.formation, text="<p>in</p>", position=1, **kw)
        self.note = Note_.objects.create(subject=self.plain, text="about", position=1, **kw)

    def test_every_rule(self):
        counts = {n: self.model(n).objects.count() for n in ("Item", "Section", "Note")}
        stats = topic_one.migrate_loose(self.old_apps)
        Item_, Topic_, Section_, Note_ = (self.model(n) for n in ("Item", "Topic", "Section", "Note"))
        self.assertEqual({n: self.model(n).objects.count() for n in ("Item", "Section", "Note")}, counts)
        self.assertEqual((stats["topics_made"], stats["items_moved"], stats["sections_moved"],
                          stats["left_under_subjects_with_subtopics"]), (1, 3, 1, 1))
        topic = Topic_.objects.get(subject_id=self.plain.pk)
        self.assertEqual((topic.name, topic.position, topic.version, topic.deleted_at), ("1", 1, 1, None))
        order = lambda obj: (obj.topic_id, obj.subject_id, obj.position, obj.version)  # noqa: E731
        self.assertEqual(order(Item_.objects.get(pk=self.i2.pk)), (topic.pk, None, 1, 2))
        self.assertEqual(order(Item_.objects.get(pk=self.i1.pk)), (topic.pk, None, 2, 2))
        self.assertEqual(order(Section_.objects.get(pk=self.sec.pk)), (topic.pk, None, 3, 2))
        gone = Item_.objects.get(pk=self.gone.pk)  # in Trash: moves, keeps its position and trash state
        self.assertEqual((gone.topic_id, gone.position, gone.deleted_at is None), (topic.pk, 4, False))
        kept = Item_.objects.get(pk=self.kept.pk)
        self.assertEqual((kept.subject_id, kept.topic_id, kept.version), (self.holder.pk, None, 1))
        self.assertEqual(Item_.objects.get(pk=self.inside.pk).topic_id, self.formation.pk)
        note = Note_.objects.get(pk=self.note.pk)
        self.assertEqual((note.subject_id, note.topic_id), (self.plain.pk, None))  # Notes are not moved
        history = self.model("VersionHistory").objects.filter(change_kind="migrate")
        self.assertEqual({(r.record_type, r.record_id) for r in history},
                         {("topic", topic.pk), ("item", self.i1.pk), ("item", self.i2.pk), ("item", self.gone.pk),
                          ("section", self.sec.pk)})
        self.assertFalse(Item_.objects.filter(subject_id=self.plain.pk).exists())

    def test_a_failed_check_rolls_everything_back(self):
        Item_ = self.model("Item")
        with mock.patch.object(topic_one, "_counts", side_effect=[
            {"items": 6, "sections": 1, "topics": 1}, {"items": 5, "sections": 1, "topics": 2}
        ]):
            with self.assertRaises(topic_one.MigrationVerificationError):
                topic_one.migrate_loose(self.old_apps)
        self.assertEqual(Item_.objects.get(pk=self.i1.pk).subject_id, self.plain.pk)
        self.assertFalse(self.model("Topic").objects.filter(subject_id=self.plain.pk).exists())
        self.assertFalse(self.model("VersionHistory").objects.filter(change_kind="migrate").exists())

    def test_running_twice_changes_nothing_more(self):
        topic_one.migrate_loose(self.old_apps)
        history = self.model("VersionHistory").objects.count()
        stats = topic_one.migrate_loose(self.old_apps)
        self.assertEqual((stats["topics_made"], stats["items_moved"]), (0, 0))
        self.assertEqual(self.model("VersionHistory").objects.count(), history)

    def test_an_existing_topic_1_is_reused(self):
        existing = self.model("Topic").objects.create(subject=self.plain, name="1", position=1, profile_id=self.profile.pk)
        self.model("Item").objects.create(topic=existing, text="<p>there</p>", position=1, profile_id=self.profile.pk)
        stats = topic_one.migrate_loose(self.old_apps)
        self.assertEqual((stats["topics_made"], stats["topics_reused"]), (0, 1))
        self.assertEqual(self.model("Item").objects.get(pk=self.i2.pk).position, 2)  # after the one already there

    def test_a_deleted_subject_gets_a_deleted_topic_1(self):
        stamp = timezone.now()
        self.model("Subject").objects.filter(pk=self.plain.pk).update(deleted_at=stamp)
        topic_one.migrate_loose(self.old_apps)
        topic = self.model("Topic").objects.get(subject_id=self.plain.pk)
        self.assertEqual(topic.deleted_at, stamp)

    def test_the_real_migration_file_applies_and_the_final_schema_holds(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        topic = Topic.objects.get(subject_id=self.plain.pk)
        self.assertEqual(topic.name, "1")
        self.assertEqual(Item.objects.filter(topic=topic).count(), 3)
        self.assertEqual(Section.objects.filter(topic=topic).count(), 1)
        self.assertTrue(Note.objects.filter(subject_id=self.plain.pk).exists())
        self.assertTrue(VersionHistory.objects.filter(change_kind="migrate", record_type="topic").exists())

    def test_reverse_is_refused_while_any_item_exists(self):
        import importlib

        module = importlib.import_module("diary.migrations.0017_house_loose_in_topic_one")
        with self.assertRaises(IrreversibleError):
            module.house_backwards(self.old_apps, None)
        self.model("Note").objects.all().delete()
        self.model("Item").objects.all().delete()
        self.model("Section").objects.all().delete()
        self.assertIsNone(module.house_backwards(self.old_apps, None))
