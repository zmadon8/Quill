"""Round 10: Nested Items are gone. The mapping (diary/nested_conversion.py): pure rules, the old-backup-file
mapping, and the data migration 0015 run on a database built at the schema before it."""
import uuid
from unittest import mock

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.exceptions import IrreversibleError
from django.test import SimpleTestCase, TransactionTestCase

from diary import nested_conversion as nc

BEFORE = [("diary", "0014_item_citation_layout")]
AFTER = [("diary", "0015_convert_nested_items")]


def child(id_, text="", cases=(), **kw):
    base = {"id": id_, "text": text, "flag": "none", "flag_text": "", "needs_review": False, "review_note": "",
            "cases": [{"id": i, "citation": c, "comment": m} for i, c, m in cases], "notes": 0, "links": 0}
    base.update(kw)
    return base


def parent(citation="", **kw):
    return {"citation": citation, "review_note": "", "needs_review": False, "cases": [], **kw}


class CommentRulesTests(SimpleTestCase):
    def test_child_text_comes_first_then_the_existing_comment(self):
        self.assertEqual(nc.combine_comment("<p>The rule</p>", "<p>at para 4</p>"), "<p>The rule - at para 4</p>")

    def test_more_paragraphs_are_kept(self):
        self.assertEqual(nc.combine_comment("<p>One</p><p>Two</p>", "<p>Three</p><p>Four</p>"),
                         "<p>One</p><p>Two - Three</p><p>Four</p>")

    def test_plain_text_stays_plain(self):
        self.assertEqual(nc.combine_comment("The rule", "at para 4"), "The rule - at para 4")

    def test_an_empty_side_gives_the_other_side_unchanged(self):
        self.assertEqual(nc.combine_comment("<p>The rule</p>", ""), "<p>The rule</p>")
        self.assertEqual(nc.combine_comment("", "<p>c</p>"), "<p>c</p>")
        self.assertEqual(nc.combine_comment("  ", "c"), "c")
        self.assertEqual(nc.combine_comment("", ""), "")

    def test_flag_and_review_suffix(self):
        self.assertEqual(nc.flag_suffix("none", "", False, ""), "")
        self.assertEqual(nc.flag_suffix("overruled", "by X v Y", False, ""), "[Overruled: by X v Y]")
        self.assertEqual(nc.flag_suffix("doubted", "", True, "check <it>"), "[Doubted] [For review: check &lt;it&gt;]")
        self.assertEqual(nc.flag_suffix("none", "", True, ""), "[For review]")

    def test_suffix_goes_inside_the_last_paragraph(self):
        self.assertEqual(nc.append_suffix("<p>One</p><p>Two</p>", "[x]"), "<p>One</p><p>Two [x]</p>")
        self.assertEqual(nc.append_suffix("plain", "[x]"), "plain [x]")
        self.assertEqual(nc.append_suffix("", "[x]"), "[x]")
        self.assertEqual(nc.append_suffix("<p>a</p>", ""), "<p>a</p>")

    def test_letters(self):
        self.assertEqual([nc.letters(n) for n in (1, 2, 26, 27)], ["a", "b", "z", "aa"])

    def test_every_kind_maps_to_plain_and_old_citations_map_to_case_a(self):
        self.assertEqual((nc.map_kind("nested"), nc.map_kind("multi"), nc.map_kind("plain")), ("plain",) * 3)
        self.assertEqual(nc.old_snapshot_citation({"citation": "A v B", "kind": "nested"}), "A v B")
        self.assertIsNone(nc.old_snapshot_citation({"citation": ""}))
        self.assertIsNone(nc.old_snapshot_citation({}))


