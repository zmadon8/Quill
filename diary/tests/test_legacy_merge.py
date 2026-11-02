"""10d: Multi-Item merged into Item. The mapping (diary/services/legacy.py), data migration 0010 logic and
History restore of a version that predates the merge (docs/DESIGN.md, Proposal for 10d)."""
from unittest import mock

from django.apps import apps as django_apps
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from diary.models import Case, Item, Subject, Subtopic, Topic, VersionHistory
from diary.services import history, legacy
from diary.tests.helpers import main_profile
from diary.tests.service_helpers import ServiceTestCase


class ConvertItemTests(SimpleTestCase):
    def test_plain_with_citation_moves_to_a_first_case(self):
        c = legacy.convert_item("plain", "A v B")
        self.assertEqual((c.new_kind, c.new_citation, c.case_citation, c.case_position), ("plain", "", "A v B", 1))

    def test_plain_without_citation_is_untouched(self):
        self.assertIsNone(legacy.convert_item("plain", ""))

    def test_multi_becomes_plain_and_keeps_its_cases(self):
        c = legacy.convert_item("multi", "", [1, 2])
        self.assertEqual((c.new_kind, c.case_citation, c.kind_changed), ("plain", None, True))

    def test_multi_with_a_stray_citation_is_not_lost(self):
        c = legacy.convert_item("multi", "Stray", [3])
        self.assertEqual((c.new_kind, c.case_citation, c.case_position), ("plain", "Stray", 2))

    def test_nested_keeps_its_own_citation(self):
        self.assertIsNone(legacy.convert_item("nested", "N v M"))

    def test_whitespace_only_citation_is_kept_verbatim_and_flagged(self):
        c = legacy.convert_item("plain", "  ")
        self.assertEqual((c.case_citation, c.whitespace_only), ("  ", True))

    def test_no_free_place_in_front_of_position_zero_is_refused(self):
        with self.assertRaises(legacy.LegacyConflict):
            legacy.convert_item("plain", "A v B", [0, 1])

    def test_old_snapshot_citation_mapping(self):
        self.assertEqual(legacy.legacy_snapshot_citation({"citation": "A v B"}, "plain"), "A v B")
        self.assertIsNone(legacy.legacy_snapshot_citation({"citation": ""}, "plain"))
        self.assertIsNone(legacy.legacy_snapshot_citation({}, "plain"))
        self.assertIsNone(legacy.legacy_snapshot_citation({"citation": "N v M"}, "nested"))
        self.assertIsNone(legacy.legacy_snapshot_citation({"citation": "N v M", "kind": "nested"}, "plain"))

    def test_verify_counts_detects_each_mismatch(self):
        before = {"items": 3, "cases": 1, "multi": 1, "to_move": 1, "nested_with_citation": 1}
        good_after = {"items": 3, "cases": 2, "multi": 0, "to_move": 0, "nested_with_citation": 1}
        stats = {"cases_created": 1, "multi_to_plain": 1}
        legacy.verify_counts(before, good_after, stats)
        for key, value in (("items", 2), ("cases", 1), ("multi", 1), ("to_move", 1), ("nested_with_citation", 0)):
            with self.assertRaises(legacy.MigrationVerificationError, msg=key):
                legacy.verify_counts(before, {**good_after, key: value}, stats)
        with self.assertRaises(legacy.MigrationVerificationError):
            legacy.verify_counts(before, good_after, {**stats, "cases_created": 0})


