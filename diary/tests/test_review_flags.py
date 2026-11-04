"""Round 16 (D88): For review is merged into the Flags.

The rule (diary/review_flags.merge), data migration 0021 on a database at the schema before it, the retired switch, and
History restore of a version saved before the merge."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TransactionTestCase

from diary import review_flags
from diary.models import FLAG_CHOICES, Item, Section, VersionHistory, flag_label
from diary.services import history
from diary.tests.service_helpers import ServiceTestCase

BEFORE = [("diary", "0020_flags_on_sections")]


class MergeRuleTests(SimpleTestCase):
    def test_no_flag_becomes_other_with_the_note(self):
        self.assertEqual(review_flags.merge("none", "", True, "  check\n the  year "), ("other", "check the year"))
        self.assertEqual(review_flags.merge("none", "", True, ""), ("other", "For review"))
        self.assertEqual(review_flags.merge(None, None, True, None), ("other", "For review"))

    def test_an_existing_flag_is_kept_and_the_note_added(self):
        self.assertEqual(review_flags.merge("overruled", "by X", True, "see appeal"),
                         ("overruled", "by X \u00b7 For review: see appeal"))
        self.assertEqual(review_flags.merge("doubted", "", True, ""), ("doubted", "For review"))
        self.assertEqual(review_flags.merge("other", "mine", True, ""), ("other", "mine \u00b7 For review"))

    def test_not_marked_changes_nothing(self):
        self.assertEqual(review_flags.merge("pending", "x", False, "left over"), ("pending", "x"))
        self.assertEqual(review_flags.merge("none", "", False, "left over"), ("none", ""))

    def test_pending_is_after_none_and_labels_read_well(self):
        self.assertEqual([key for key, _ in FLAG_CHOICES], ["none", "pending", "overruled", "doubted", "other"])
        self.assertEqual(flag_label("none", "ignored"), "")
        self.assertEqual(flag_label("pending", ""), "Pending")
        self.assertEqual(flag_label("pending", "ask the client"), "Pending: ask the client")
        self.assertEqual(flag_label("other", "see the appeal"), "see the appeal")
        self.assertEqual(flag_label("other", ""), "Other")
        self.assertEqual(flag_label("overruled", "Overruled by New v. Law"), "Overruled by New v. Law")


class MigrationTests(TransactionTestCase):
    """Data migration 0021 on a database at the schema before it (0022 adds the check rule afterwards)."""

    def setUp(self):
        executor = MigrationExecutor(connection)
        executor.migrate(BEFORE)  # an empty database: reversing 0022 and 0021 is allowed
        self.old_apps = executor.loader.project_state(BEFORE).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def model(self, name):
        return self.old_apps.get_model("diary", name)

    def build(self):
        from accounts.models import Profile  # the real model: the accounts tables have columns the old state lacks

        kw = {"profile_id": Profile.objects.create(program="diary", name="Mig").pk}
        Subject, Topic, Item_, Section_ = (self.model(n) for n in ("Subject", "Topic", "Item", "Section"))
        topic = Topic.objects.create(subject=Subject.objects.create(name="S", **kw), name="T", **kw)
        self.marked = Item_.objects.create(topic=topic, text="<p>a</p>", needs_review=True, review_note="check", position=1, **kw)
        self.both = Item_.objects.create(topic=topic, text="<p>b</p>", needs_review=True, review_note="", flag="doubted",
                                         flag_text="maybe", position=2, **kw)
        self.leftover = Item_.objects.create(topic=topic, text="<p>c</p>", review_note="old note", position=3, **kw)
        self.section = Section_.objects.create(topic=topic, name="Sec", needs_review=True, review_note="name?", position=4, **kw)

    def test_every_rule(self):
        self.build()
        stats = review_flags.migrate_review(self.old_apps)
        self.assertEqual((stats["items"], stats["sections"], stats["kept_flag"], stats["notes_left"]), (2, 1, 1, 1))
        Item_, Section_ = self.model("Item"), self.model("Section")
        shape = lambda o: (o.flag, o.flag_text, o.needs_review, o.review_note, o.version)  # noqa: E731
        self.assertEqual(shape(Item_.objects.get(pk=self.marked.pk)), ("other", "check", False, "", 2))
        self.assertEqual(shape(Item_.objects.get(pk=self.both.pk)), ("doubted", "maybe \u00b7 For review", False, "", 2))
        self.assertEqual(shape(Item_.objects.get(pk=self.leftover.pk)), ("none", "", False, "old note", 1))  # not marked
        self.assertEqual(shape(Section_.objects.get(pk=self.section.pk)), ("other", "name?", False, "", 2))
        rows = self.model("VersionHistory").objects.filter(change_kind="migrate")
        self.assertEqual({(r.record_type, r.record_id) for r in rows},
                         {("item", self.marked.pk), ("item", self.both.pk), ("section", self.section.pk)})
        self.assertEqual(review_flags.migrate_review(self.old_apps)["items"], 0)  # running twice changes nothing

    def test_the_real_migration_files_apply_and_the_switch_stays_off(self):
        from django.db import IntegrityError, transaction

        self.build()
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        self.assertEqual(Item.objects.get(pk=self.marked.pk).flag, "other")
        self.assertEqual(Section.objects.get(pk=self.section.pk).flag_text, "name?")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Section.objects.filter(pk=self.section.pk).update(needs_review=True)


class HistoryRestoreTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.build_topic()

    def test_restoring_a_version_saved_before_the_merge_folds_its_mark_into_the_flag(self):
        VersionHistory.objects.create(
            profile=self.profile, record_type="item", record_id=self.one.pk, version=7, change_kind="edit",
            snapshot={"text": "<p>old text</p>", "citation": "", "kind": "plain", "flag": "none", "flag_text": "",
                      "needs_review": True, "review_note": "look again"},
        )
        history.restore_version(self.profile, self.user, "item", self.one.pk, 7)
        item = self.get(self.one)
        self.assertEqual((item.text, item.flag, item.flag_text, item.needs_review, item.review_note),
                         ("<p>old text</p>", "other", "look again", False, ""))