class PlanGroupTests(SimpleTestCase):
    def test_own_citation_is_case_a_then_each_child_in_order(self):
        plan = nc.plan_group(parent("N v M"), [
            child(1, "<p>first</p>", [(11, "A v B", "")]),
            child(2, "<p>second</p>", [(12, "C v D", "<p>c</p>"), (13, "E v F", "")]),
        ])
        self.assertEqual([(s.existing_id, s.citation, s.comment) for s in plan.cases], [
            (None, "N v M", ""),
            (11, "A v B", "<p>first</p>"),
            (12, "C v D", "<p>second - c</p>"),
            (13, "E v F", ""),  # only the FIRST citation of a child carries the child's text
        ])
        self.assertEqual((plan.layout, plan.needs_review, plan.folded), ("lines", True, [1, 2]))
        self.assertIn("2 sub-item(s)", plan.review_note)

    def test_a_child_without_a_citation_becomes_a_case_with_an_empty_citation(self):
        plan = nc.plan_group(parent(), [child(1, "<p>only words</p>")])
        self.assertEqual([(s.existing_id, s.citation, s.comment) for s in plan.cases], [(None, "", "<p>only words</p>")])

    def test_child_flag_and_review_marker_are_kept_in_the_comment(self):
        plan = nc.plan_group(parent("N v M"), [
            child(1, "<p>words</p>", [(11, "A v B", "")], flag="overruled", flag_text="by X", needs_review=True,
                  review_note="odd"),
        ])
        self.assertEqual(plan.cases[1].comment, "<p>words [Overruled: by X] [For review: odd]</p>")
        self.assertIn("1 sub-item(s) had a flag or review marker", plan.review_note)

    def test_a_child_with_nothing_in_it_is_folded_without_a_case(self):
        plan = nc.plan_group(parent("N v M"), [child(1, ""), child(2, "<p>x</p>")])
        self.assertEqual(plan.empty_children, [1])
        self.assertEqual(plan.folded, [1, 2])
        self.assertEqual(len(plan.cases), 2)

    def test_the_existing_review_note_is_kept_and_extended(self):
        plan = nc.plan_group(parent("N v M", review_note="old note", needs_review=False), [child(1, "<p>x</p>")])
        self.assertTrue(plan.review_note.startswith("old note\n"))
        self.assertTrue(plan.needs_review)

    def test_without_children_the_citation_just_moves_and_nothing_is_flagged(self):
        plan = nc.plan_group(parent("N v M", review_note="keep", needs_review=False), [])
        self.assertEqual([(s.existing_id, s.citation) for s in plan.cases], [(None, "N v M")])
        self.assertEqual((plan.layout, plan.needs_review, plan.review_note), ("inline", False, "keep"))

    def test_counts_of_notes_and_links_are_in_the_review_note(self):
        plan = nc.plan_group(parent(), [child(1, "<p>x</p>", notes=2, links=3)])
        self.assertIn("2 Note(s) and 3 link(s)", plan.review_note)


def rec(model, pk, **fields):
    return {"model": model, "pk": pk, "fields": fields}


def old_document():
    base = {"profile": 1, "created_by": None, "updated_by": None, "deleted_at": None, "delete_batch": None, "version": 1}
    item = dict(subject=None, topic=5, subtopic=None, flag="none", flag_text="", needs_review=False, review_note="",
                citation="", position=1, **base)
    return {
        "diary.Item": [
            rec("diary.item", 1, kind="nested", text="<p>Parent</p>", parent_item=None, **{**item, "citation": "N v M"}),
            rec("diary.item", 2, kind="plain", text="<p>kid</p>", parent_item=1,
                **{**item, "topic": None, "flag": "doubted"}),
            rec("diary.item", 3, kind="plain", text="<p>plain</p>", parent_item=None, **{**item, "position": 2}),
        ],
        "diary.Case": [rec("diary.case", 1, item=2, citation="A v B", comment="", comment_plain="", position=1, **base)],
        "diary.Note": [rec("diary.note", 1, item=2, text="n", text_plain="n", position=1, subject=None, topic=None,
                           subtopic=None, section=None, **base)],
        "diary.NoteLink": [rec("diary.notelink", 1, note=1, item=2, position=1, subject=None, topic=None,
                               subtopic=None, section=None, **base)],
        "diary.UserSettings": [rec("diary.usersettings", 1, user=1, nested_item_format="bullet")],
        "diary.VersionHistory": [],
    }


