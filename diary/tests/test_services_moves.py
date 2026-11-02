"""Move, reorder, positions and generated numbers after moves and deletes (service layer)."""
from diary import services as svc
from diary.models import Case, NoteLink, VersionHistory
from diary.services.sequences import members
from diary.tests.service_helpers import ServiceTestCase

BASE = [("(1)", "one"), ("(2)", "two"), ("(a)", "S"), ("(1)", "three"), ("(2)", "four")]


class ReorderTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.build_topic()

    def test_fixture_numbering(self):
        self.assertEqual(self.numbered(self.topic), BASE)
        self.assertEqual(self.positions([self.one, self.two, self.sec, self.three, self.four]), [1, 2, 3, 4, 5])

    def test_move_section_up_renumbers_the_items_that_follow(self):
        result = svc.shift(self.profile, self.user, "section", self.sec.pk, -1)
        self.assertTrue(result.changed)
        self.assertEqual(
            self.numbered(self.topic),
            [("(1)", "one"), ("(a)", "S"), ("(1)", "two"), ("(2)", "three"), ("(3)", "four")],
        )
        self.assertEqual(self.positions([self.one, self.sec, self.two, self.three, self.four]), [1, 2, 3, 4, 5])
        self.assertEqual(self.history_kinds(self.sec), ["create", "reorder"])

    def test_items_before_the_first_section_number_as_usual(self):
        svc.move(self.profile, self.user, "section", self.sec.pk, index=0)
        self.assertEqual(
            self.numbered(self.topic),
            [("(a)", "S"), ("(1)", "one"), ("(2)", "two"), ("(3)", "three"), ("(4)", "four")],
        )

    def test_preview_lists_exactly_the_items_whose_numbers_change(self):
        before_versions = [self.get(o).version for o in (self.one, self.two, self.sec, self.three, self.four)]
        preview = svc.preview_move(self.profile, self.user, "section", self.sec.pk, index=1)
        changes = {(c["type"], c["id"]): (c["before"], c["after"]) for c in preview["changes"]}
        self.assertEqual(
            changes,
            {
                ("item", self.two.pk): ("(2)", "(1)"),
                ("item", self.three.pk): ("(1)", "(2)"),
                ("item", self.four.pk): ("(2)", "(3)"),
            },
        )
        # A preview writes nothing.
        after_versions = [self.get(o).version for o in (self.one, self.two, self.sec, self.three, self.four)]
        self.assertEqual(before_versions, after_versions)
        self.assertEqual(self.numbered(self.topic), BASE)

    def test_preview_of_moving_to_another_parent(self):
        other = self.make("topic", ("subject", self.subject.pk), name="Other")
        preview = svc.preview_move(self.profile, self.user, "section", self.sec.pk, ("topic", other.pk))
        changes = {c["id"]: (c["before"], c["after"]) for c in preview["changes"]}
        self.assertEqual(changes, {self.three.pk: ("(1)", "(3)"), self.four.pk: ("(2)", "(4)")})

    def test_preview_of_delete_counts_and_lists_renumbered_items(self):
        preview = svc.preview_delete(self.profile, self.user, "section", self.sec.pk)
        changes = {c["id"]: (c["before"], c["after"]) for c in preview["changes"]}
        self.assertEqual(changes, {self.three.pk: ("(1)", "(3)"), self.four.pk: ("(2)", "(4)")})
        self.assertEqual(preview["count"], 1)
        self.assertIsNone(self.get(self.sec).deleted_at)

    def test_a_repeated_move_changes_nothing(self):
        svc.move(self.profile, self.user, "item", self.four.pk, index=0)
        count = VersionHistory.objects.count()
        again = svc.move(self.profile, self.user, "item", self.four.pk, index=0)
        self.assertFalse(again.changed)
        self.assertEqual(VersionHistory.objects.count(), count)
        self.assertEqual(self.get(self.four).position, 1)

    def test_shift_at_the_ends_does_nothing(self):
        self.assertFalse(svc.shift(self.profile, self.user, "item", self.one.pk, -1).changed)
        self.assertFalse(svc.shift(self.profile, self.user, "item", self.four.pk, 1).changed)
        self.assertEqual(self.numbered(self.topic), BASE)

    def test_positions_stay_contiguous_after_many_moves(self):
        svc.move(self.profile, self.user, "item", self.one.pk, index=4)
        svc.move(self.profile, self.user, "item", self.four.pk, index=0)
        svc.shift(self.profile, self.user, "section", self.sec.pk, 1)
        order = [self.two, self.three, self.sec, self.one]
        order = [self.four] + order
        self.assertEqual(self.positions(order), [1, 2, 3, 4, 5])

    def test_reorder_with_a_stale_version_is_a_conflict(self):
        svc.edit(self.profile, self.user, "item", self.one.pk, {"text": "uno"})
        with self.assertRaises(svc.Conflict):
            svc.shift(self.profile, self.user, "item", self.one.pk, 1, expected_version=1)

    def test_subjects_cannot_be_reordered_by_hand(self):
        a = self.make("subject", name="A")
        b = self.make("subject", name="B")
        c = self.make("subject", name="C")
        other_group = self.make("subject", name="Other act", show_on_landing=False)
        before = [self.get(x).landing_position for x in (a, b, c)]
        with self.assertRaises(svc.Refused):
            svc.shift(self.profile, self.user, "subject", c.pk, -2)
        with self.assertRaises(svc.Refused):
            svc.move(self.profile, self.user, "subject", c.pk, index=0)
        self.assertEqual([self.get(x).landing_position for x in (a, b, c)], before)
        self.assertEqual(self.get(other_group).other_acts_position, 1)
        self.assertEqual(self.get(c).version, 1)

    def test_topics_and_subtopics_cannot_be_reordered_by_hand(self):
        self.topic2 = self.make("topic", ("subject", self.subject.pk), name="Other")
        sub1 = self.make("subtopic", ("topic", self.topic.pk), name="Alpha")
        sub2 = self.make("subtopic", ("topic", self.topic.pk), name="Beta")
        for kind, rec in (("topic", self.topic2), ("subtopic", sub2)):
            with self.assertRaises(svc.Refused):
                svc.shift(self.profile, self.user, kind, rec.pk, -1)
            with self.assertRaises(svc.Refused):
                svc.move(self.profile, self.user, kind, rec.pk, index=0)
            with self.assertRaises(svc.Refused):
                svc.preview_move(self.profile, self.user, kind, rec.pk, index=0)
        self.assertEqual(self.positions([self.topic, self.topic2]), [1, 2])
        self.assertEqual(self.positions([sub1, sub2]), [1, 2])

    def test_cases_reorder(self):
        multi = self.make("item", ("topic", self.topic.pk), text="m")
        c1, c2, c3 = (self.make("case", ("item", multi.pk), citation=f"C{n}") for n in (1, 2, 3))
        svc.shift(self.profile, self.user, "case", c3.pk, -1)
        self.assertEqual(self.positions([c1, c2, c3]), [1, 3, 2])

    def test_notes_reorder(self):
        n1 = self.make("note", ("topic", self.topic.pk), text="n1")
        n2 = self.make("note", ("topic", self.topic.pk), text="n2")
        svc.shift(self.profile, self.user, "note", n2.pk, -1)
        self.assertEqual(self.positions([n1, n2]), [2, 1])


class MoveBetweenParentsTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.build_topic()
        self.topic2 = self.make("topic", ("subject", self.subject.pk), name="Other")

    def test_move_section_to_another_topic_renumbers_both_sides(self):
        result = svc.move(self.profile, self.user, "section", self.sec.pk, ("topic", self.topic2.pk))
        self.assertTrue(result.changed)
        self.assertEqual(
            self.numbered(self.topic), [("(1)", "one"), ("(2)", "two"), ("(3)", "three"), ("(4)", "four")]
        )
        self.assertEqual(self.numbered(self.topic2), [("(a)", "S")])
        self.assertEqual(self.positions([self.one, self.two, self.three, self.four]), [1, 2, 3, 4])
        self.assertEqual(self.get(self.sec).position, 1)
        self.assertEqual(self.history_kinds(self.sec), ["create", "move"])
        self.assertEqual(self.history_kinds(self.three), ["create", "reorder"])
        self.assertIsNone(self.get(self.sec).subtopic_id)

    def test_move_at_an_index_in_the_new_parent(self):
        extra = self.make("item", ("topic", self.topic2.pk), text="x")
        svc.move(self.profile, self.user, "item", self.one.pk, ("topic", self.topic2.pk), index=0)
        self.assertEqual(self.numbered(self.topic2), [("(1)", "one"), ("(2)", "x")])
        self.assertEqual(self.get(extra).position, 2)
        self.assertEqual(self.get(self.one).topic_id, self.topic2.pk)

    def test_moving_to_the_same_parent_is_a_reorder(self):
        svc.move(self.profile, self.user, "item", self.one.pk, ("topic", self.topic.pk), index=4)
        self.assertEqual(self.history_kinds(self.one), ["create", "reorder"])
        self.assertEqual(self.get(self.one).position, 5)

    def test_an_item_cannot_be_moved_beneath_an_item(self):
        for moved, parent in ((self.four, self.two), (self.one, self.two)):
            with self.assertRaises(svc.Refused):
                svc.move(self.profile, self.user, "item", moved.pk, ("item", parent.pk))
        self.assertEqual(self.get(self.one).version, 1)
        self.assertEqual(self.get(self.four).topic_id, self.topic.pk)

    def test_a_case_moves_to_another_item(self):
        first = self.make("item", ("topic", self.topic.pk), text="a", citation="A v B")
        second = self.make("item", ("topic", self.topic.pk), text="b")
        case = Case.objects.get(item=first)
        svc.move(self.profile, self.user, "case", case.pk, ("item", second.pk))
        self.assertEqual(self.get(case).item_id, second.pk)

    def test_impossible_moves_are_refused_with_a_reason(self):
        with self.assertRaises(svc.Refused):
            svc.move(self.profile, self.user, "topic", self.topic.pk, ("item", self.one.pk))
        with self.assertRaises(svc.Refused):
            svc.move(self.profile, self.user, "section", self.sec.pk, ("item", self.one.pk))
        with self.assertRaises(svc.Refused):
            svc.move(self.profile, self.user, "subject", self.subject.pk, ("topic", self.topic.pk))
        self.assertEqual(self.get(self.sec).subtopic_id, None)
        self.assertEqual(self.get(self.sec).topic_id, self.topic.pk)

    def test_a_note_link_cannot_be_moved(self):
        note = self.make("note", ("topic", self.topic.pk), text="n")
        link = svc.add_link(self.profile, self.user, note.pk, ("item", self.one.pk)).record
        with self.assertRaises(svc.Refused):
            svc.move(self.profile, self.user, "notelink", link.pk, ("note", note.pk))

    def test_move_into_the_trash_refused(self):
        svc.delete(self.profile, self.user, "topic", self.topic2.pk)
        with self.assertRaises(svc.Refused):
            svc.move(self.profile, self.user, "item", self.one.pk, ("topic", self.topic2.pk))

    def test_topic_moves_between_subjects_and_positions_close_up(self):
        s2 = self.make("subject", name="Torts")
        x = self.make("topic", ("subject", s2.pk), name="X")
        sub = self.make("subtopic", ("topic", self.topic.pk), name="Child")
        svc.move(self.profile, self.user, "topic", self.topic.pk, ("subject", s2.pk), index=0)
        # alphabetical: "Formation" then "X"; the moved Topic takes the next free stored position
        self.assertEqual([t.name for t in members(self.profile.pk, ("topic", "subject", s2.pk))], ["Formation", "X"])
        self.assertEqual(self.positions([x, self.topic]), [1, 2])
        self.assertEqual(self.get(self.topic2).position, 2)  # the list it left is not renumbered
        self.assertEqual(self.get(sub).topic_id, self.topic.pk)
        self.assertEqual(self.get(self.topic).subject_id, s2.pk)

    def test_topic_cannot_move_into_a_subject_with_direct_subtopics(self):
        s2 = self.make("subject", name="Acts")
        self.make("subtopic", ("subject", s2.pk), name="Direct")
        with self.assertRaises(svc.Refused):
            svc.move(self.profile, self.user, "topic", self.topic.pk, ("subject", s2.pk))
        self.assertEqual(self.get(self.topic).subject_id, self.subject.pk)

    def test_subtopic_moves_between_topic_and_subject(self):
        s2 = self.make("subject", name="Acts")
        sub = self.make("subtopic", ("topic", self.topic.pk), name="Offer")
        svc.move(self.profile, self.user, "subtopic", sub.pk, ("subject", s2.pk))
        moved = self.get(sub)
        self.assertEqual((moved.topic_id, moved.subject_id), (None, s2.pk))
        with self.assertRaises(svc.Refused):
            svc.move(self.profile, self.user, "subtopic", sub.pk, ("subject", self.subject.pk))

    def test_links_are_untouched_by_moves(self):
        note = self.make("note", ("topic", self.topic2.pk), text="see")
        link = svc.add_link(self.profile, self.user, note.pk, ("item", self.one.pk)).record
        svc.move(self.profile, self.user, "item", self.one.pk, ("topic", self.topic2.pk))
        svc.move(self.profile, self.user, "section", self.sec.pk, ("topic", self.topic2.pk))
        kept = NoteLink.objects.get(pk=link.pk)
        self.assertEqual((kept.item_id, kept.deleted_at, kept.version), (self.one.pk, None, 1))


class DeleteNumberingTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.build_topic()

    def test_deleting_a_section_merges_the_item_runs(self):
        svc.delete(self.profile, self.user, "section", self.sec.pk)
        self.assertEqual(
            self.numbered(self.topic), [("(1)", "one"), ("(2)", "two"), ("(3)", "three"), ("(4)", "four")]
        )
        positions = self.positions([self.one, self.two, self.three, self.four])
        self.assertEqual(positions, sorted(positions))

    def test_restoring_the_section_brings_the_old_numbers_back(self):
        svc.delete(self.profile, self.user, "section", self.sec.pk)
        svc.restore(self.profile, self.user, "section", self.sec.pk)
        self.assertEqual(self.numbered(self.topic), BASE)
        self.assertEqual(self.positions([self.one, self.two, self.sec, self.three, self.four]), [1, 2, 3, 4, 5])
        self.assertIsNone(self.get(self.sec).delete_batch)

    def test_delete_and_restore_in_any_order_keeps_everything_in_place(self):
        svc.delete(self.profile, self.user, "item", self.two.pk)
        svc.delete(self.profile, self.user, "item", self.three.pk)
        self.assertEqual(self.numbered(self.topic), [("(1)", "one"), ("(a)", "S"), ("(1)", "four")])
        svc.restore(self.profile, self.user, "item", self.three.pk)
        svc.restore(self.profile, self.user, "item", self.two.pk)
        self.assertEqual(self.numbered(self.topic), BASE)
        self.assertEqual(self.positions([self.one, self.two, self.sec, self.three, self.four]), [1, 2, 3, 4, 5])

    def test_deleted_items_do_not_count_in_the_numbers(self):
        svc.delete(self.profile, self.user, "item", self.one.pk)
        self.assertEqual(self.numbered(self.topic)[0], ("(1)", "two"))
