"""Conversions between Item, Multi-Item and Nested Item (service layer, docs/DESIGN.md section 6)."""
from diary import services as svc
from diary.models import Case, Item, TrashBatch
from diary.services.conversions import FLATTEN_WARNING
from diary.tests.service_helpers import ServiceTestCase


class ConversionTestCase(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.build_topic()
        self.parent = ("topic", self.topic.pk)

    def convert(self, item, kind, **kwargs):
        return svc.convert_item(self.profile, self.user, item.pk, kind, **kwargs)

    def multi_with_cases(self, comments=("<b>note</b>", "")):
        multi = self.make("item", self.parent, kind="multi", text="m")
        self.make("case", ("item", multi.pk), citation="A v B", comment=comments[0])
        self.make("case", ("item", multi.pk), citation="C v D", comment=comments[1])
        return multi

    def nested_with_kids(self, kids=(("<i>c1</i>", "K1"), ("c2", "K2"))):
        nested = self.make("item", self.parent, kind="nested", text="n", citation="N v M")
        made = [self.make("item", ("item", nested.pk), text=text, citation=cite) for text, cite in kids]
        return nested, made

    def live_cases(self, item):
        rows = Case._base_manager.filter(item=item, deleted_at__isnull=True).order_by("position", "pk")
        return [(c.citation, c.comment, c.position) for c in rows]

    def live_kids(self, item):
        rows = Item._base_manager.filter(parent_item=item, deleted_at__isnull=True).order_by("position", "pk")
        return [(k.text, k.citation, k.position) for k in rows]

    def shape(self, item):
        item = self.get(item)
        return (
            item.kind, item.citation, item.text, item.deleted_at,
            self.live_cases(item), self.live_kids(item), self.numbered(self.topic),
        )


class SimpleConversionTests(ConversionTestCase):
    def test_item_to_multi_turns_the_citation_into_case_a(self):
        svc.edit(self.profile, self.user, "item", self.one.pk, {"citation": "A v B"})
        result = self.convert(self.one, "multi")
        self.assertTrue(result.changed)
        item = self.get(self.one)
        self.assertEqual((item.pk, item.kind, item.citation, item.version), (self.one.pk, "multi", "", 3))
        self.assertEqual(self.live_cases(item), [("A v B", "", 1)])
        self.assertEqual(self.history_kinds(self.one), ["create", "edit", "convert"])
        case = Case.objects.get(item=item)
        self.assertEqual(self.history_kinds(case), ["convert"])
        self.assertEqual(self.history(case)[0].group, result.group)
        self.assertEqual(self.history(self.one)[-1].group, result.group)

    def test_multi_to_item_joins_citations_and_warns_about_comments(self):
        multi = self.multi_with_cases()
        preview = svc.preview_conversion(self.profile, self.user, multi.pk, "plain")
        self.assertEqual(preview["warnings"], [FLATTEN_WARNING])
        self.assertEqual(preview["refusal"], "")
        self.assertEqual([c["label"] for c in preview["before"]["cases"]], ["(a)", "(b)"])
        self.assertEqual(preview["after"]["citation"], "(a) A v B - note; (b) C v D")
        self.assertEqual(preview["after"]["kind"], "plain")
        with self.assertRaises(svc.ConfirmationRequired) as caught:
            self.convert(multi, "plain")
        self.assertEqual(caught.exception.warnings, [FLATTEN_WARNING])
        self.assertEqual(self.get(multi).kind, "multi")
        self.assertEqual(len(self.live_cases(multi)), 2)

        self.convert(multi, "plain", accept_warnings=True)
        item = self.get(multi)
        self.assertEqual((item.kind, item.citation), ("plain", "(a) A v B - note; (b) C v D"))
        self.assertEqual(self.live_cases(item), [])
        trashed = list(Case._base_manager.filter(item=item))
        self.assertEqual(len(trashed), 2)
        self.assertEqual(len({c.delete_batch for c in trashed}), 1)
        self.assertIsNotNone(trashed[0].delete_batch)
        self.assertTrue(TrashBatch.objects.get(pk=trashed[0].delete_batch).label.startswith("Removed by conversion"))

    def test_multi_without_comments_needs_no_confirmation(self):
        multi = self.make("item", self.parent, kind="multi", text="m")
        self.make("case", ("item", multi.pk), citation="A v B")
        preview = svc.preview_conversion(self.profile, self.user, multi.pk, "plain")
        self.assertEqual(preview["warnings"], [])
        self.convert(multi, "plain")
        self.assertEqual(self.get(multi).citation, "A v B")

    def test_a_joined_citation_that_is_too_long_is_refused(self):
        multi = self.make("item", self.parent, kind="multi", text="m")
        for n in range(3):
            self.make("case", ("item", multi.pk), citation="x" * 400)
        preview = svc.preview_conversion(self.profile, self.user, multi.pk, "plain")
        self.assertIn("1000", preview["refusal"])
        with self.assertRaises(svc.Refused):
            self.convert(multi, "plain")
        self.assertEqual(self.get(multi).kind, "multi")

    def test_item_to_nested_keeps_text_and_citation(self):
        svc.edit(self.profile, self.user, "item", self.one.pk, {"citation": "A v B"})
        self.convert(self.one, "nested")
        item = self.get(self.one)
        self.assertEqual((item.kind, item.citation, item.text), ("nested", "A v B", "one"))
        child = self.make("item", ("item", self.one.pk), text="child")
        self.assertEqual(self.get(child).parent_item_id, self.one.pk)

    def test_multi_to_nested_turns_cases_into_items_beneath(self):
        multi = self.multi_with_cases(comments=("<i>x</i>", ""))
        self.convert(multi, "nested")
        item = self.get(multi)
        self.assertEqual((item.kind, item.citation), ("nested", ""))
        self.assertEqual(self.live_cases(item), [])
        self.assertEqual(self.live_kids(item), [("<i>x</i>", "A v B", 1), ("", "C v D", 2)])
        self.assertEqual({k.kind for k in Item.objects.filter(parent_item=item)}, {"plain"})

    def test_nested_without_children_converts_directly(self):
        nested = self.make("item", self.parent, kind="nested", text="n", citation="N v M")
        self.convert(nested, "plain")
        self.assertEqual((self.get(nested).kind, self.get(nested).citation), ("plain", "N v M"))
        nested2 = self.make("item", self.parent, kind="nested", text="n2", citation="P v Q")
        self.convert(nested2, "multi")
        self.assertEqual((self.get(nested2).kind, self.get(nested2).citation), ("multi", ""))
        self.assertEqual(self.live_cases(nested2), [("P v Q", "", 1)])

    def test_converting_to_the_same_type_changes_nothing(self):
        count = len(self.history(self.one))
        result = self.convert(self.one, "plain", expected_version=99)
        self.assertFalse(result.changed)
        self.assertEqual(self.get(self.one).version, 1)
        self.assertEqual(len(self.history(self.one)), count)

    def test_converting_twice_is_harmless(self):
        self.convert(self.one, "multi")
        again = self.convert(self.one, "multi")
        self.assertFalse(again.changed)
        self.assertEqual(len(self.live_cases(self.get(self.one))), 1)

    def test_preview_writes_nothing(self):
        multi = self.multi_with_cases()
        before = self.shape(multi)
        svc.preview_conversion(self.profile, self.user, multi.pk, "plain")
        svc.preview_conversion(self.profile, self.user, multi.pk, "nested")
        self.assertEqual(self.shape(multi), before)
        self.assertEqual(self.get(multi).version, 1)

    def test_an_item_beneath_a_nested_item_cannot_be_converted(self):
        nested, kids = self.nested_with_kids()
        for target in ("multi", "nested"):
            with self.assertRaises(svc.Refused):
                self.convert(kids[0], target)
        self.assertEqual(self.get(kids[0]).kind, "plain")

    def test_unknown_type_and_items_in_trash_are_refused(self):
        with self.assertRaises(svc.Refused):
            self.convert(self.one, "bogus")
        svc.delete(self.profile, self.user, "item", self.one.pk)
        with self.assertRaises(svc.Refused):
            self.convert(self.one, "multi")

    def test_a_failing_conversion_changes_nothing(self):
        multi = self.multi_with_cases()
        before = self.shape(multi)
        with self.failing_history(after=3):
            with self.assertRaises(RuntimeError):
                self.convert(multi, "nested")
        self.assertEqual(self.shape(multi), before)
        self.assertEqual(self.get(multi).version, 1)
        self.assertEqual(TrashBatch.objects.count(), 0)

    def test_a_case_cannot_be_restored_into_a_plain_item(self):
        multi = self.multi_with_cases()
        self.convert(multi, "plain", accept_warnings=True)
        case = Case._base_manager.filter(item=multi).first()
        with self.assertRaises(svc.Refused):
            svc.restore(self.profile, self.user, "case", case.pk)


class NestedConversionTests(ConversionTestCase):
    def test_children_force_a_choice(self):
        nested, kids = self.nested_with_kids()
        preview = svc.preview_conversion(self.profile, self.user, nested.pk, "plain")
        self.assertTrue(preview["needs_option"])
        self.assertIsNone(preview["after"])
        self.assertEqual(
            preview["options"],
            [
                {"key": "keep", "available": True, "reasons": []},
                {"key": "fold", "available": True, "reasons": []},
            ],
        )
        self.assertEqual(len(preview["before"]["children"]), 2)
        with self.assertRaises(svc.Refused):
            self.convert(nested, "plain")
        self.assertEqual(self.get(nested).kind, "nested")

    def test_keep_moves_the_children_to_sit_right_after_it(self):
        nested, kids = self.nested_with_kids(kids=(("k1", "K1"), ("k2", "K2")))
        later = self.make("item", self.parent, text="later")
        self.convert(nested, "plain", option="keep")
        item = self.get(nested)
        self.assertEqual((item.kind, item.citation), ("plain", "N v M"))
        self.assertEqual(self.live_kids(item), [])
        self.assertEqual(
            [name for _label, name in self.numbered(self.topic)],
            ["one", "two", "S", "three", "four", "n", "k1", "k2", "later"],
        )
        self.assertEqual(
            [label for label, _name in self.numbered(self.topic)][5:],
            ["(3)", "(4)", "(5)", "(6)"],
        )
        for kid in kids:
            self.assertEqual((self.get(kid).parent_item_id, self.get(kid).topic_id), (None, self.topic.pk))
        self.assertEqual(self.positions([nested, kids[0], kids[1], later]), [6, 7, 8, 9])
        self.assertEqual(self.history_kinds(kids[0])[-1], "convert")

    def test_keep_to_multi_makes_the_nested_citation_case_a(self):
        nested, kids = self.nested_with_kids(kids=(("k1", "K1"),))
        self.convert(nested, "multi", option="keep")
        item = self.get(nested)
        self.assertEqual((item.kind, item.citation), ("multi", ""))
        self.assertEqual(self.live_cases(item), [("N v M", "", 1)])
        self.assertIsNone(self.get(kids[0]).parent_item_id)

    def test_fold_to_multi_turns_children_into_cases(self):
        nested, kids = self.nested_with_kids()
        self.convert(nested, "multi", option="fold")
        item = self.get(nested)
        self.assertEqual((item.kind, item.citation), ("multi", ""))
        self.assertEqual(
            self.live_cases(item),
            [("N v M", "", 1), ("K1", "<i>c1</i>", 2), ("K2", "c2", 3)],
        )
        self.assertEqual(self.live_kids(item), [])
        for kid in kids:
            self.assertIsNotNone(self.get(kid).deleted_at)
        self.assertEqual(len({self.get(k).delete_batch for k in kids}), 1)

    def test_fold_to_item_joins_everything_into_the_citation(self):
        nested, kids = self.nested_with_kids()
        with self.assertRaises(svc.ConfirmationRequired):
            self.convert(nested, "plain", option="fold")
        self.convert(nested, "plain", option="fold", accept_warnings=True)
        item = self.get(nested)
        self.assertEqual((item.kind, item.citation), ("plain", "(a) N v M; (b) K1 - c1; (c) K2 - c2"))
        self.assertEqual(self.live_cases(item), [])
        self.assertTrue(all(self.get(k).deleted_at for k in kids))

    def test_folding_is_refused_for_flags_review_markers_and_notes(self):
        nested, kids = self.nested_with_kids(kids=(("k0", "K0"), ("k1", "K1"), ("k2", "K2"), ("k3", "K3")))
        svc.edit(self.profile, self.user, "item", kids[0].pk, {"flag": "overruled"})
        svc.edit(self.profile, self.user, "item", kids[1].pk, {"needs_review": True})
        self.make("note", ("item", kids[2].pk), text="a note")
        preview = svc.preview_conversion(self.profile, self.user, nested.pk, "multi")
        fold = preview["options"][1]
        self.assertFalse(fold["available"])
        self.assertEqual(
            fold["reasons"], ["'k0' has a flag.", "'k1' is marked For review.", "'k2' has a Note."]
        )
        self.assertTrue(preview["options"][0]["available"])
        before = self.shape(nested)
        with self.assertRaises(svc.Refused) as caught:
            self.convert(nested, "multi", option="fold")
        self.assertEqual(caught.exception.reasons, fold["reasons"])
        self.assertIn("Keep them as separate Items", caught.exception.message)
        self.assertEqual(self.shape(nested), before)
        # The other choice is still open.
        self.convert(nested, "multi", option="keep")
        self.assertEqual(self.get(nested).kind, "multi")

    def test_the_refusal_is_shown_in_the_preview_for_the_chosen_option(self):
        nested, kids = self.nested_with_kids(kids=(("k0", "K0"),))
        svc.edit(self.profile, self.user, "item", kids[0].pk, {"flag": "doubted"})
        preview = svc.preview_conversion(self.profile, self.user, nested.pk, "plain", option="fold")
        self.assertTrue(preview["refusal"])
        self.assertEqual(preview["reasons"], ["'k0' has a flag."])
        self.assertIsNone(preview["after"])


class ConversionUndoTests(ConversionTestCase):
    def assertUndoRestoresExactly(self, item, kind, **kwargs):
        before = self.shape(item)
        result = self.convert(item, kind, **kwargs)
        self.assertNotEqual(self.shape(item), before)
        svc.undo_group(self.profile, self.user, result.group)
        self.assertEqual(self.shape(item), before)

    def test_undo_item_to_multi(self):
        svc.edit(self.profile, self.user, "item", self.one.pk, {"citation": "A v B"})
        self.assertUndoRestoresExactly(self.one, "multi")

    def test_undo_multi_to_item(self):
        self.assertUndoRestoresExactly(self.multi_with_cases(), "plain", accept_warnings=True)

    def test_undo_multi_to_nested(self):
        self.assertUndoRestoresExactly(self.multi_with_cases(), "nested")

    def test_undo_nested_keep_to_item(self):
        nested, _kids = self.nested_with_kids()
        self.assertUndoRestoresExactly(nested, "plain", option="keep")

    def test_undo_nested_keep_to_multi(self):
        nested, _kids = self.nested_with_kids()
        self.assertUndoRestoresExactly(nested, "multi", option="keep")

    def test_undo_nested_fold_to_multi(self):
        nested, _kids = self.nested_with_kids()
        self.assertUndoRestoresExactly(nested, "multi", option="fold")

    def test_undo_nested_fold_to_item(self):
        nested, _kids = self.nested_with_kids()
        self.assertUndoRestoresExactly(nested, "plain", option="fold", accept_warnings=True)

    def test_convert_there_and_back_keeps_the_id_and_history(self):
        svc.edit(self.profile, self.user, "item", self.one.pk, {"citation": "A v B"})
        self.convert(self.one, "multi")
        self.convert(self.one, "plain")
        item = self.get(self.one)
        self.assertEqual((item.pk, item.kind, item.citation), (self.one.pk, "plain", "A v B"))
        self.assertEqual(self.history_kinds(self.one), ["create", "edit", "convert", "convert"])
