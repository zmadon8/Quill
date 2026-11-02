"""Undo by action group (service layer)."""
import uuid

from diary import services as svc
from diary.models import Item, Section, Subtopic, Topic, TrashBatch, VersionHistory
from diary.tests.service_helpers import ServiceTestCase

BASE = [("(1)", "one"), ("(2)", "two"), ("(a)", "S"), ("(1)", "three"), ("(2)", "four")]


class UndoTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.build_topic()
        self.run_items = [self.one, self.two, self.sec, self.three, self.four]

    def state(self):
        rows = []
        for model in (Topic, Subtopic, Section, Item):
            for obj in model._base_manager.order_by("pk"):
                rows.append((model.__name__, obj.pk, obj.deleted_at is None, obj.position, obj.delete_batch))
        return rows

    def test_undo_an_edit_and_redo_it(self):
        edited = svc.edit(self.profile, self.user, "item", self.one.pk, {"text": "uno"}, 1)
        undone = svc.undo_group(self.profile, self.user, edited.group)
        self.assertTrue(undone.changed)
        self.assertNotEqual(undone.group, edited.group)
        item = self.get(self.one)
        self.assertEqual((item.text, item.version), ("one", 3))
        self.assertEqual(self.history_kinds(self.one), ["create", "edit", "restore"])
        redone = svc.undo_group(self.profile, self.user, undone.group)
        self.assertEqual((self.get(self.one).text, self.get(self.one).version), ("uno", 4))
        self.assertIsNotNone(redone.group)

    def test_undo_moving_a_section_brings_back_the_numbers(self):
        other = self.make("topic", ("subject", self.subject.pk), name="Other")
        moved = svc.move(self.profile, self.user, "section", self.sec.pk, ("topic", other.pk))
        self.assertEqual(self.numbered(other), [("(a)", "S")])
        svc.undo_group(self.profile, self.user, moved.group)
        self.assertEqual(self.numbered(self.topic), BASE)
        self.assertEqual(self.numbered(other), [])
        self.assertEqual(self.positions(self.run_items), [1, 2, 3, 4, 5])
        sec = self.get(self.sec)
        self.assertEqual((sec.topic_id, sec.subject_id, sec.subtopic_id), (self.topic.pk, None, None))

    def test_undo_deleting_a_section_brings_back_the_numbers(self):
        deleted = svc.delete(self.profile, self.user, "section", self.sec.pk)
        self.assertEqual(self.numbered(self.topic)[2], ("(3)", "three"))
        svc.undo_group(self.profile, self.user, deleted.group)
        self.assertEqual(self.numbered(self.topic), BASE)
        self.assertIsNone(self.get(self.sec).deleted_at)
        self.assertIsNone(self.get(self.sec).delete_batch)

    def test_undo_a_reorder(self):
        shifted = svc.shift(self.profile, self.user, "section", self.sec.pk, -1)
        self.assertNotEqual(self.numbered(self.topic), BASE)
        svc.undo_group(self.profile, self.user, shifted.group)
        self.assertEqual(self.numbered(self.topic), BASE)
        self.assertEqual(self.positions(self.run_items), [1, 2, 3, 4, 5])

    def test_undo_a_create_removes_it_and_closes_the_gap(self):
        created = svc.create(self.profile, self.user, "item", ("topic", self.topic.pk), index=0, text="new")
        self.assertEqual(self.numbered(self.topic)[0], ("(1)", "new"))
        undone = svc.undo_group(self.profile, self.user, created.group)
        self.assertIsNotNone(self.get(created.record).deleted_at)
        self.assertEqual(self.numbered(self.topic), BASE)
        self.assertEqual(self.positions(self.run_items), [1, 2, 3, 4, 5])
        svc.undo_group(self.profile, self.user, undone.group)
        self.assertIsNone(self.get(created.record).deleted_at)
        self.assertEqual(self.numbered(self.topic)[0], ("(1)", "new"))
        self.assertEqual(len(self.numbered(self.topic)), 6)

    def test_undo_deleting_a_heading_restores_the_whole_subtree(self):
        sub = self.make("subtopic", ("topic", self.topic.pk), name="Offer")
        self.make("item", ("subtopic", sub.pk), text="deep")
        before = self.state()
        deleted = svc.delete(self.profile, self.user, "topic", self.topic.pk)
        self.assertNotEqual(self.state(), before)
        svc.undo_group(self.profile, self.user, deleted.group)
        self.assertEqual(self.state(), before)

    def test_undo_a_restore_deletes_again(self):
        svc.delete(self.profile, self.user, "item", self.two.pk)
        restored = svc.restore(self.profile, self.user, "item", self.two.pk)
        svc.undo_group(self.profile, self.user, restored.group)
        self.assertIsNotNone(self.get(self.two).deleted_at)
        self.assertEqual(self.numbered(self.topic)[1], ("(a)", "S"))

    def test_undo_only_reverses_that_action(self):
        first = svc.edit(self.profile, self.user, "item", self.one.pk, {"text": "uno"})
        svc.edit(self.profile, self.user, "item", self.two.pk, {"text": "dos"})
        svc.undo_group(self.profile, self.user, first.group)
        self.assertEqual((self.get(self.one).text, self.get(self.two).text), ("one", "dos"))

    def test_undo_refuses_someone_elses_action(self):
        edited = svc.edit(self.profile, self.user, "item", self.one.pk, {"text": "uno"})
        with self.assertRaises(svc.Refused):
            svc.undo_group(self.profile, self.user2, edited.group)
        self.assertEqual(self.get(self.one).text, "uno")

    def test_undo_warns_when_the_record_changed_since_and_force_goes_ahead(self):
        first = svc.edit(self.profile, self.user, "item", self.one.pk, {"text": "a"})
        svc.edit(self.profile, self.user, "item", self.one.pk, {"text": "b"})
        with self.assertRaises(svc.UndoWarning) as caught:
            svc.undo_group(self.profile, self.user, first.group)
        self.assertEqual(
            caught.exception.changed,
            [{"type": "item", "id": self.one.pk, "label": "b", "expected_version": 2, "current_version": 3}],
        )
        self.assertEqual(self.get(self.one).text, "b")
        svc.undo_group(self.profile, self.user, first.group, force=True)
        self.assertEqual(self.get(self.one).text, "one")

    def test_undo_refused_when_someone_else_changed_it_since(self):
        first = svc.edit(self.profile, self.user, "item", self.one.pk, {"text": "a"})
        svc.edit(self.profile, self.user2, "item", self.one.pk, {"text": "theirs"})
        for force in (False, True):
            with self.assertRaises(svc.Refused):
                svc.undo_group(self.profile, self.user, first.group, force=force)
        self.assertEqual(self.get(self.one).text, "theirs")

    def test_undoing_the_same_action_twice_warns_instead_of_repeating(self):
        edited = svc.edit(self.profile, self.user, "item", self.one.pk, {"text": "uno"})
        svc.undo_group(self.profile, self.user, edited.group)
        with self.assertRaises(svc.UndoWarning):
            svc.undo_group(self.profile, self.user, edited.group)
        self.assertEqual(self.get(self.one).version, 3)

    def test_undo_after_permanent_delete_is_refused(self):
        created = svc.create(self.profile, self.user, "item", ("topic", self.topic.pk), text="temp")
        svc.delete(self.profile, self.user, "item", created.record.pk)
        svc.permanent_delete(self.profile, self.user, "item", created.record.pk)
        with self.assertRaises(svc.Refused):
            svc.undo_group(self.profile, self.user, created.group)

    def test_unknown_group(self):
        with self.assertRaises(svc.NotFound):
            svc.undo_group(self.profile, self.user, uuid.uuid4())

    def test_failing_undo_changes_nothing(self):
        deleted = svc.delete(self.profile, self.user, "topic", self.topic.pk)
        before = self.state()
        with self.failing_history(after=2):
            with self.assertRaises(RuntimeError):
                svc.undo_group(self.profile, self.user, deleted.group)
        self.assertEqual(self.state(), before)

    def test_undoing_a_subject_delete_whose_name_is_taken_changes_nothing(self):
        deleted = svc.delete(self.profile, self.user, "subject", self.subject.pk)
        self.make("subject", name="Contract")
        before = self.state()
        with self.assertRaises(svc.NameClash) as caught:
            svc.undo_group(self.profile, self.user, deleted.group)
        self.assertEqual(caught.exception.suggestion, "Contract (restored)")
        self.assertEqual(self.state(), before)
        self.assertIsNotNone(self.get(self.subject).deleted_at)

    def test_group_summary(self):
        edited = svc.edit(self.profile, self.user, "item", self.one.pk, {"text": "uno"})
        summary = svc.group_summary(self.profile, edited.group)
        self.assertEqual(summary["kinds"], ["edit"])
        self.assertEqual(summary["records"], [("item", self.one.pk)])
        self.assertEqual(svc.group_summary(self.other_profile, edited.group)["count"], 0)

    def test_every_action_in_one_call_shares_one_group(self):
        result = svc.shift(self.profile, self.user, "section", self.sec.pk, -1)
        groups = {
            row.group for row in VersionHistory.objects.filter(record_type__in=["item", "section"], version=2)
        }
        self.assertEqual(groups, {result.group})