class MigrateItemsTests(TestCase):
    def setUp(self):
        self.profile = main_profile()
        subject = Subject.objects.create(profile=self.profile, name="Contract")
        topic = Topic.objects.create(profile=self.profile, subject=subject, name="Formation")
        self.sub = Subtopic.objects.create(profile=self.profile, topic=topic, name="Offer")

    def item(self, **fields):
        fields.setdefault("text", "t")
        return Item.objects.create(profile=self.profile, subtopic=self.sub, **fields)

    def raw_kind(self, item, kind):
        Item.objects.filter(pk=item.pk).update(kind=kind)  # the old "multi" value is not a choice any more

    def build(self):
        self.plain = self.item(citation="A v B", position=1, version=4)
        self.empty = self.item(position=2)
        self.multi = self.item(position=3)
        self.raw_kind(self.multi, "multi")
        self.case1 = Case.objects.create(profile=self.profile, item=self.multi, citation="C1", comment="<i>x</i>", position=1)
        self.case2 = Case.objects.create(profile=self.profile, item=self.multi, citation="C2", position=2)
        self.nested = self.item(kind="nested", citation="N v M", position=4)
        self.child = Item.objects.create(profile=self.profile, parent_item=self.nested, text="kid")
        self.trashed = self.item(citation="T v U", position=5, deleted_at=timezone.now())
        self.space = self.item(citation="   ", position=6)

    def test_every_rule(self):
        self.build()
        updated = {i.pk: i.updated_at for i in Item.objects.all()}
        stats = legacy.migrate_items(django_apps)

        self.assertFalse(Item.objects.exclude(kind="nested").exclude(citation="").exists())
        self.assertFalse(Item.objects.filter(kind="multi").exists())

        first = self.plain.cases.get()
        self.assertEqual((first.citation, first.comment, first.comment_plain, first.position, first.version), ("A v B", "", "", 1, 1))
        self.assertEqual(first.profile, self.profile)
        self.plain.refresh_from_db()
        self.assertEqual((self.plain.kind, self.plain.citation, self.plain.version), ("plain", "", 5))
        self.assertEqual(self.plain.updated_at, updated[self.plain.pk])

        self.assertFalse(self.empty.cases.exists())
        self.empty.refresh_from_db()
        self.assertEqual(self.empty.version, 1)

        self.multi.refresh_from_db()
        self.assertEqual((self.multi.kind, self.multi.version), ("plain", 2))
        self.assertEqual(list(self.multi.cases.order_by("position").values_list("citation", "position")), [("C1", 1), ("C2", 2)])

        self.nested.refresh_from_db()
        self.assertEqual((self.nested.kind, self.nested.citation, self.nested.version), ("nested", "N v M", 1))
        self.assertFalse(self.nested.cases.exists())

        gone = self.trashed.cases.get()
        self.assertEqual((gone.citation, gone.deleted_at), ("T v U", self.trashed.deleted_at))

        spaces = self.space.cases.get()
        self.assertEqual(spaces.citation, "   ")

        self.assertEqual(stats["cases_created"], 3)
        self.assertEqual(stats["multi_to_plain"], 1)
        self.assertEqual(stats["items_changed"], 4)
        self.assertEqual(stats["whitespace_only"], 1)
        self.assertEqual(stats["nested_with_citation_kept"], 1)

    def test_history_rows_are_written(self):
        self.build()
        legacy.migrate_items(django_apps)
        rows = VersionHistory.objects.filter(change_kind="migrate")
        self.assertEqual(rows.filter(record_type="case").count(), 3)
        self.assertEqual(rows.filter(record_type="item").count(), 4)
        row = rows.get(record_type="item", record_id=self.plain.pk)
        self.assertEqual((row.version, row.snapshot["citation"], row.snapshot["kind"]), (5, "", "plain"))
        self.assertIsNone(row.changed_by)
        self.assertEqual(rows.get(record_type="case", record_id=self.plain.cases.get().pk).version, 1)
        self.assertEqual(row.get_change_kind_display(), "Migrate")

    def test_case_goes_before_existing_cases(self):
        item = self.item(citation="First", position=1)
        Case.objects.create(profile=self.profile, item=item, citation="Later", position=2)
        legacy.migrate_items(django_apps)
        self.assertEqual(list(item.cases.order_by("position").values_list("citation", flat=True)), ["First", "Later"])

    def test_running_twice_changes_nothing_more(self):
        self.build()
        legacy.migrate_items(django_apps)
        history_count = VersionHistory.objects.count()
        stats = legacy.migrate_items(django_apps)
        self.assertEqual((stats["items_changed"], stats["cases_created"]), (0, 0))
        self.assertEqual(VersionHistory.objects.count(), history_count)

    def test_failed_count_check_raises_and_rolls_back(self):
        self.build()
        real = legacy._count_state
        calls = []

        def lying(Item_, Case_):
            calls.append(1)
            state = real(Item_, Case_)
            if len(calls) > 1:
                state["cases"] += 1
            return state

        history_before = VersionHistory.objects.count()
        with mock.patch.object(legacy, "_count_state", side_effect=lying):
            with self.assertRaises(legacy.MigrationVerificationError):
                legacy.migrate_items(django_apps)
        self.assertEqual(Case.objects.count(), 2)
        self.assertEqual(VersionHistory.objects.count(), history_before)
        self.plain.refresh_from_db()
        self.assertEqual(self.plain.citation, "A v B")
        self.multi.refresh_from_db()
        self.assertEqual(self.multi.kind, "multi")

    def test_conflict_stops_everything(self):
        other = self.item(citation="Fine", position=1)
        item = self.item(citation="Clash", position=2)
        Case.objects.create(profile=self.profile, item=item, citation="Zero", position=0)
        with self.assertRaises(legacy.LegacyConflict):
            legacy.migrate_items(django_apps)
        other.refresh_from_db()
        self.assertEqual(other.citation, "Fine")
        self.assertFalse(other.cases.exists())

    def test_migration_module_wires_the_helper_and_refuses_reverse(self):
        import importlib

        from django.db.migrations.exceptions import IrreversibleError

        module = importlib.import_module("diary.migrations.0010_merge_multi_into_item")
        with self.assertRaises(IrreversibleError):
            module.merge_backwards(django_apps, None)
        self.build()
        module.merge_forwards(django_apps, None)
        self.assertFalse(Item.objects.exclude(kind="nested").exclude(citation="").exists())


