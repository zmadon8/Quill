"""Create, edit, validation, conflicts, history restore, profile isolation and atomicity (service layer)."""
from diary import services as svc
from diary.models import Case, Item, Subject, Topic, VersionHistory
from diary.reading import formats_for
from diary.services.sequences import ident, labels, members
from diary.tests.service_helpers import ServiceTestCase


class CreateTests(ServiceTestCase):
    def test_subjects_are_placed_last_and_history_is_written(self):
        a = self.make("subject", name="Alpha")
        b = self.make("subject", name="Beta")
        self.assertEqual((self.get(a).landing_position, self.get(b).landing_position), (1, 2))
        self.assertEqual(self.get(a).version, 1)
        self.assertEqual(self.history_kinds(a), ["create"])
        self.assertEqual(self.history(a)[0].snapshot["name"], "Alpha")
        self.assertEqual(self.history(a)[0].changed_by, self.user)
        self.assertEqual(self.get(a).created_by, self.user)

    def test_other_subjects_have_their_own_order(self):
        main = self.make("subject", name="Main one")
        other = self.make("subject", name="Other one", show_on_landing=False)
        self.assertEqual(self.get(main).landing_position, 1)
        self.assertEqual(self.get(other).other_acts_position, 1)

    def test_insert_at_index_is_ignored_for_headings_and_shifts_no_sibling(self):
        subject = self.make("subject", name="S")
        t1 = self.make("topic", ("subject", subject.pk), name="T1")
        t2 = self.make("topic", ("subject", subject.pk), name="T2")
        t0 = self.make("topic", ("subject", subject.pk), index=0, name="T0")
        self.assertEqual(self.positions([t1, t2, t0]), [1, 2, 3])  # stored Word order untouched
        self.assertEqual(self.get(t1).version, 1)
        self.assertEqual(self.history_kinds(t1), ["create"])
        self.assertEqual(self.history_kinds(t2), ["create"])
        self.assertEqual([t.name for t in members(self.profile.pk, ("topic", "subject", subject.pk))], ["T0", "T1", "T2"])

    def test_insert_at_index_still_shifts_items(self):
        subject = self.make("subject", name="S")
        i1 = self.make("item", ("subject", subject.pk), text="1")
        i0 = self.make("item", ("subject", subject.pk), index=0, text="0")
        self.assertEqual(self.positions([i0, i1]), [1, 2])
        self.assertEqual(self.history_kinds(i1), ["create", "reorder"])

    def test_headings_are_shown_alphabetically_with_numbers_as_numbers(self):
        for name in ("S. 11", "s. 9", "Zebra", "\u201cApple\u201d", "banana"):
            self.make("subject", name=name)
        names = [s.name for s in members(self.profile.pk, ("subject", "show", True))]
        self.assertEqual(names, ["\u201cApple\u201d", "banana", "s. 9", "S. 11", "Zebra"])
        other = self.make("subject", name="Aardvark", show_on_landing=False)
        self.assertEqual([s.name for s in members(self.profile.pk, ("subject", "show", False))], ["Aardvark"])
        self.assertEqual(self.get(other).other_acts_position, 1)

    def test_names_equal_after_normalising_list_deterministically(self):
        subject = self.make("subject", name="S")
        t = ("subject", subject.pk)
        a = self.make("subtopic", t, name="Commercial contracts")
        b = self.make("subtopic", t, name="Commercial Contracts")
        first = [x.pk for x in members(self.profile.pk, ("subtopic", "subject", subject.pk))]
        second = [x.pk for x in members(self.profile.pk, ("subtopic", "subject", subject.pk))]
        self.assertEqual(first, second)
        self.assertEqual(sorted(first), sorted([a.pk, b.pk]))

    def test_renaming_a_topic_relettered_it_and_undo_restores_name_and_letter(self):
        subject = self.make("subject", name="S")
        t = ("subject", subject.pk)
        apple = self.make("topic", t, name="Apple")
        pear = self.make("topic", t, name="Pear")
        key = ("topic", "subject", subject.pk)

        def lettered():
            objs = members(self.profile.pk, key)
            gen = labels(key, objs, formats_for(None))
            return [(gen[ident(o)], o.name) for o in objs]

        self.assertEqual(lettered(), [("A", "Apple"), ("B", "Pear")])
        svc.edit(self.profile, self.user, "topic", apple.pk, {"name": "Zulu"})
        self.assertEqual(lettered(), [("A", "Pear"), ("B", "Zulu")])
        svc.restore_version(self.profile, self.user, "topic", apple.pk, 1)
        self.assertEqual(lettered(), [("A", "Apple"), ("B", "Pear")])
        self.assertEqual(self.positions([apple, pear]), [1, 2])

    def test_subject_name_unique_ignoring_case(self):
        self.make("subject", name="Contract")
        with self.assertRaises(svc.ValidationFailed):
            self.make("subject", name="contract")
        self.assertEqual(Subject.objects.count(), 1)

    def test_same_subject_name_allowed_in_another_profile(self):
        self.make("subject", name="Contract")
        again = self.make("subject", profile=self.other_profile, name="Contract")
        self.assertEqual(again.profile_id, self.other_profile.pk)

    def test_blank_names_refused(self):
        subject = self.make("subject", name="S")
        for kind, parent in (("subject", None), ("topic", ("subject", subject.pk))):
            with self.assertRaises(svc.ValidationFailed):
                self.make(kind, parent, name="   ")
        self.assertEqual(Topic.objects.count(), 0)

    def test_name_whitespace_is_tidied(self):
        subject = self.make("subject", name="  Law   of  Tort ")
        self.assertEqual(self.get(subject).name, "Law of Tort")

    def test_item_needs_a_place_and_a_valid_one(self):
        subject = self.make("subject", name="S")
        with self.assertRaises(svc.Refused):
            self.make("item", None, text="x")
        with self.assertRaises(svc.Refused):
            self.make("topic", ("topic", self.make("topic", ("subject", subject.pk), name="T").pk), name="X")
        with self.assertRaises(svc.Refused):
            self.make("subject", ("subject", subject.pk), name="Y")

    def test_item_beneath_an_item_refused(self):
        subject = self.make("subject", name="S")
        plain = self.make("item", ("subject", subject.pk), text="p")
        with self.assertRaises(svc.Refused):
            self.make("item", ("item", plain.pk), text="child")

    def test_every_subject_may_hold_topics_and_older_direct_subtopics_together(self):
        # D81: a Subject listed under Other Subjects is treated like any other. The old "Topics or Sub-topics, not both" rule is gone.
        subject = self.make("subject", name="S")
        self.make("topic", ("subject", subject.pk), name="T")
        direct = self.make("subtopic", ("subject", subject.pk), name="Direct")
        self.assertEqual(self.get(direct).subject_id, subject.pk)
        other = self.make("subject", name="O", show_on_landing=False)
        self.make("subtopic", ("subject", other.pk), name="Direct")
        topic = self.make("topic", ("subject", other.pk), name="T")
        self.assertEqual(self.get(topic).subject_id, other.pk)

    def test_cases_under_any_item(self):
        subject = self.make("subject", name="S")
        plain = self.make("item", ("subject", subject.pk), text="p")
        case = self.make("case", ("item", plain.pk), citation="A v B")
        self.assertEqual(self.get(case).position, 1)
        second = self.make("case", ("item", plain.pk), citation="C v D")
        self.assertEqual(self.get(second).position, 2)

    def test_a_new_item_with_a_citation_gets_it_as_case_a(self):
        subject = self.make("subject", name="S")
        item = self.make("item", ("subject", subject.pk), text="p", citation="A v B")
        self.assertEqual(self.get(item).citation, "")
        cases = list(Case.objects.filter(item=item))
        self.assertEqual([(c.citation, c.position, c.comment) for c in cases], [("A v B", 1, "")])
        self.assertEqual(self.history_kinds(cases[0]), ["create"])
        self.assertEqual(self.history(cases[0])[0].group, self.history(item)[0].group)
        bare = self.make("item", ("subject", subject.pk), text="q")
        self.assertFalse(Case.objects.filter(item=bare).exists())

    def test_a_kind_cannot_be_given_to_a_new_item(self):
        subject = self.make("subject", name="S")
        with self.assertRaises(svc.Refused):
            self.make("item", ("subject", subject.pk), kind="nested", text="n")

    def test_the_citation_layout_can_be_set_on_creation_and_edit(self):
        subject = self.make("subject", name="S")
        item = self.make("item", ("subject", subject.pk), text="n", citation_layout="lines")
        self.assertEqual(self.get(item).citation_layout, "lines")
        svc.edit(self.profile, self.user, "item", item.pk, {"citation_layout": "inline"})
        self.assertEqual(self.get(item).citation_layout, "inline")
        with self.assertRaises(svc.ValidationFailed):
            svc.edit(self.profile, self.user, "item", item.pk, {"citation_layout": "sideways"})

    def test_parent_in_trash_refused(self):
        subject = self.make("subject", name="S")
        topic = self.make("topic", ("subject", subject.pk), name="T")
        svc.delete(self.profile, self.user, "topic", topic.pk)
        with self.assertRaises(svc.Refused):
            self.make("item", ("topic", topic.pk), text="x")


class EditTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.build_topic()

    def test_edit_bumps_version_and_writes_a_full_snapshot(self):
        result = svc.edit(self.profile, self.user2, "item", self.one.pk, {"text": "uno", "flag_text": "x"}, 1)
        self.assertTrue(result.changed)
        item = self.get(self.one)
        self.assertEqual((item.version, item.text, item.flag_text, item.updated_by), (2, "uno", "x", self.user2))
        row = self.history(self.one)[-1]
        self.assertEqual((row.version, row.change_kind, row.changed_by), (2, "edit", self.user2))
        self.assertEqual(row.snapshot["text"], "uno")
        self.assertEqual(row.snapshot["topic_id"], self.topic.pk)
        self.assertEqual(row.snapshot["position"], 1)
        self.assertEqual(row.group, result.group)

    def test_repeating_the_same_edit_changes_nothing(self):
        svc.edit(self.profile, self.user, "item", self.one.pk, {"text": "uno"}, 1)
        before = VersionHistory.objects.count()
        again = svc.edit(self.profile, self.user, "item", self.one.pk, {"text": "uno"}, 1)
        self.assertFalse(again.changed)
        self.assertIsNone(again.group)
        self.assertEqual(self.get(self.one).version, 2)
        self.assertEqual(VersionHistory.objects.count(), before)

    def test_sanitised_value_counts_as_the_same(self):
        svc.edit(self.profile, self.user, "item", self.one.pk, {"text": "<strong>x</strong>"})
        again = svc.edit(self.profile, self.user, "item", self.one.pk, {"text": "<b>x</b>"})
        self.assertFalse(again.changed)
        self.assertEqual(self.get(self.one).text, "<b>x</b>")

    def test_rich_text_is_sanitised_on_edit(self):
        svc.edit(self.profile, self.user, "item", self.one.pk, {"text": "<script>bad()</script><b>ok</b>"})
        self.assertEqual(self.get(self.one).text, "<b>ok</b>")
        self.assertEqual(self.get(self.one).text_plain, "ok")

    def test_stale_save_is_a_conflict_with_both_versions(self):
        svc.edit(self.profile, self.user, "item", self.one.pk, {"text": "theirs"}, 1)
        with self.assertRaises(svc.Conflict) as caught:
            svc.edit(self.profile, self.user2, "item", self.one.pk, {"text": "mine"}, 1)
        conflict = caught.exception
        self.assertEqual((conflict.expected_version, conflict.current_version), (1, 2))
        self.assertEqual(conflict.theirs["text"], "theirs")
        self.assertEqual(conflict.mine, {"text": "mine"})
        self.assertEqual((conflict.record_type, conflict.record_id), ("item", self.one.pk))
        self.assertEqual(self.get(self.one).text, "theirs")
        self.assertEqual(self.get(self.one).version, 2)

    def test_stale_delete_and_move_are_conflicts_too(self):
        svc.edit(self.profile, self.user, "item", self.one.pk, {"text": "theirs"}, 1)
        with self.assertRaises(svc.Conflict):
            svc.delete(self.profile, self.user2, "item", self.one.pk, 1)
        with self.assertRaises(svc.Conflict):
            svc.move(self.profile, self.user2, "item", self.one.pk, index=3, expected_version=1)
        self.assertIsNone(self.get(self.one).deleted_at)
        self.assertEqual(self.get(self.one).kind, "plain")

    def test_only_content_fields_can_be_edited(self):
        with self.assertRaises(svc.Refused):
            svc.edit(self.profile, self.user, "item", self.one.pk, {"position": 9})
        with self.assertRaises(svc.Refused):
            svc.edit(self.profile, self.user, "item", self.one.pk, {"kind": "plain"})
        with self.assertRaises(svc.Refused):
            svc.edit(self.profile, self.user, "notelink", 1, {})

    def test_bad_values_refused_and_nothing_written(self):
        for changes in ({"citation": "line one\nline two"}, {"flag": "nonsense"}):
            with self.assertRaises(svc.ValidationFailed):
                svc.edit(self.profile, self.user, "item", self.one.pk, changes)
        # The citations of an Item are Cases: its own citation column cannot be edited.
        with self.assertRaises(svc.ValidationFailed):
            svc.edit(self.profile, self.user, "item", self.one.pk, {"citation": "A v B"})
        self.assertEqual(self.get(self.one).version, 1)
        self.assertEqual(self.get(self.one).citation, "")

    def test_rename_subject_keeps_name_unique(self):
        other = self.make("subject", name="Torts")
        with self.assertRaises(svc.ValidationFailed):
            svc.edit(self.profile, self.user, "subject", other.pk, {"name": "CONTRACT"})
        svc.edit(self.profile, self.user, "subject", other.pk, {"name": "Torts II"})
        self.assertEqual(self.get(other).name, "Torts II")

    def test_edit_section_review_marker(self):
        svc.edit(self.profile, self.user, "section", self.sec.pk, {"needs_review": True, "review_note": "check"})
        sec = self.get(self.sec)
        self.assertTrue(sec.needs_review)
        self.assertEqual(self.history(self.sec)[-1].snapshot["review_note"], "check")

    def test_a_record_in_trash_cannot_be_edited(self):
        svc.delete(self.profile, self.user, "item", self.one.pk)
        with self.assertRaises(svc.Refused):
            svc.edit(self.profile, self.user, "item", self.one.pk, {"text": "x"})


class ProfileIsolationTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.build_topic()
        self.foreign = self.make("subject", profile=self.other_profile, name="Foreign")
        self.foreign_topic = self.make("topic", ("subject", self.foreign.pk), profile=self.other_profile, name="FT")
        self.foreign_item = self.make("item", ("topic", self.foreign_topic.pk), profile=self.other_profile, text="f")

    def assertUntouched(self):
        self.assertEqual(self.get(self.foreign_item).version, 1)
        self.assertIsNone(self.get(self.foreign_item).deleted_at)
        self.assertEqual(self.get(self.one).version, 1)

    def test_every_function_treats_another_profiles_id_as_missing(self):
        p, u = self.profile, self.user
        fi = self.foreign_item.pk
        calls = [
            lambda: svc.edit(p, u, "item", fi, {"text": "x"}),
            lambda: svc.delete(p, u, "item", fi),
            lambda: svc.restore(p, u, "item", fi),
            lambda: svc.permanent_delete(p, u, "item", fi),
            lambda: svc.move(p, u, "item", fi, index=0),
            lambda: svc.shift(p, u, "item", fi, 1),
            lambda: svc.preview_move(p, u, "item", fi),
            lambda: svc.preview_delete(p, u, "item", fi),
            lambda: svc.restore_version(p, u, "item", fi, 1),
            lambda: svc.create(p, u, "item", ("topic", self.foreign_topic.pk), text="x"),
            lambda: svc.create(p, u, "topic", ("subject", self.foreign.pk), name="x"),
            lambda: svc.add_link(p, u, self.make("note", ("topic", self.topic.pk), text="n").pk, ("item", fi)),
        ]
        for call in calls:
            with self.assertRaises(svc.NotFound):
                call()
        self.assertUntouched()

    def test_move_to_a_parent_in_another_profile_refused(self):
        with self.assertRaises(svc.NotFound):
            svc.move(self.profile, self.user, "item", self.one.pk, ("topic", self.foreign_topic.pk))
        self.assertEqual(self.get(self.one).topic_id, self.topic.pk)
        self.assertEqual(self.get(self.one).version, 1)

    def test_history_and_undo_of_another_profile_are_not_reachable(self):
        group = VersionHistory.objects.filter(profile=self.other_profile).first().group
        with self.assertRaises(svc.NotFound):
            svc.undo_group(self.profile, self.user, group)
        self.assertEqual(svc.history_for(self.profile, "item", self.foreign_item.pk).count(), 0)
        self.assertEqual(svc.history_for(self.other_profile, "item", self.foreign_item.pk).count(), 1)


class AtomicityTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.build_topic()

    def snapshot(self):
        return (
            list(Item.objects.order_by("pk").values_list("pk", "position", "version", "deleted_at", "topic_id")),
            VersionHistory.objects.count(),
        )

    def test_create_that_fails_half_way_changes_nothing(self):
        before = self.snapshot()
        with self.failing_history(after=1):
            with self.assertRaises(RuntimeError):
                self.make("item", ("topic", self.topic.pk), index=0, text="new")
        self.assertEqual(self.snapshot(), before)

    def test_delete_that_fails_half_way_changes_nothing(self):
        before = self.snapshot()
        with self.failing_history(after=1):
            with self.assertRaises(RuntimeError):
                svc.delete(self.profile, self.user, "topic", self.topic.pk)
        self.assertEqual(self.snapshot(), before)
        self.assertIsNone(Topic.objects.get(pk=self.topic.pk).deleted_at)
        from diary.models import TrashBatch

        self.assertEqual(TrashBatch.objects.count(), 0)

    def test_move_that_fails_half_way_changes_nothing(self):
        before = self.snapshot()
        with self.failing_history(after=1):
            with self.assertRaises(RuntimeError):
                svc.move(self.profile, self.user, "item", self.four.pk, index=0)
        self.assertEqual(self.snapshot(), before)

    def test_edit_that_fails_changes_nothing(self):
        before = self.snapshot()
        with self.failing_history(after=0):
            with self.assertRaises(RuntimeError):
                svc.edit(self.profile, self.user, "item", self.one.pk, {"text": "changed"})
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.get(self.one).text, "one")


class HistoryRestoreTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.build_topic()
        for number, text in enumerate(("v2", "v3", "v4"), start=1):
            svc.edit(self.profile, self.user, "item", self.one.pk, {"text": text}, number)

    def test_history_lists_every_version_newest_first(self):
        rows = list(svc.history_for(self.profile, "item", self.one.pk))
        self.assertEqual([r.version for r in rows], [4, 3, 2, 1])

    def test_restore_version_creates_a_new_version_and_keeps_history(self):
        result = svc.restore_version(self.profile, self.user, "item", self.one.pk, 2, expected_version=4)
        self.assertTrue(result.changed)
        item = self.get(self.one)
        self.assertEqual((item.text, item.version), ("v2", 5))
        self.assertEqual(self.history_kinds(self.one), ["create", "edit", "edit", "edit", "restore"])
        self.assertEqual([r.snapshot["text"] for r in self.history(self.one)], ["one", "v2", "v3", "v4", "v2"])

    def test_restore_of_the_current_content_changes_nothing(self):
        result = svc.restore_version(self.profile, self.user, "item", self.one.pk, 4)
        self.assertFalse(result.changed)
        self.assertEqual(self.get(self.one).version, 4)

    def test_restore_version_checks_the_version_and_the_number(self):
        with self.assertRaises(svc.Conflict):
            svc.restore_version(self.profile, self.user, "item", self.one.pk, 2, expected_version=2)
        with self.assertRaises(svc.NotFound):
            svc.restore_version(self.profile, self.user, "item", self.one.pk, 99)

    def test_restore_version_does_not_move_the_item(self):
        svc.move(self.profile, self.user, "item", self.one.pk, index=3)
        moved_to = self.get(self.one).position
        svc.restore_version(self.profile, self.user, "item", self.one.pk, 1)
        self.assertEqual(self.get(self.one).position, moved_to)
        self.assertEqual(self.get(self.one).text, "one")

    def test_restore_of_an_old_nested_version_maps_its_citation_to_case_a(self):
        # A version saved before round 10 may say kind "nested" and carry the Item's own citation.
        row = VersionHistory.objects.get(record_type="item", record_id=self.one.pk, version=1)
        row.snapshot = {**row.snapshot, "kind": "nested", "citation": "N v M"}
        row.save()
        svc.edit(self.profile, self.user, "item", self.one.pk, {"text": "<p>newer words</p>"})
        svc.restore_version(self.profile, self.user, "item", self.one.pk, 1)
        item = self.get(self.one)
        self.assertEqual((item.kind, item.citation), ("plain", ""))
        self.assertEqual([c.citation for c in Case.objects.filter(item=item, deleted_at__isnull=True)], ["N v M"])


