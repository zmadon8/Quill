"""Reading versions saved by earlier releases (diary/oldversions.py): For review folded into the Flags, and a version's old citation."""
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase

from diary import oldversions
from diary.models import FLAG_CHOICES, Section, VersionHistory, flag_label
from diary.services import history
from diary.tests.service_helpers import ServiceTestCase


class MergeRuleTests(SimpleTestCase):
    def test_no_flag_becomes_other_with_the_note(self):
        self.assertEqual(oldversions.merge("none", "", True, "  check\n the  year "), ("other", "check the year"))
        self.assertEqual(oldversions.merge("none", "", True, ""), ("other", "For review"))
        self.assertEqual(oldversions.merge(None, None, True, None), ("other", "For review"))

    def test_an_existing_flag_is_kept_and_the_note_added(self):
        self.assertEqual(oldversions.merge("overruled", "by X", True, "see appeal"),
                         ("overruled", "by X \u00b7 For review: see appeal"))
        self.assertEqual(oldversions.merge("doubted", "", True, ""), ("doubted", "For review"))
        self.assertEqual(oldversions.merge("other", "mine", True, ""), ("other", "mine \u00b7 For review"))

    def test_not_marked_changes_nothing(self):
        self.assertEqual(oldversions.merge("pending", "x", False, "left over"), ("pending", "x"))
        self.assertEqual(oldversions.merge("none", "", False, "left over"), ("none", ""))

    def test_pending_is_after_none_and_labels_read_well(self):
        self.assertEqual([key for key, _ in FLAG_CHOICES], ["none", "pending", "overruled", "doubted", "other"])
        self.assertEqual(flag_label("none", "ignored"), "")
        self.assertEqual(flag_label("pending", ""), "Pending")
        self.assertEqual(flag_label("pending", "ask the client"), "Pending: ask the client")
        self.assertEqual(flag_label("other", "see the appeal"), "see the appeal")
        self.assertEqual(flag_label("other", ""), "Other")
        self.assertEqual(flag_label("overruled", "Overruled by New v. Law"), "Overruled by New v. Law")

    def test_an_old_citation_is_found_and_an_empty_one_means_nothing_to_map(self):
        self.assertEqual(oldversions.old_snapshot_citation({"citation": "A v B"}), "A v B")
        self.assertIsNone(oldversions.old_snapshot_citation({"citation": ""}))
        self.assertIsNone(oldversions.old_snapshot_citation({}))


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

    def test_the_retired_switch_cannot_be_turned_on(self):
        section = self.make("section", ("topic", self.topic.pk), name="Sec")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Section.objects.filter(pk=section.pk).update(needs_review=True)
