"""Conversions between Item and Nested Item (service layer, docs/DESIGN.md section 6; Multi-Item is gone since 10d)."""
from diary import services as svc
from diary.models import Case, Item, TrashBatch
from diary.tests.service_helpers import ServiceTestCase


class ConversionTestCase(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.build_topic()
        self.parent = ("topic", self.topic.pk)

    def convert(self, item, kind, **kwargs):
        return svc.convert_item(self.profile, self.user, item.pk, kind, **kwargs)

    def item_with_cases(self, comments=("<b>note</b>", "")):
        item = self.make("item", self.parent, text="m")
        self.make("case", ("item", item.pk), citation="A v B", comment=comments[0])
        self.make("case", ("item", item.pk), citation="C v D", comment=comments[1])
        return item

    def nested_with_kids(self, kids=(("<i>c1</i>", "K1"), ("c2", "K2"))):
        nested = self.make("item", self.parent, kind="nested", text="n", citation="N v M")
        made = [self.make("item", ("item", nested.pk), text=text, citation=cite) for text, cite in kids]
        return nested, made

    def live_cases(self, item):
        rows = Case._base_manager.filter(item=item, deleted_at__isnull=True).order_by("position", "pk")
        return [(c.citation, c.comment, c.position) for c in rows]

    def live_kids(self, item):
        rows = Item._base_manager.filter(parent_item=item, deleted_at__isnull=True).order_by("position", "pk")
        return [(k.text, self.kid_citation(k), k.position) for k in rows]

    def kid_citation(self, kid):
        """The citations of a child Item (its Cases, in order) as one string."""
        rows = Case._base_manager.filter(item=kid, deleted_at__isnull=True).order_by("position", "pk")
        return "; ".join(c.citation for c in rows)

    def shape(self, item):
        item = self.get(item)
        return (
            item.kind, item.citation, item.text, item.deleted_at,
            self.live_cases(item), self.live_kids(item), self.numbered(self.topic),
        )


class SimpleConversionTests(ConversionTestCase):
    def test_item_with_one_citation_to_nested_moves_it_to_the_nested_citation(self):
        item = self.make("item", self.parent, text="m", citation="A v B")
        self.assertEqual(self.live_cases(item), [("A v B", "", 1)])
        self.assertEqual(self.get(item).citation, "")
        result = self.convert(item, "nested")
        self.assertTrue(result.changed)
        after = self.get(item)
        self.assertEqual((after.kind, after.citation), ("nested", "A v B"))
        self.assertEqual(self.live_cases(after), [])
        self.assertEqual(self.live_kids(after), [])
        trashed = list(Case._base_manager.filter(item=item))
        self.assertEqual(len(trashed), 1)
        self.assertTrue(TrashBatch.objects.get(pk=trashed[0].delete_batch).label.startswith("Removed by conversion"))
        self.assertEqual(self.history_kinds(item), ["create", "convert"])
        self.assertEqual(self.history(item)[-1].group, result.group)

    def test_item_with_several_citations_to_nested_turns_them_into_items_beneath(self):
        item = self.item_with_cases(comments=("<i>x</i>", ""))
        self.convert(item, "nested")
        after = self.get(item)
        self.assertEqual((after.kind, after.citation), ("nested", ""))
        self.assertEqual(self.live_cases(after), [])
        self.assertEqual(self.live_kids(after), [("<i>x</i>", "A v B", 1), ("", "C v D", 2)])
        self.assertEqual({k.kind for k in Item.objects.filter(parent_item=after)}, {"plain"})

    def test_one_citation_with_a_comment_to_nested_keeps_the_comment_as_an_item_beneath(self):
        item = self.make("item", self.parent, text="m")
        self.make("case", ("item", item.pk), citation="A v B", comment="<b>note</b>")
        self.convert(item, "nested")
        after = self.get(item)
        self.assertEqual((after.kind, after.citation), ("nested", ""))
        self.assertEqual(self.live_kids(after), [("<b>note</b>", "A v B", 1)])

    def test_item_to_nested_keeps_text(self):
        self.convert(self.one, "nested")
        item = self.get(self.one)
        self.assertEqual((item.kind, item.citation, item.text), ("nested", "", "one"))
        child = self.make("item", ("item", self.one.pk), text="child")
        self.assertEqual(self.get(child).parent_item_id, self.one.pk)

    def test_nested_without_children_converts_directly_and_its_citation_becomes_case_a(self):
        nested = self.make("item", self.parent, kind="nested", text="n", citation="N v M")
        self.assertEqual(self.get(nested).citation, "N v M")
        self.convert(nested, "plain")
        item = self.get(nested)
        self.assertEqual((item.kind, item.citation), ("plain", ""))
        self.assertEqual(self.live_cases(item), [("N v M", "", 1)])
        case = Case.objects.get(item=item)
        self.assertEqual(self.history_kinds(case), ["convert"])

    def test_nested_without_citation_makes_no_case(self):
        nested = self.make("item", self.parent, kind="nested", text="n")
        self.convert(nested, "plain")
        self.assertEqual(self.live_cases(self.get(nested)), [])

    def test_converting_to_the_same_type_changes_nothing(self):
        count = len(self.history(self.one))
        result = self.convert(self.one, "plain", expected_version=99)
        self.assertFalse(result.changed)
        self.assertEqual(self.get(self.one).version, 1)
        self.assertEqual(len(self.history(self.one)), count)

    def test_converting_twice_is_harmless(self):
        self.convert(self.one, "nested")
        again = self.convert(self.one, "nested")
        self.assertFalse(again.changed)
        self.assertEqual(self.get(self.one).version, 2)

    def test_preview_writes_nothing(self):
        item = self.item_with_cases()
        before = self.shape(item)
        svc.preview_conversion(self.profile, self.user, item.pk, "nested")
        self.assertEqual(self.shape(item), before)
        self.assertEqual(self.get(item).version, 1)

    def test_preview_of_item_to_nested_lists_the_citations_with_labels(self):
        item = self.item_with_cases()
        preview = svc.preview_conversion(self.profile, self.user, item.pk, "nested")
        self.assertEqual([c["label"] for c in preview["before"]["cases"]], ["(a)", "(b)"])
        self.assertEqual(preview["warnings"], [])
        self.assertEqual(len(preview["after"]["children"]), 2)
        single = self.make("item", self.parent, text="s", citation="A v B")
        preview = svc.preview_conversion(self.profile, self.user, single.pk, "nested")
        self.assertEqual([c["label"] for c in preview["before"]["cases"]], [""])
        self.assertEqual(preview["after"]["citation"], "A v B")

    def test_an_item_beneath_a_nested_item_cannot_be_converted(self):
        nested, kids = self.nested_with_kids()
        with self.assertRaises(svc.Refused):
            self.convert(kids[0], "nested")
        self.assertEqual(self.get(kids[0]).kind, "plain")

    def test_multi_is_not_a_type_any_more(self):
        with self.assertRaises(svc.Refused):
            self.convert(self.one, "multi")
        with self.assertRaises(svc.Refused):
            svc.preview_conversion(self.profile, self.user, self.one.pk, "multi")

    def test_unknown_type_and_items_in_trash_are_refused(self):
        with self.assertRaises(svc.Refused):
            self.convert(self.one, "bogus")
        svc.delete(self.profile, self.user, "item", self.one.pk)
        with self.assertRaises(svc.Refused):
            self.convert(self.one, "nested")

    def test_a_failing_conversion_changes_nothing(self):
        item = self.item_with_cases()
        before = self.shape(item)
        with self.failing_history(after=3):
            with self.assertRaises(RuntimeError):
                self.convert(item, "nested")
        self.assertEqual(self.shape(item), before)
        self.assertEqual(self.get(item).version, 1)
        self.assertEqual(TrashBatch.objects.count(), 0)

    def test_a_case_cannot_be_restored_into_a_nested_item(self):
        item = self.make("item", self.parent, text="m", citation="A v B")
        self.convert(item, "nested")
        case = Case._base_manager.filter(item=item).first()
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
        self.assertEqual((item.kind, item.citation), ("plain", ""))
        self.assertEqual(self.live_cases(item), [("N v M", "", 1)])
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
            self.assertEqual(len(self.live_cases(kid)), 1)  # their own citations stay with them
        self.assertEqual(self.positions([nested, kids[0], kids[1], later]), [6, 7, 8, 9])
        self.assertEqual(self.history_kinds(kids[0])[-1], "convert")

    def test_fold_turns_the_citation_and_the_children_into_cases(self):
        nested, kids = self.nested_with_kids()
        preview = svc.preview_conversion(self.profile, self.user, nested.pk, "plain", option="fold")
        self.assertEqual(preview["warnings"], [])
        self.assertEqual([c["label"] for c in preview["after"]["cases"]], ["(a)", "(b)", "(c)"])
        self.convert(nested, "plain", option="fold")
        item = self.get(nested)
        self.assertEqual((item.kind, item.citation), ("plain", ""))
        self.assertEqual(
            self.live_cases(item),
            [("N v M", "", 1), ("K1", "<i>c1</i>", 2), ("K2", "c2", 3)],
        )
        self.assertEqual(self.live_kids(item), [])
        for kid in kids:
            self.assertIsNotNone(self.get(kid).deleted_at)
            self.assertTrue(all(c.deleted_at for c in Case._base_manager.filter(item=kid)))
        self.assertEqual(len({self.get(k).delete_batch for k in kids}), 1)
        self.assertEqual({c.delete_batch for c in Case._base_manager.filter(item__in=kids)}, {self.get(kids[0]).delete_batch})

    def test_fold_without_a_nested_citation_starts_with_the_first_child(self):
        nested = self.make("item", self.parent, kind="nested", text="n")
        self.make("item", ("item", nested.pk), text="c1", citation="K1")
        self.convert(nested, "plain", option="fold")
        self.assertEqual(self.live_cases(self.get(nested)), [("K1", "c1", 1)])

    def test_folding_is_refused_for_flags_review_markers_notes_and_several_citations(self):
        nested, kids = self.nested_with_kids(kids=(("k0", "K0"), ("k1", "K1"), ("k2", "K2"), ("k3", "K3")))
        svc.edit(self.profile, self.user, "item", kids[0].pk, {"flag": "overruled"})
        svc.edit(self.profile, self.user, "item", kids[1].pk, {"needs_review": True})
        self.make("note", ("item", kids[2].pk), text="a note")
        self.make("case", ("item", kids[3].pk), citation="second")
        preview = svc.preview_conversion(self.profile, self.user, nested.pk, "plain")
        fold = preview["options"][1]
        self.assertFalse(fold["available"])
        self.assertEqual(
            fold["reasons"],
            ["'k0' has a flag.", "'k1' is marked For review.", "'k2' has a Note.", "'k3' has several citations."],
        )
        self.assertTrue(preview["options"][0]["available"])
        before = self.shape(nested)
        with self.assertRaises(svc.Refused) as caught:
            self.convert(nested, "plain", option="fold")
        self.assertEqual(caught.exception.reasons, fold["reasons"])
        self.assertIn("Keep them as separate Items", caught.exception.message)
        self.assertEqual(self.shape(nested), before)
        # The other choice is still open.
        self.convert(nested, "plain", option="keep")
        self.assertEqual(self.get(nested).kind, "plain")

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

    def test_undo_item_with_one_citation_to_nested(self):
        item = self.make("item", self.parent, text="m", citation="A v B")
        self.assertUndoRestoresExactly(item, "nested")

    def test_undo_item_with_several_citations_to_nested(self):
        self.assertUndoRestoresExactly(self.item_with_cases(), "nested")

    def test_undo_nested_keep_to_item(self):
        nested, _kids = self.nested_with_kids()
        self.assertUndoRestoresExactly(nested, "plain", option="keep")

    def test_undo_nested_fold_to_item(self):
        nested, _kids = self.nested_with_kids()
        self.assertUndoRestoresExactly(nested, "plain", option="fold")

    def test_convert_there_and_back_keeps_the_id_and_history(self):
        item = self.make("item", self.parent, text="m", citation="A v B")
        self.convert(item, "nested")
        self.convert(item, "plain")
        after = self.get(item)
        self.assertEqual((after.pk, after.kind, after.citation), (item.pk, "plain", ""))
        self.assertEqual(self.live_cases(after), [("A v B", "", 1)])
        self.assertEqual(self.history_kinds(item), ["create", "convert", "convert"])