class LandingTests(ServiceTestCase):
    def test_a_subject_moves_between_the_two_lists_and_takes_the_next_free_number(self):
        a = self.make("subject", name="A")
        b = self.make("subject", name="B")
        c = self.make("subject", name="C")
        other = self.make("subject", name="Other", show_on_landing=False)
        result = svc.set_landing(self.profile, self.user, a.pk, False)
        self.assertTrue(result.changed)
        self.assertFalse(self.get(a).show_on_landing)
        self.assertEqual(self.get(a).other_acts_position, 2)
        self.assertEqual(self.get(other).other_acts_position, 1)
        # the list it left is not renumbered (stored Word order kept)
        self.assertEqual((self.get(b).landing_position, self.get(c).landing_position), (2, 3))
        self.assertEqual(self.get(b).version, 1)
        self.assertEqual(self.history_kinds(a), ["create", "move"])
        svc.set_landing(self.profile, self.user, a.pk, True)
        self.assertEqual((self.get(b).landing_position, self.get(c).landing_position, self.get(a).landing_position), (2, 3, 4))
        self.assertEqual([x.name for x in members(self.profile.pk, ("subject", "show", True))], ["A", "B", "C"])

    def test_repeating_the_same_choice_changes_nothing(self):
        a = self.make("subject", name="A")
        count = VersionHistory.objects.count()
        self.assertFalse(svc.set_landing(self.profile, self.user, a.pk, True).changed)
        self.assertEqual(VersionHistory.objects.count(), count)

    def test_stale_version_is_a_conflict_and_other_profiles_are_not_found(self):
        a = self.make("subject", name="A")
        svc.edit(self.profile, self.user, "subject", a.pk, {"name": "A2"})
        with self.assertRaises(svc.Conflict):
            svc.set_landing(self.profile, self.user, a.pk, False, expected_version=1)
        foreign = self.make("subject", profile=self.other_profile, name="Foreign")
        with self.assertRaises(svc.NotFound):
            svc.set_landing(self.profile, self.user, foreign.pk, False)