class DocumentMappingTests(SimpleTestCase):
    """The same mapping on a parsed backup file (a minimal old-format file)."""

    def test_minimal_old_file(self):
        doc = old_document()
        stats = nc.upgrade_document_nested(doc, "2026-01-01T00:00:00")
        self.assertEqual((stats["nested_items"], stats["children_folded"], stats["cases_created"], stats["cases_moved"],
                          stats["notes_moved"], stats["links_retargeted"]), (1, 1, 1, 1, 1, 1))
        items = {r["pk"]: r["fields"] for r in doc["diary.Item"]}
        self.assertEqual((items[1]["kind"], items[1]["citation"], items[1]["citation_layout"]), ("plain", "", "lines"))
        self.assertTrue(items[1]["needs_review"])
        self.assertTrue(all("parent_item" not in f for f in items.values()))
        self.assertNotIn("citation_layout", items[3])  # an untouched Item is left as it is
        cases = sorted(doc["diary.Case"], key=lambda r: r["fields"]["position"])
        self.assertEqual([(c["fields"]["item"], c["fields"]["citation"]) for c in cases], [(1, "N v M"), (1, "A v B")])
        self.assertEqual(cases[1]["fields"]["comment"], "<p>kid [Doubted]</p>")
        self.assertEqual(cases[1]["fields"]["comment_plain"], "kid [Doubted]")
        self.assertEqual((doc["diary.Note"][0]["fields"]["item"], doc["diary.NoteLink"][0]["fields"]["item"]), (1, 1))
        self.assertEqual(items[2]["topic"], 5)
        self.assertIsNotNone(items[2]["deleted_at"])
        batch = doc["diary.TrashBatch"][0]
        self.assertEqual(items[2]["delete_batch"], batch["pk"])
        self.assertTrue(batch["fields"]["label"].startswith(nc.BATCH_LABEL))
        self.assertNotIn("nested_item_format", doc["diary.UserSettings"][0]["fields"])

    def test_history_rows_are_added_with_new_keys(self):
        doc = old_document()
        nc.upgrade_document_nested(doc, "2026-01-01T00:00:00")
        rows = doc["diary.VersionHistory"]
        self.assertEqual({(r["fields"]["record_type"], r["fields"]["record_id"]) for r in rows},
                         {("case", 1), ("case", 2), ("note", 1), ("notelink", 1), ("item", 1), ("item", 2)})
        self.assertEqual({r["fields"]["change_kind"] for r in rows}, {"migrate"})
        self.assertEqual(len({r["pk"] for r in rows}), len(rows))

    def test_a_file_already_in_the_current_shape_is_not_changed(self):
        doc = old_document()
        nc.upgrade_document_nested(doc, "2026-01-01T00:00:00")
        again = nc.upgrade_document_nested(doc, "2026-01-02T00:00:00")
        self.assertEqual(again["nested_items"], 0)
        self.assertEqual(len(doc["diary.TrashBatch"]), 1)

    def test_a_file_without_trash_batches_gets_none_unless_needed(self):
        doc = old_document()
        doc["diary.Item"] = [r for r in doc["diary.Item"] if r["pk"] == 3]
        nc.upgrade_document_nested(doc, "2026-01-01T00:00:00")
        self.assertNotIn("diary.TrashBatch", doc)

    def test_a_nested_item_without_children_keeps_its_citation_as_a_case(self):
        doc = old_document()
        doc["diary.Item"] = [r for r in doc["diary.Item"] if r["pk"] == 1]
        nc.upgrade_document_nested(doc, "2026-01-01T00:00:00")
        item = doc["diary.Item"][0]["fields"]
        self.assertEqual((item["kind"], item["citation"], item["citation_layout"], item["needs_review"]),
                         ("plain", "", "inline", False))
        self.assertEqual([c["fields"]["citation"] for c in doc["diary.Case"] if c["fields"]["item"] == 1], ["N v M"])

    def test_an_individually_trashed_child_stays_in_trash_and_is_not_folded(self):
        doc = old_document()
        doc["diary.Item"][1]["fields"]["deleted_at"] = "2025-01-01T00:00:00"
        doc["diary.Item"][1]["fields"]["delete_batch"] = "other-batch"
        stats = nc.upgrade_document_nested(doc, "2026-01-01T00:00:00")
        self.assertEqual((stats["children_folded"], stats["children_left_in_trash"]), (0, 1))
        kid = doc["diary.Item"][1]["fields"]
        self.assertEqual((kid["topic"], kid["delete_batch"], "parent_item" in kid), (5, "other-batch", False))
        self.assertEqual([c["fields"]["item"] for c in doc["diary.Case"]], [2, 1])  # its Case stays with it