class RestoreOldVersionTests(ServiceTestCase):
    """A version written before the merge carries the old citation; restoring it maps it into Case (a)."""

    def setUp(self):
        super().setUp()
        self.build_topic()

    def old_version(self, item, citation, kind="plain", version=1):
        VersionHistory.objects.create(
            profile=self.profile, record_type="item", record_id=item.pk, version=version, change_kind="edit",
            snapshot={"text": "old text", "citation": citation, "kind": kind, "flag": "none", "flag_text": "",
                      "needs_review": False, "review_note": ""},
        )

    def test_old_citation_is_made_case_a(self):
        self.old_version(self.one, "Old v New", version=7)
        history.restore_version(self.profile, self.user, "item", self.one.pk, 7)
        one = self.get(self.one)
        self.assertEqual((one.text_plain, one.citation), ("old text", ""))
        self.assertEqual(list(one.cases.values_list("citation", "position")), [("Old v New", 1)])

    def test_old_citation_replaces_the_first_live_case(self):
        case = self.make("case", ("item", self.one.pk), citation="Now", comment="keep me")
        second = self.make("case", ("item", self.one.pk), citation="Second")
        self.old_version(self.one, "Old v New", version=7)
        history.restore_version(self.profile, self.user, "item", self.one.pk, 7)
        case, second = self.get(case), self.get(second)
        self.assertEqual((case.citation, case.comment, second.citation), ("Old v New", "keep me", "Second"))

    def test_old_multi_snapshot_is_accepted_for_a_plain_item(self):
        self.old_version(self.one, "", kind="multi", version=7)
        history.restore_version(self.profile, self.user, "item", self.one.pk, 7)
        self.assertEqual(self.get(self.one).kind, "plain")

    def test_empty_snapshot_citation_never_clears_case_a(self):
        case = self.make("case", ("item", self.one.pk), citation="Keep")
        self.old_version(self.one, "", version=7)
        history.restore_version(self.profile, self.user, "item", self.one.pk, 7)
        self.assertEqual(self.get(case).citation, "Keep")