class UndoStructuralRuleTests(ServiceTestCase):
    def test_undo_of_a_topic_delete_is_refused_once_the_subject_holds_subtopics(self):
        subject = self.make("subject", name="Contract")
        topic = self.make("topic", ("subject", subject.pk), name="Formation")
        deleted = svc.delete(self.profile, self.user, "topic", topic.pk)
        self.make("subtopic", ("subject", subject.pk), name="Direct")
        with self.assertRaises(svc.Refused):
            svc.undo_group(self.profile, self.user, deleted.group)
        self.assertIsNotNone(self.get(topic).deleted_at)
        self.assertIsNotNone(self.get(topic).delete_batch)

    def test_undo_of_a_move_is_refused_once_the_old_subject_holds_subtopics(self):
        old = self.make("subject", name="Contract")
        new = self.make("subject", name="Tort")
        topic = self.make("topic", ("subject", old.pk), name="Formation")
        moved = svc.move(self.profile, self.user, "topic", topic.pk, parent=("subject", new.pk))
        self.make("subtopic", ("subject", old.pk), name="Direct")
        with self.assertRaises(svc.Refused):
            svc.undo_group(self.profile, self.user, moved.group)
        self.assertEqual(self.get(topic).subject_id, new.pk)

    def test_undo_still_works_when_the_rules_hold(self):
        subject = self.make("subject", name="Contract")
        topic = self.make("topic", ("subject", subject.pk), name="Formation")
        deleted = svc.delete(self.profile, self.user, "topic", topic.pk)
        svc.undo_group(self.profile, self.user, deleted.group)
        self.assertIsNone(self.get(topic).deleted_at)
        self.assertEqual(TrashBatch.objects.count(), 0)

    def test_undo_of_a_topic_rename_restores_its_name_and_its_letter(self):
        from diary.reading import formats_for
        from diary.services.sequences import ident, labels, members

        subject = self.make("subject", name="Tort")
        apple = self.make("topic", ("subject", subject.pk), name="Apple")
        self.make("topic", ("subject", subject.pk), name="Pear")
        key = ("topic", "subject", subject.pk)

        def lettered():
            objs = members(self.profile.pk, key)
            gen = labels(key, objs, formats_for(None))
            return [(gen[ident(o)], o.name) for o in objs]

        renamed = svc.edit(self.profile, self.user, "topic", apple.pk, {"name": "Zulu"})
        self.assertEqual(lettered(), [("A", "Pear"), ("B", "Zulu")])
        svc.undo_group(self.profile, self.user, renamed.group)
        self.assertEqual(lettered(), [("A", "Apple"), ("B", "Pear")])
