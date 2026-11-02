"""Delete, Trash batches, restore edge cases, permanent delete and Note link preservation (service layer)."""
from unittest import mock

from diary import services as svc
from diary.models import Case, Item, Note, NoteLink, Section, Subject, Subtopic, Topic, TrashBatch, VersionHistory
from diary.services.sequences import members
from diary.tests.service_helpers import ServiceTestCase


class TrashTestCase(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.subject = self.make("subject", name="Contract")
        self.t1 = self.make("topic", ("subject", self.subject.pk), name="Formation")
        self.t2 = self.make("topic", ("subject", self.subject.pk), name="Breach")
        self.st = self.make("subtopic", ("topic", self.t1.pk), name="Offer")
        parent = ("subtopic", self.st.pk)
        self.i1 = self.make("item", parent, text="i1")
        self.i2 = self.make("item", parent, text="i2")
        self.sec = self.make("section", parent, name="Sec")
        self.i3 = self.make("item", parent, text="i3")
        self.multi = self.make("item", ("topic", self.t1.pk), text="m")
        self.case = self.make("case", ("item", self.multi.pk), citation="A v B")
        self.note = self.make("note", ("item", self.i1.pk), text="see")
        self.t1_tree = [self.t1, self.st, self.i1, self.i2, self.sec, self.i3, self.multi, self.case, self.note]

    def deleted(self, objs):
        return [self.get(o).deleted_at is not None for o in objs]


class DeleteTests(TrashTestCase):
    def test_deleting_a_heading_trashes_its_whole_subtree_as_one_batch(self):
        result = svc.delete(self.profile, self.user, "topic", self.t1.pk)
        self.assertTrue(result.changed)
        self.assertEqual(result.info["count"], 9)
        batch = TrashBatch.objects.get()
        self.assertEqual(result.info["batch"], batch.pk)
        self.assertEqual((batch.root_type, batch.root_id, batch.label), ("topic", self.t1.pk, "Formation"))
        self.assertEqual((batch.profile_id, batch.created_by), (self.profile.pk, self.user))
        self.assertTrue(all(self.deleted(self.t1_tree)))
        self.assertEqual({self.get(o).delete_batch for o in self.t1_tree}, {batch.pk})
        for obj in self.t1_tree:
            last = self.history(obj)[-1]
            self.assertEqual((last.change_kind, last.group), ("delete", result.group))
        # Everything else is untouched.
        self.assertIsNone(self.get(self.t2).deleted_at)
        self.assertIsNone(self.get(self.subject).deleted_at)
        self.assertEqual(self.get(self.t2).version, 1)

    def test_deleting_twice_is_harmless(self):
        svc.delete(self.profile, self.user, "topic", self.t1.pk)
        count = VersionHistory.objects.count()
        again = svc.delete(self.profile, self.user, "topic", self.t1.pk, expected_version=1)
        self.assertFalse(again.changed)
        self.assertEqual(TrashBatch.objects.count(), 1)
        self.assertEqual(VersionHistory.objects.count(), count)

    def test_items_deleted_earlier_keep_their_own_batch(self):
        svc.delete(self.profile, self.user, "item", self.i2.pk)
        first = self.get(self.i2).delete_batch
        svc.delete(self.profile, self.user, "topic", self.t1.pk)
        self.assertEqual(self.get(self.i2).delete_batch, first)
        self.assertNotEqual(self.get(self.i1).delete_batch, first)
        self.assertEqual(TrashBatch.objects.count(), 2)

    def test_deleting_a_nested_item_takes_its_children_and_an_item_its_citations(self):
        nested = self.make("item", ("topic", self.t2.pk), kind="nested", text="n")
        child = self.make("item", ("item", nested.pk), text="child")
        svc.delete(self.profile, self.user, "item", nested.pk)
        svc.delete(self.profile, self.user, "item", self.multi.pk)
        self.assertTrue(all(self.deleted([nested, child, self.multi, self.case])))

    def test_deleting_a_note_takes_its_links_and_never_deletes_the_target(self):
        link = svc.add_link(self.profile, self.user, self.note.pk, ("item", self.i3.pk)).record
        svc.delete(self.profile, self.user, "note", self.note.pk)
        self.assertIsNotNone(self.get(link).deleted_at)
        self.assertIsNone(self.get(self.i3).deleted_at)

    def test_delete_a_stale_version_is_refused(self):
        svc.edit(self.profile, self.user, "item", self.i1.pk, {"text": "changed"})
        with self.assertRaises(svc.Conflict):
            svc.delete(self.profile, self.user, "item", self.i1.pk, expected_version=1)
        self.assertIsNone(self.get(self.i1).deleted_at)

    def test_delete_failing_half_way_changes_nothing(self):
        with self.failing_history(after=3):
            with self.assertRaises(RuntimeError):
                svc.delete(self.profile, self.user, "topic", self.t1.pk)
        self.assertFalse(any(self.deleted(self.t1_tree)))
        self.assertEqual(TrashBatch.objects.count(), 0)


class RestoreTests(TrashTestCase):
    def test_restore_brings_back_exactly_that_batch_in_place(self):
        svc.delete(self.profile, self.user, "item", self.i2.pk)
        svc.delete(self.profile, self.user, "topic", self.t1.pk)
        result = svc.restore(self.profile, self.user, "topic", self.t1.pk)
        self.assertEqual(result.info["count"], 8)
        self.assertEqual(self.deleted(self.t1_tree), [o is self.i2 for o in self.t1_tree])
        self.assertEqual(self.numbered(self.st), [("(1)", "i1"), ("(a)", "Sec"), ("(1)", "i3")])
        self.assertEqual(self.positions([self.i1, self.sec, self.i3]), [1, 2, 3])
        # The earlier deleted item is restored on its own, back between i1 and Sec.
        svc.restore(self.profile, self.user, "item", self.i2.pk)
        self.assertEqual(
            self.numbered(self.st), [("(1)", "i1"), ("(2)", "i2"), ("(a)", "Sec"), ("(1)", "i3")]
        )
        self.assertEqual(self.positions([self.i1, self.i2, self.sec, self.i3]), [1, 2, 3, 4])

    def test_a_restored_heading_returns_to_its_alphabetical_place_and_keeps_its_stored_position(self):
        extra = self.make("topic", ("subject", self.subject.pk), name="Capacity")
        svc.delete(self.profile, self.user, "topic", self.t2.pk)
        stored = [self.get(x).position for x in (self.t1, extra)]
        svc.restore(self.profile, self.user, "topic", self.t2.pk)
        names = [t.name for t in members(self.profile.pk, ("topic", "subject", self.subject.pk))]
        self.assertEqual(names, ["Breach", "Capacity", "Formation"])
        self.assertEqual(self.get(self.t2).position, 2)
        self.assertEqual([self.get(x).position for x in (self.t1, extra)], stored)
        self.assertEqual(self.history_kinds(self.t1), ["create"])

    def test_a_new_heading_never_reuses_the_stored_position_of_a_trashed_one(self):
        svc.delete(self.profile, self.user, "topic", self.t2.pk)  # t2 held stored position 2
        extra = self.make("topic", ("subject", self.subject.pk), name="Capacity")
        svc.restore(self.profile, self.user, "topic", self.t2.pk)
        stored = [self.get(x).position for x in (self.t1, self.t2, extra)]
        self.assertEqual(len(set(stored)), 3)

    def test_restore_writes_history_and_bumps_versions(self):
        svc.delete(self.profile, self.user, "topic", self.t1.pk)
        result = svc.restore(self.profile, self.user, "topic", self.t1.pk)
        self.assertEqual(self.history_kinds(self.i1), ["create", "delete", "restore"])
        self.assertEqual(self.get(self.i1).version, 3)
        self.assertEqual(self.history(self.i1)[-1].group, result.group)
        self.assertIsNone(self.get(self.i1).delete_batch)
        self.assertIsNone(self.get(self.t1).deleted_at)

    def test_restoring_a_live_record_changes_nothing(self):
        result = svc.restore(self.profile, self.user, "topic", self.t2.pk)
        self.assertFalse(result.changed)
        self.assertEqual(self.get(self.t2).version, 1)

    def test_restore_twice_is_harmless(self):
        svc.delete(self.profile, self.user, "topic", self.t1.pk)
        svc.restore(self.profile, self.user, "topic", self.t1.pk)
        count = VersionHistory.objects.count()
        self.assertFalse(svc.restore(self.profile, self.user, "topic", self.t1.pk).changed)
        self.assertEqual(VersionHistory.objects.count(), count)

    def test_parent_in_trash_is_reported_with_the_chain(self):
        svc.delete(self.profile, self.user, "topic", self.t1.pk)
        with self.assertRaises(svc.ParentInTrash) as caught:
            svc.restore(self.profile, self.user, "item", self.i1.pk)
        self.assertEqual(
            caught.exception.chain, [("topic", self.t1.pk, "Formation"), ("subtopic", self.st.pk, "Offer")]
        )
        self.assertIsNotNone(self.get(self.i1).deleted_at)

    def test_restoring_the_parent_chain_restores_only_the_chain_and_the_record(self):
        svc.delete(self.profile, self.user, "topic", self.t1.pk)
        svc.restore(self.profile, self.user, "item", self.i1.pk, restore_parents=True)
        self.assertFalse(any(self.deleted([self.t1, self.st, self.i1, self.note])))
        self.assertTrue(all(self.deleted([self.i2, self.sec, self.i3, self.multi, self.case])))
        self.assertEqual(self.numbered(self.st), [("(1)", "i1")])
        topics = [t.name for t in members(self.profile.pk, ("topic", "subject", self.subject.pk))]
        self.assertEqual(topics, ["Breach", "Formation"])  # alphabetical, not stored (Word) order
        # The rest of the batch can still be restored one by one.
        svc.restore(self.profile, self.user, "item", self.i3.pk)
        self.assertEqual(self.numbered(self.st), [("(1)", "i1"), ("(2)", "i3")])

    def test_subject_name_clash_asks_for_a_new_name(self):
        svc.delete(self.profile, self.user, "subject", self.subject.pk)
        again = self.make("subject", name="Contract")
        with self.assertRaises(svc.NameClash) as caught:
            svc.restore(self.profile, self.user, "subject", self.subject.pk)
        self.assertEqual(caught.exception.suggestion, "Contract (restored)")
        self.assertEqual(caught.exception.record_type, "subject")
        self.assertIsNotNone(self.get(self.subject).deleted_at)
        self.assertIsNotNone(self.get(self.t1).deleted_at)
        with self.assertRaises(svc.ValidationFailed):
            svc.restore(self.profile, self.user, "subject", self.subject.pk, new_name="CONTRACT")
        with self.assertRaises(svc.ValidationFailed):
            svc.restore(self.profile, self.user, "subject", self.subject.pk, new_name="   ")
        svc.restore(self.profile, self.user, "subject", self.subject.pk, new_name="Contract (old)")
        self.assertEqual(self.get(self.subject).name, "Contract (old)")
        self.assertIsNone(self.get(self.t1).deleted_at)
        self.assertEqual(self.get(again).name, "Contract")
        self.assertEqual(self.history(self.subject)[-1].snapshot["name"], "Contract (old)")

    def test_topic_name_clash_asks_for_a_new_name(self):
        svc.delete(self.profile, self.user, "topic", self.t2.pk)
        self.make("topic", ("subject", self.subject.pk), name="breach")
        with self.assertRaises(svc.NameClash) as caught:
            svc.restore(self.profile, self.user, "topic", self.t2.pk)
        self.assertEqual((caught.exception.record_type, caught.exception.suggestion), ("topic", "Breach (restored)"))
        svc.restore(self.profile, self.user, "topic", self.t2.pk, new_name="Breach of contract")
        self.assertEqual(self.get(self.t2).name, "Breach of contract")
        self.assertIsNone(self.get(self.t2).deleted_at)

    def test_same_topic_name_in_another_subject_is_not_a_clash(self):
        svc.delete(self.profile, self.user, "topic", self.t2.pk)
        other = self.make("subject", name="Torts")
        self.make("topic", ("subject", other.pk), name="Breach")
        svc.restore(self.profile, self.user, "topic", self.t2.pk)
        self.assertEqual(self.get(self.t2).name, "Breach")

    def test_restore_failing_half_way_changes_nothing(self):
        svc.delete(self.profile, self.user, "topic", self.t1.pk)
        with self.failing_history(after=2):
            with self.assertRaises(RuntimeError):
                svc.restore(self.profile, self.user, "topic", self.t1.pk)
        self.assertTrue(all(self.deleted(self.t1_tree)))

    def test_stale_restore_is_a_conflict(self):
        svc.delete(self.profile, self.user, "item", self.i1.pk)
        with self.assertRaises(svc.Conflict):
            svc.restore(self.profile, self.user, "item", self.i1.pk, expected_version=1)

    def test_a_case_cannot_come_back_under_an_item_that_is_now_a_nested_item(self):
        svc.delete(self.profile, self.user, "case", self.case.pk)
        Item.objects.filter(pk=self.multi.pk).update(kind="nested")
        with self.assertRaises(svc.Refused):
            svc.restore(self.profile, self.user, "case", self.case.pk)


class PermanentDeleteTests(TrashTestCase):
    def test_only_from_trash(self):
        with self.assertRaises(svc.Refused):
            svc.permanent_delete(self.profile, self.user, "topic", self.t1.pk)
        self.assertTrue(Topic.objects.filter(pk=self.t1.pk).exists())

    def test_removes_the_whole_subtree_and_keeps_history(self):
        svc.delete(self.profile, self.user, "topic", self.t1.pk)
        result = svc.permanent_delete(self.profile, self.user, "topic", self.t1.pk)
        self.assertTrue(result.changed)
        self.assertEqual(
            result.info["deleted"],
            {"topic": 1, "subtopic": 1, "item": 4, "section": 1, "case": 1, "note": 1},
        )
        self.assertFalse(Topic.objects.filter(pk=self.t1.pk).exists())
        self.assertFalse(Subtopic.objects.filter(pk=self.st.pk).exists())
        self.assertFalse(Item.objects.filter(pk__in=[self.i1.pk, self.i2.pk, self.i3.pk, self.multi.pk]).exists())
        self.assertFalse(Section.objects.filter(pk=self.sec.pk).exists())
        self.assertFalse(Case.objects.filter(pk=self.case.pk).exists())
        self.assertFalse(Note.objects.filter(pk=self.note.pk).exists())
        self.assertFalse(TrashBatch.objects.exists())
        self.assertTrue(Topic.objects.filter(pk=self.t2.pk).exists())
        self.assertTrue(Subject.objects.filter(pk=self.subject.pk).exists())
        self.assertTrue(VersionHistory.objects.filter(record_type="item", record_id=self.i1.pk).exists())

    def test_ids_are_not_reused(self):
        svc.delete(self.profile, self.user, "topic", self.t2.pk)
        svc.permanent_delete(self.profile, self.user, "topic", self.t2.pk)
        fresh = self.make("topic", ("subject", self.subject.pk), name="New")
        self.assertGreater(fresh.pk, self.t2.pk)

    def test_refused_while_other_notes_link_to_it(self):
        other_note = self.make("note", ("topic", self.t2.pk), text="points")
        link = svc.add_link(self.profile, self.user, other_note.pk, ("item", self.i1.pk)).record
        svc.delete(self.profile, self.user, "topic", self.t1.pk)
        with self.assertRaises(svc.PermanentDeleteRefused) as caught:
            svc.permanent_delete(self.profile, self.user, "topic", self.t1.pk)
        self.assertEqual(len(caught.exception.links), 1)
        shown = caught.exception.links[0]
        self.assertEqual(
            (shown["link_id"], shown["note_id"], shown["target_type"], shown["target_id"], shown["live"]),
            (link.pk, other_note.pk, "item", self.i1.pk, True),
        )
        self.assertEqual((shown["target_label"], shown["note_label"]), ("i1", "points"))
        # Nothing was removed, and the link is exactly as it was.
        self.assertTrue(Topic.objects.filter(pk=self.t1.pk).exists())
        self.assertTrue(Item.objects.filter(pk=self.i1.pk).exists())
        kept = NoteLink.objects.get(pk=link.pk)
        self.assertEqual((kept.item_id, kept.deleted_at, kept.version), (self.i1.pk, None, 1))

    def test_a_link_in_trash_still_blocks_and_can_be_removed_on_its_own(self):
        other_note = self.make("note", ("topic", self.t2.pk), text="points")
        link = svc.add_link(self.profile, self.user, other_note.pk, ("item", self.i1.pk)).record
        svc.delete(self.profile, self.user, "topic", self.t1.pk)
        svc.delete(self.profile, self.user, "notelink", link.pk)
        with self.assertRaises(svc.PermanentDeleteRefused) as caught:
            svc.permanent_delete(self.profile, self.user, "topic", self.t1.pk)
        self.assertFalse(caught.exception.links[0]["live"])
        svc.permanent_delete(self.profile, self.user, "notelink", link.pk)
        self.assertFalse(NoteLink.objects.filter(pk=link.pk).exists())
        svc.permanent_delete(self.profile, self.user, "topic", self.t1.pk)
        self.assertFalse(Topic.objects.filter(pk=self.t1.pk).exists())

    def test_links_inside_the_deleted_subtree_do_not_block(self):
        link = svc.add_link(self.profile, self.user, self.note.pk, ("subtopic", self.st.pk)).record
        svc.delete(self.profile, self.user, "topic", self.t1.pk)
        svc.permanent_delete(self.profile, self.user, "topic", self.t1.pk)
        self.assertFalse(NoteLink.objects.filter(pk=link.pk).exists())

    def test_failing_permanent_delete_removes_nothing(self):
        link = svc.add_link(self.profile, self.user, self.note.pk, ("subtopic", self.st.pk)).record
        svc.delete(self.profile, self.user, "topic", self.t1.pk)
        with mock.patch.object(Topic, "delete", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                svc.permanent_delete(self.profile, self.user, "topic", self.t1.pk)
        self.assertTrue(NoteLink.objects.filter(pk=link.pk).exists())
        self.assertTrue(Topic.objects.filter(pk=self.t1.pk).exists())
        self.assertTrue(TrashBatch.objects.exists())

    def test_a_record_with_a_live_descendant_is_refused(self):
        svc.delete(self.profile, self.user, "topic", self.t1.pk)
        Item.objects.filter(pk=self.i1.pk).update(deleted_at=None)
        with self.assertRaises(svc.Refused):
            svc.permanent_delete(self.profile, self.user, "topic", self.t1.pk)


class NoteLinkPreservationTests(TrashTestCase):
    def setUp(self):
        super().setUp()
        self.other_note = self.make("note", ("topic", self.t2.pk), text="points")
        self.link = svc.add_link(self.profile, self.user, self.other_note.pk, ("item", self.i1.pk)).record

    def link_state(self):
        link = NoteLink.objects.get(pk=self.link.pk)
        return (link.item_id, link.note_id, link.deleted_at, link.version)

    def test_target_in_trash_keeps_the_link_and_restoring_makes_it_work_again(self):
        svc.delete(self.profile, self.user, "item", self.i1.pk)
        self.assertEqual(self.link_state(), (self.i1.pk, self.other_note.pk, None, 1))
        svc.restore(self.profile, self.user, "item", self.i1.pk)
        self.assertEqual(self.link_state(), (self.i1.pk, self.other_note.pk, None, 1))

    def test_deleting_the_whole_topic_of_the_target_keeps_the_link(self):
        svc.delete(self.profile, self.user, "topic", self.t1.pk)
        self.assertEqual(self.link_state(), (self.i1.pk, self.other_note.pk, None, 1))
        svc.restore(self.profile, self.user, "topic", self.t1.pk)
        self.assertEqual(self.link_state(), (self.i1.pk, self.other_note.pk, None, 1))

    def test_deleting_the_note_trashes_its_links_and_restoring_brings_them_back(self):
        svc.delete(self.profile, self.user, "note", self.other_note.pk)
        self.assertIsNotNone(NoteLink.objects.get(pk=self.link.pk).deleted_at)
        svc.restore(self.profile, self.user, "note", self.other_note.pk)
        self.assertEqual(self.link_state()[:3], (self.i1.pk, self.other_note.pk, None))

    def test_the_same_link_is_not_added_twice(self):
        again = svc.add_link(self.profile, self.user, self.other_note.pk, ("item", self.i1.pk))
        self.assertFalse(again.changed)
        self.assertEqual(again.record.pk, self.link.pk)
        self.assertEqual(NoteLink.objects.filter(note=self.other_note).count(), 1)

    def test_links_survive_moves_and_conversions(self):
        svc.move(self.profile, self.user, "item", self.i1.pk, ("topic", self.t2.pk))
        svc.convert_item(self.profile, self.user, self.i1.pk, "nested")
        self.assertEqual(self.link_state(), (self.i1.pk, self.other_note.pk, None, 1))

    def test_link_targets_in_another_profile_are_refused(self):
        foreign = self.make("subject", profile=self.other_profile, name="Foreign")
        with self.assertRaises(svc.NotFound):
            svc.add_link(self.profile, self.user, self.other_note.pk, ("subject", foreign.pk))
        self.assertEqual(NoteLink.objects.filter(subject=foreign).count(), 0)


class BatchCleanupAndRenameTests(TrashTestCase):
    def test_restore_removes_the_batch_row_when_nothing_carries_it(self):
        svc.delete(self.profile, self.user, "topic", self.t2.pk)
        self.assertEqual(TrashBatch.objects.count(), 1)
        svc.restore(self.profile, self.user, "topic", self.t2.pk)
        self.assertEqual(TrashBatch.objects.count(), 0)

    def test_partial_restore_keeps_the_batch_row(self):
        svc.delete(self.profile, self.user, "topic", self.t1.pk)
        svc.restore(self.profile, self.user, "item", self.i1.pk, restore_parents=True)
        self.assertEqual(TrashBatch.objects.count(), 1)

    def test_permanent_delete_prunes_batches_of_earlier_deletes(self):
        svc.delete(self.profile, self.user, "item", self.i2.pk)
        svc.delete(self.profile, self.user, "topic", self.t1.pk)
        self.assertEqual(TrashBatch.objects.count(), 2)
        svc.permanent_delete(self.profile, self.user, "topic", self.t1.pk)
        self.assertEqual(TrashBatch.objects.count(), 0)

    def test_long_rename_is_refused(self):
        svc.delete(self.profile, self.user, "topic", self.t2.pk)
        with self.assertRaises(svc.ValidationFailed):
            svc.restore(self.profile, self.user, "topic", self.t2.pk, new_name="x" * 301)
        self.assertIsNotNone(self.get(self.t2).deleted_at)

    def test_rename_of_a_record_type_that_cannot_be_renamed_is_refused(self):
        svc.delete(self.profile, self.user, "topic", self.t1.pk)
        with self.assertRaises(svc.ValidationFailed):
            svc.restore(
                self.profile, self.user, "topic", self.t1.pk, new_names={("item", self.i1.pk): "renamed"}
            )
        self.assertEqual(self.get(self.i1).text, "i1")
        self.assertIsNotNone(self.get(self.t1).deleted_at)