class ConversionOrderTests(SimpleTestCase):
    def test_deepest_parent_first_and_plain_parents_are_included(self):
        # 1 (nested) > 2 (plain, has kid 4) > 4 ; 1 > 3 ; 9 is a nested Item with no kids
        order = nc.conversion_order({2: 1, 3: 1, 4: 2}, [1, 9])
        self.assertEqual(order, [2, 1, 9])

    def test_a_plain_parent_with_children_is_converted_too(self):
        self.assertEqual(nc.conversion_order({5: 7}, []), [7])

    def test_a_cycle_cannot_loop(self):
        self.assertEqual(sorted(nc.conversion_order({1: 2, 2: 1}, [])), [1, 2])

    def test_nothing_to_do(self):
        self.assertEqual(nc.conversion_order({}, []), [])


def shaped_document():
    """Nested 1 with a live kid, a trashed kid and an inner plain parent 4 (itself a kid) with kid 5; plus a
    plain parent 6 with kid 7 and a trashed Nested Item 8 whose kid 9 is live."""
    base = {"profile": 1, "created_by": None, "updated_by": None, "deleted_at": None, "delete_batch": None, "version": 1}
    item = dict(subject=None, topic=None, subtopic=None, flag="none", flag_text="", needs_review=False,
                review_note="", citation="", position=1, **base)

    def make(pk, kind="plain", parent=None, **kw):
        fields = {**item, **kw}
        if parent is None and "topic" not in kw:
            fields["topic"] = 5
        return rec("diary.item", pk, kind=kind, text=f"<p>t{pk}</p>", parent_item=parent, **fields)

    trashed = {"deleted_at": "2025-01-01T00:00:00", "delete_batch": "b1"}
    return {
        "diary.Item": [
            make(1, "nested", citation="N v M"),
            make(2, parent=1), make(3, parent=1, **trashed),
            make(4, parent=1), make(5, parent=4),
            make(6), make(7, parent=6),
            make(8, "nested", citation="T v U", **trashed), make(9, parent=8),
        ],
        "diary.Case": [], "diary.Note": [], "diary.NoteLink": [], "diary.VersionHistory": [], "diary.UserSettings": [],
    }


class ShapesInDocumentTests(SimpleTestCase):
    def test_every_shape_ends_with_no_item_beneath_another(self):
        doc = shaped_document()
        nc.upgrade_document_nested(doc, "2026-01-01T00:00:00")
        items = {r["pk"]: r["fields"] for r in doc["diary.Item"]}
        self.assertEqual(len(items), 9)
        self.assertTrue(all("parent_item" not in f for f in items.values()))
        self.assertTrue(all(f["kind"] == "plain" for f in items.values()))
        # every Item has exactly one place (the database constraint)
        for pk, f in items.items():
            self.assertEqual(sum(f.get(c) is not None for c in ("subject", "topic", "subtopic")), 1, pk)

    def test_the_trashed_child_stays_in_trash_and_is_not_folded(self):
        doc = shaped_document()
        nc.upgrade_document_nested(doc, "2026-01-01T00:00:00")
        items = {r["pk"]: r["fields"] for r in doc["diary.Item"]}
        self.assertEqual(items[3]["delete_batch"], "b1")

    def test_a_plain_parent_absorbs_its_child(self):
        doc = shaped_document()
        nc.upgrade_document_nested(doc, "2026-01-01T00:00:00")
        items = {r["pk"]: r["fields"] for r in doc["diary.Item"]}
        self.assertEqual(items[6]["citation_layout"], "lines")
        self.assertIsNotNone(items[7]["deleted_at"])
        cases = [c["fields"] for c in doc["diary.Case"] if c["fields"]["item"] == 6]
        self.assertEqual([c["comment"] for c in cases], ["<p>t7</p>"])

    def test_two_levels_are_folded_inner_group_first(self):
        doc = shaped_document()
        nc.upgrade_document_nested(doc, "2026-01-01T00:00:00")
        items = {r["pk"]: r["fields"] for r in doc["diary.Item"]}
        self.assertIsNotNone(items[5]["deleted_at"])
        self.assertIsNotNone(items[4]["deleted_at"])
        self.assertEqual(items[5]["topic"], 5)  # the place of the outermost Item
        by_item = {}
        for c in doc["diary.Case"]:
            by_item.setdefault(c["fields"]["item"], []).append(c["fields"]["comment"])
        self.assertNotIn(4, by_item)  # its Case moved up into Item 1
        self.assertEqual(len(by_item[1]), 3)
        self.assertIn("<p>t2</p>", by_item[1])
        self.assertTrue(any(c.startswith("<p>t4 - t5") for c in by_item[1]))  # the inner group arrived finished

    def test_a_live_child_of_a_trashed_parent_is_folded_and_waits_in_trash(self):
        doc = shaped_document()
        nc.upgrade_document_nested(doc, "2026-01-01T00:00:00")
        items = {r["pk"]: r["fields"] for r in doc["diary.Item"]}
        self.assertIsNotNone(items[9]["deleted_at"])
        self.assertEqual(items[8]["delete_batch"], "b1")
        self.assertEqual([c["fields"]["citation"] for c in doc["diary.Case"] if c["fields"]["item"] == 8][:1], ["T v U"])


