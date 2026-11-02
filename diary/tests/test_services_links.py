"""Notes with several links (Milestone 5, service layer): order, same-profile rule, Trash, restore, Undo, History."""
from diary import services as svc
from diary.models import Note, NoteLink
from diary.services.links import link_target
from diary.tests.service_helpers import ServiceTestCase


class LinkTestCase(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.build_topic()
        self.section = self.sec if hasattr(self, "sec") else self.make("section", ("topic", self.topic.pk), name="S2")
        self.note = self.make("note", ("topic", self.topic.pk), text="<p>see</p>")

    def link(self, kind, obj, note=None):
        return svc.add_link(self.profile, self.user, (note or self.note).pk, (kind, obj.pk)).record

    def live_targets(self, note=None):
        rows = NoteLink.objects.filter(note=note or self.note, deleted_at__isnull=True).order_by("position", "pk")
        return [link_target(row) for row in rows]


class CreateTests(LinkTestCase):
    def test_a_note_can_have_several_links_of_every_kind_in_order(self):
        nested = self.make("item", ("topic", self.topic.pk), kind="nested", text="group")
        child = self.make("item", ("item", nested.pk), text="child")
        sub = self.make("subtopic", ("topic", self.topic.pk), name="Offer")
        wanted = [("subject", self.subject), ("topic", self.topic), ("subtopic", sub), ("section", self.section),
                  ("item", self.one), ("item", nested), ("item", child)]
        for kind, obj in wanted:
            self.link(kind, obj)
        self.assertEqual(self.live_targets(), [(kind, obj.pk) for kind, obj in wanted])
        positions = list(NoteLink.objects.filter(note=self.note).order_by("pk").values_list("position", flat=True))
        self.assertEqual(positions, [1, 2, 3, 4, 5, 6, 7])

    def test_adding_the_same_link_twice_does_nothing(self):
        first = self.link("item", self.one)
        again = svc.add_link(self.profile, self.user, self.note.pk, ("item", self.one.pk))
        self.assertFalse(again.changed)
        self.assertEqual(again.record.pk, first.pk)
        self.assertEqual(NoteLink.objects.filter(note=self.note).count(), 1)

    def test_a_note_cannot_link_to_a_note_or_a_case(self):
        other = self.make("note", ("topic", self.topic.pk), text="o")
        with self.assertRaises(svc.Refused):
            svc.add_link(self.profile, self.user, self.note.pk, ("note", other.pk))
        with self.assertRaises(svc.Refused):
            svc.add_link(self.profile, self.user, self.note.pk, ("case", 1))

    def test_a_link_to_another_profile_is_refused_and_nothing_is_written(self):
        foreign_subject = self.make("subject", profile=self.other_profile, name="Foreign")
        foreign_topic = self.make("topic", ("subject", foreign_subject.pk), profile=self.other_profile, name="T")
        foreign_item = self.make("item", ("topic", foreign_topic.pk), profile=self.other_profile, text="x")
        for kind, obj in (("subject", foreign_subject), ("topic", foreign_topic), ("item", foreign_item)):
            with self.assertRaises(svc.NotFound):
                svc.add_link(self.profile, self.user, self.note.pk, (kind, obj.pk))
        self.assertFalse(NoteLink.objects.exists())

    def test_a_note_of_another_profile_cannot_be_linked_from(self):
        foreign_subject = self.make("subject", profile=self.other_profile, name="Foreign")
        foreign_note = self.make("note", ("subject", foreign_subject.pk), profile=self.other_profile, text="n")
        with self.assertRaises(svc.NotFound):
            svc.add_link(self.profile, self.user, foreign_note.pk, ("item", self.one.pk))

    def test_a_target_in_trash_is_refused(self):
        svc.delete(self.profile, self.user, "item", self.one.pk)
        with self.assertRaises(svc.Refused):
            svc.add_link(self.profile, self.user, self.note.pk, ("item", self.one.pk))


class OrderTests(LinkTestCase):
    def test_notes_come_after_items_and_sections_of_their_parent_and_reorder_among_themselves(self):
        second = self.make("note", ("topic", self.topic.pk), text="second")
        third = self.make("note", ("topic", self.topic.pk), text="third")
        self.assertEqual([self.get(n).position for n in (self.note, second, third)], [1, 2, 3])
        svc.shift(self.profile, self.user, "note", third.pk, -2)
        self.assertEqual([self.get(n).position for n in (third, self.note, second)], [1, 2, 3])
        # Items and Sections keep their own sequence: a Note never changes a number.
        self.assertEqual([text for _, text in self.numbered(self.topic)], ["one", "two", "S", "three", "four"])

    def test_notes_of_one_parent_do_not_share_a_sequence_with_another_parent(self):
        on_item = self.make("note", ("item", self.one.pk), text="on item")
        self.assertEqual(self.get(on_item).position, 1)
        self.assertEqual(self.get(self.note).position, 1)

    def test_a_note_can_be_moved_to_any_kind_of_parent(self):
        sub = self.make("subtopic", ("topic", self.topic.pk), name="Offer")
        for kind, obj in (("item", self.one), ("section", self.sec), ("subtopic", sub), ("subject", self.subject)):
            svc.move(self.profile, self.user, "note", self.note.pk, (kind, obj.pk))
            self.assertEqual(getattr(self.get(self.note), f"{kind}_id"), obj.pk)

    def test_links_reorder_up_and_down_and_clamp_at_the_ends(self):
        a, b, c = (self.link("item", o) for o in (self.one, self.two, self.three))
        svc.shift_link(self.profile, self.user, c.pk, -2)
        self.assertEqual(self.live_targets(), [("item", self.three.pk), ("item", self.one.pk), ("item", self.two.pk)])
        svc.shift_link(self.profile, self.user, c.pk, -1)  # already first: nothing changes
        self.assertEqual(self.live_targets()[0], ("item", self.three.pk))
        svc.shift_link(self.profile, self.user, a.pk, 5)
        self.assertEqual(self.live_targets()[-1], ("item", self.one.pk))
        self.assertEqual(sorted(self.get(x).position for x in (a, b, c)), [1, 2, 3])


class RetargetTests(LinkTestCase):
    def test_retarget_keeps_the_place_and_writes_history(self):
        a = self.link("item", self.one)
        self.link("item", self.two)
        result = svc.retarget_link(self.profile, self.user, a.pk, ("section", self.section.pk))
        self.assertTrue(result.changed)
        self.assertEqual(self.live_targets(), [("section", self.section.pk), ("item", self.two.pk)])
        self.assertEqual(self.history_kinds(a), ["create", "edit"])
        again = svc.retarget_link(self.profile, self.user, a.pk, ("section", self.section.pk))
        self.assertFalse(again.changed)

    def test_retarget_into_another_profile_is_refused(self):
        foreign = self.make("subject", profile=self.other_profile, name="Foreign")
        a = self.link("item", self.one)
        with self.assertRaises(svc.NotFound):
            svc.retarget_link(self.profile, self.user, a.pk, ("subject", foreign.pk))
        self.assertEqual(link_target(self.get(a)), ("item", self.one.pk))


class TrashTests(LinkTestCase):
    def test_a_trashed_target_keeps_its_link_and_restoring_it_revives_the_link(self):
        a = self.link("item", self.one)
        svc.delete(self.profile, self.user, "item", self.one.pk)
        kept = self.get(a)
        self.assertIsNone(kept.deleted_at)
        self.assertEqual(link_target(kept), ("item", self.one.pk))
        self.assertEqual(kept.version, 1)  # untouched
        svc.restore(self.profile, self.user, "item", self.one.pk)
        self.assertIsNone(self.get(self.one).deleted_at)
        self.assertEqual(self.live_targets(), [("item", self.one.pk)])

    def test_deleting_a_note_trashes_its_links_and_restoring_brings_them_back_in_order(self):
        links = [self.link("item", o) for o in (self.one, self.two, self.three)]
        svc.delete(self.profile, self.user, "note", self.note.pk)
        self.assertTrue(all(self.get(x).deleted_at is not None for x in links))
        self.assertEqual(NoteLink.objects.filter(note=self.note, deleted_at__isnull=True).count(), 0)
        svc.restore(self.profile, self.user, "note", self.note.pk)
        self.assertEqual(self.live_targets(), [("item", self.one.pk), ("item", self.two.pk), ("item", self.three.pk)])
        self.assertTrue(all(self.get(x).deleted_at is None for x in links))

    def test_a_removed_link_goes_to_trash_and_restores_to_its_place(self):
        a, b, c = (self.link("item", o) for o in (self.one, self.two, self.three))
        svc.delete(self.profile, self.user, "notelink", b.pk)
        self.assertEqual(self.live_targets(), [("item", self.one.pk), ("item", self.three.pk)])
        svc.restore(self.profile, self.user, "notelink", b.pk)
        self.assertEqual(self.live_targets(), [("item", self.one.pk), ("item", self.two.pk), ("item", self.three.pk)])

    def test_a_link_cannot_be_restored_while_its_note_is_in_trash(self):
        a = self.link("item", self.one)
        svc.delete(self.profile, self.user, "note", self.note.pk)
        with self.assertRaises(svc.ParentInTrash):
            svc.restore(self.profile, self.user, "notelink", a.pk)

    def test_trashing_a_note_never_trashes_what_it_links_to(self):
        self.link("item", self.one)
        svc.delete(self.profile, self.user, "note", self.note.pk)
        self.assertIsNone(self.get(self.one).deleted_at)


class PermanentDeleteTests(LinkTestCase):
    def setUp(self):
        super().setUp()
        self.link_to_one = self.link("item", self.one)
        svc.delete(self.profile, self.user, "item", self.one.pk)

    def test_refused_while_a_link_points_at_it_and_lists_the_link(self):
        with self.assertRaises(svc.PermanentDeleteRefused) as caught:
            svc.permanent_delete(self.profile, self.user, "item", self.one.pk)
        shown = caught.exception.links
        self.assertEqual([(x["link_id"], x["note_id"], x["target_type"]) for x in shown],
                         [(self.link_to_one.pk, self.note.pk, "item")])
        self.assertTrue(type(self.one).objects.filter(pk=self.one.pk).exists())

    def test_retargeting_the_link_lets_the_delete_go_ahead(self):
        svc.retarget_link(self.profile, self.user, self.link_to_one.pk, ("item", self.two.pk))
        svc.permanent_delete(self.profile, self.user, "item", self.one.pk)
        self.assertFalse(type(self.one).objects.filter(pk=self.one.pk).exists())
        self.assertEqual(self.live_targets(), [("item", self.two.pk)])

    def test_purging_the_link_lets_the_delete_go_ahead_and_keeps_its_history(self):
        svc.purge_link(self.profile, self.user, self.link_to_one.pk)
        self.assertFalse(NoteLink.objects.filter(pk=self.link_to_one.pk).exists())
        self.assertGreaterEqual(len(self.history(self.link_to_one)), 2)  # created, then deleted
        svc.permanent_delete(self.profile, self.user, "item", self.one.pk)
        self.assertTrue(Note.objects.filter(pk=self.note.pk).exists())

    def test_deleting_a_note_for_good_takes_its_links_with_it(self):
        svc.delete(self.profile, self.user, "note", self.note.pk)
        svc.permanent_delete(self.profile, self.user, "note", self.note.pk)
        self.assertFalse(NoteLink.objects.filter(pk=self.link_to_one.pk).exists())
        svc.permanent_delete(self.profile, self.user, "item", self.one.pk)


class UndoAndHistoryTests(LinkTestCase):
    def test_undo_adding_a_link_takes_it_out_of_view(self):
        added = svc.add_link(self.profile, self.user, self.note.pk, ("item", self.one.pk))
        svc.undo_group(self.profile, self.user, added.group)
        self.assertEqual(self.live_targets(), [])

    def test_undo_removing_a_link_brings_it_back(self):
        a = self.link("item", self.one)
        removed = svc.delete(self.profile, self.user, "notelink", a.pk)
        svc.undo_group(self.profile, self.user, removed.group)
        self.assertEqual(self.live_targets(), [("item", self.one.pk)])

    def test_undo_a_retarget(self):
        a = self.link("item", self.one)
        moved = svc.retarget_link(self.profile, self.user, a.pk, ("item", self.two.pk))
        svc.undo_group(self.profile, self.user, moved.group)
        self.assertEqual(link_target(self.get(a)), ("item", self.one.pk))

    def test_undo_reordering_links(self):
        self.link("item", self.one)
        b = self.link("item", self.two)
        shifted = svc.shift_link(self.profile, self.user, b.pk, -1)
        self.assertEqual(self.live_targets()[0], ("item", self.two.pk))
        svc.undo_group(self.profile, self.user, shifted.group)
        self.assertEqual(self.live_targets()[0], ("item", self.one.pk))

    def test_undo_deleting_a_note_restores_it_and_its_links(self):
        self.link("item", self.one)
        self.link("item", self.two)
        deleted = svc.delete(self.profile, self.user, "note", self.note.pk)
        svc.undo_group(self.profile, self.user, deleted.group)
        self.assertIsNone(self.get(self.note).deleted_at)
        self.assertEqual(self.live_targets(), [("item", self.one.pk), ("item", self.two.pk)])

    def test_a_note_edit_has_history_and_an_old_version_can_be_restored(self):
        svc.edit(self.profile, self.user, "note", self.note.pk, {"text": "<p>changed</p>"}, 1)
        self.assertEqual(self.history_kinds(self.note), ["create", "edit"])
        svc.restore_version(self.profile, self.user, "note", self.note.pk, 1)
        self.assertEqual(self.get(self.note).text, "<p>see</p>")
        self.assertEqual(self.history_kinds(self.note), ["create", "edit", "restore"])

    def test_every_link_change_writes_a_history_row(self):
        a = self.link("item", self.one)
        svc.retarget_link(self.profile, self.user, a.pk, ("item", self.two.pk))
        svc.delete(self.profile, self.user, "notelink", a.pk)
        svc.restore(self.profile, self.user, "notelink", a.pk)
        self.assertEqual(self.history_kinds(a), ["create", "edit", "delete", "restore"])