class MigrationIndependenceTests(SimpleTestCase):
    def test_the_module_and_the_migration_import_no_models_and_no_services(self):
        import ast
        from pathlib import Path

        from django.conf import settings

        base = Path(settings.BASE_DIR) / "diary"
        for path in (base / "nested_conversion.py", base / "migrations" / "0015_convert_nested_items.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [("." * node.level) + (node.module or "")] + [a.name for a in node.names]
                for name in names:
                    self.assertFalse(name.startswith("diary.services"), f"{path.name} imports {name}")
                    self.assertNotIn(name, ("diary.models", ".models", "..models"), f"{path.name} imports {name}")


class MigrationTests(TransactionTestCase):
    """Data migration 0015 on a database at the schema before it (built with the historical models)."""

    def setUp(self):
        executor = MigrationExecutor(connection)
        executor.migrate(BEFORE)  # an empty database: reversing 0016 and 0015 is allowed
        self.old_apps = executor.loader.project_state(BEFORE).apps
        self.build()

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def build(self):
        apps = self.old_apps
        from accounts.models import Profile  # the real model: the accounts table has columns the old state lacks

        Subject, Topic, Item = (apps.get_model("diary", n) for n in ("Subject", "Topic", "Item"))
        Case, Note, NoteLink = (apps.get_model("diary", n) for n in ("Case", "Note", "NoteLink"))
        self.profile = Profile.objects.create(program="diary", name="Mig")
        kw = {"profile_id": self.profile.pk}
        subject = Subject.objects.create(name="S", **kw)
        self.topic = Topic.objects.create(subject=subject, name="T", **kw)
        self.nested = Item.objects.create(topic=self.topic, kind="nested", text="<p>Group</p>", citation="N v M",
                                          position=1, **kw)
        self.kid1 = Item.objects.create(parent_item=self.nested, text="<p>one</p>", position=1, flag="overruled",
                                        flag_text="by X", **kw)
        self.kid2 = Item.objects.create(parent_item=self.nested, text="<p>two</p>", position=2, needs_review=True,
                                        review_note="rn", **kw)
        self.plain = Item.objects.create(topic=self.topic, text="<p>plain</p>", position=2, **kw)
        self.case = Case.objects.create(item=self.kid1, citation="A v B", comment="<p>why</p>", position=1, **kw)
        self.own_note = Note.objects.create(item=self.nested, text="own", position=1, **kw)
        self.kid_note = Note.objects.create(item=self.kid1, text="kid", position=1, **kw)
        elsewhere = Note.objects.create(topic=self.topic, text="elsewhere", position=1, **kw)
        self.link = NoteLink.objects.create(note=elsewhere, item=self.kid1, position=1, **kw)

    def run_migration(self):
        return nc.migrate_nested(self.old_apps)

    def model(self, name):
        return self.old_apps.get_model("diary", name)

    def test_every_rule(self):
        counts = {n: self.model(n).objects.count() for n in ("Item", "Note", "NoteLink")}
        stats = self.run_migration()
        Item, Case, Note, NoteLink = (self.model(n) for n in ("Item", "Case", "Note", "NoteLink"))
        self.assertEqual({n: self.model(n).objects.count() for n in ("Item", "Note", "NoteLink")}, counts)  # nothing lost

        nested = Item.objects.get(pk=self.nested.pk)
        self.assertEqual((nested.kind, nested.citation, nested.citation_layout, nested.needs_review, nested.version),
                         ("plain", "", "lines", True, 2))
        self.assertIn("Converted from a Nested Item", nested.review_note)
        cases = list(Case.objects.filter(item=nested).order_by("position"))
        self.assertEqual([(c.position, c.citation) for c in cases], [(1, "N v M"), (2, "A v B"), (3, "")])
        self.assertEqual(cases[0].comment, "")
        self.assertEqual(cases[1].pk, self.case.pk)  # the sub-item's Case moved
        self.assertEqual(cases[1].comment, "<p>one - why [Overruled: by X]</p>")
        self.assertEqual(cases[1].comment_plain, "one - why [Overruled: by X]")
        self.assertEqual(cases[2].comment, "<p>two [For review: rn]</p>")
        self.assertEqual(Note.objects.get(pk=self.kid_note.pk).item_id, nested.pk)
        self.assertEqual([n.position for n in Note.objects.filter(item=nested).order_by("position")], [1, 2])
        self.assertEqual(NoteLink.objects.get(pk=self.link.pk).item_id, nested.pk)

        for kid in (self.kid1, self.kid2):
            kid = Item.objects.get(pk=kid.pk)
            self.assertEqual((kid.parent_item_id, kid.topic_id), (None, self.topic.pk))
            self.assertIsNotNone(kid.deleted_at)
            batch = self.model("TrashBatch").objects.get(pk=kid.delete_batch)
            self.assertTrue(batch.label.startswith("Nested Item conversion"))
        plain = Item.objects.get(pk=self.plain.pk)
        self.assertEqual((plain.version, plain.deleted_at), (1, None))
        self.assertFalse(Item.objects.filter(kind="nested").exists())

        self.assertEqual((stats["nested_items"], stats["children_folded"], stats["cases_created"], stats["cases_moved"],
                          stats["notes_moved"], stats["links_retargeted"]), (1, 2, 2, 1, 1, 1))
        history = self.model("VersionHistory").objects.filter(change_kind="migrate")
        self.assertEqual({r.record_type for r in history}, {"item", "case", "note", "notelink"})
        self.assertEqual(history.filter(record_type="item").count(), 3)

    def test_a_failed_count_check_rolls_everything_back(self):
        Item = self.model("Item")
        before_history = self.model("VersionHistory").objects.count()
        with mock.patch.object(nc, "verify_counts", side_effect=nc.MigrationVerificationError("boom")):
            with self.assertRaises(nc.MigrationVerificationError):
                self.run_migration()
        nested = Item.objects.get(pk=self.nested.pk)
        self.assertEqual((nested.kind, nested.citation, nested.version), ("nested", "N v M", 1))
        self.assertEqual(Item.objects.get(pk=self.kid1.pk).parent_item_id, self.nested.pk)
        self.assertEqual(self.model("Case").objects.get(pk=self.case.pk).item_id, self.kid1.pk)
        self.assertEqual(self.model("VersionHistory").objects.count(), before_history)
        self.assertFalse(self.model("TrashBatch").objects.exists())

    def test_running_twice_changes_nothing_more(self):
        self.run_migration()
        history = self.model("VersionHistory").objects.count()
        stats = self.run_migration()
        self.assertEqual(stats["nested_items"], 0)
        self.assertEqual(self.model("VersionHistory").objects.count(), history)

    def test_a_trashed_nested_item_keeps_its_cases_in_trash_with_it(self):
        from django.utils import timezone

        Item, Case = self.model("Item"), self.model("Case")
        batch = uuid.uuid4()
        self.model("TrashBatch").objects.create(
            id=batch, profile_id=self.profile.pk, root_type="item", root_id=self.nested.pk, label="Gone")
        stamp = timezone.now()
        for pk in (self.nested.pk, self.kid1.pk, self.kid2.pk):
            Item.objects.filter(pk=pk).update(deleted_at=stamp, delete_batch=batch)
        Case.objects.update(deleted_at=stamp, delete_batch=batch)
        self.run_migration()
        nested = Item.objects.get(pk=self.nested.pk)
        self.assertEqual(nested.delete_batch, batch)
        cases = Case.objects.filter(item=nested)
        self.assertEqual(cases.count(), 3)
        self.assertEqual({(c.deleted_at, c.delete_batch) for c in cases}, {(stamp, batch)})
        self.assertNotEqual(Item.objects.get(pk=self.kid1.pk).delete_batch, batch)  # the sub-items wait in their own batch

    def test_an_individually_trashed_sub_item_is_not_folded(self):
        from django.utils import timezone

        Item = self.model("Item")
        Item.objects.filter(pk=self.kid2.pk).update(deleted_at=timezone.now())
        stats = self.run_migration()
        self.assertEqual((stats["children_folded"], stats["children_left_in_trash"]), (1, 1))
        kid2 = Item.objects.get(pk=self.kid2.pk)
        self.assertEqual((kid2.parent_item_id, kid2.topic_id, kid2.delete_batch), (None, self.topic.pk, None))
        self.assertEqual(self.model("Case").objects.filter(item_id=self.nested.pk).count(), 2)

    def test_children_of_a_plain_parent_are_converted_too(self):
        Item = self.model("Item")
        Item.objects.filter(pk=self.nested.pk).update(kind="plain", citation="")
        stats = self.run_migration()
        self.assertEqual(Item.objects.filter(parent_item__isnull=False).count(), 0)
        self.assertEqual(stats["children_folded"], 2)
        self.assertEqual(Item.objects.get(pk=self.nested.pk).citation_layout, "lines")
        self.assertEqual(self.model("Case").objects.filter(item_id=self.nested.pk).count(), 2)

    def test_two_levels_leave_nothing_beneath_another_item(self):
        Item, Case = self.model("Item"), self.model("Case")
        kw = {"profile_id": self.profile.pk}
        inner = Item.objects.create(parent_item=self.kid2, text="<p>inner</p>", position=1, **kw)
        counts = Item.objects.count()
        self.run_migration()
        self.assertEqual(Item.objects.count(), counts)
        self.assertFalse(Item.objects.filter(parent_item__isnull=False).exists())
        inner = Item.objects.get(pk=inner.pk)
        self.assertEqual((inner.topic_id, inner.parent_item_id), (self.topic.pk, None))
        self.assertIsNotNone(inner.deleted_at)
        comments = [c.comment for c in Case.objects.filter(item_id=self.nested.pk)]
        self.assertTrue(any(c.startswith("<p>two - inner") for c in comments), comments)  # inner group first

    def test_a_trashed_child_and_a_live_child_of_a_trashed_parent(self):
        from django.utils import timezone

        Item = self.model("Item")
        stamp = timezone.now()
        Item.objects.filter(pk__in=[self.nested.pk]).update(deleted_at=stamp)
        Item.objects.filter(pk=self.kid1.pk).update(deleted_at=stamp)
        self.run_migration()
        self.assertFalse(Item.objects.filter(parent_item__isnull=False).exists())
        self.assertEqual(Item.objects.get(pk=self.kid1.pk).topic_id, self.topic.pk)
        self.assertIsNotNone(Item.objects.get(pk=self.kid2.pk).deleted_at)

    def test_counts_reconcile_after_the_conversion(self):
        Item = self.model("Item")
        total = Item.objects.count()
        live = Item.objects.filter(deleted_at__isnull=True).count()
        self.run_migration()
        self.assertEqual(Item.objects.count(), total)
        self.assertEqual(Item.objects.filter(deleted_at__isnull=True).count(), live - 2)

    def test_the_real_migration_files_apply_and_leave_the_final_schema(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        from diary.models import Case, Item

        nested = Item.objects.get(pk=self.nested.pk)
        self.assertEqual((nested.kind, nested.citation, nested.citation_layout), ("plain", "", "lines"))
        self.assertEqual(list(Case.objects.filter(item=nested).order_by("position").values_list("citation", flat=True)),
                         ["N v M", "A v B", ""])
        self.assertFalse(hasattr(Item, "parent_item"))

    def test_reverse_is_refused_while_any_item_exists(self):
        import importlib

        module = importlib.import_module("diary.migrations.0015_convert_nested_items")
        with self.assertRaises(IrreversibleError):
            module.convert_backwards(self.old_apps, None)
        self.model("Case").objects.all().delete()
        self.model("Note").objects.all().delete()
        self.model("NoteLink").objects.all().delete()
        self.model("Item").objects.all().delete()
        self.assertIsNone(module.convert_backwards(self.old_apps, None))
