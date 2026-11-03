"""Database and screen tests of the Word import (Milestone 2)."""
from io import StringIO
from pathlib import Path
from unittest import mock, skipUnless

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from django.urls import reverse

from accounts.models import Profile, User
from backups import services as backup_services
from backups.models import BackupFile
from diary.importer import loader, service
from diary.importer.docx_reader import file_digest
from diary.importer.plan import EXPECTED, REASONS
from diary.models import Case, Item, Section, Subject, Subtopic, Topic, VersionHistory
from diary.tests.docx_builder import SMALL, make_docx
from diary.tests.helpers import join_main, main_profile

PASSWORD = "x-long-pass-123"
REAL_FILE = Path(__file__).resolve().parents[2] / "Case Law Diary.docx"


def other_profile(name="Junior"):
    return Profile.objects.create(program="diary", name=name)


class ImportIntoProfileTests(TestCase):
    def setUp(self):
        self.data = make_docx(SMALL)
        self.profile = main_profile()

    def do_import(self, profile=None):
        return service.run_import(self.data, "small.docx", profile or self.profile)

    def test_creates_every_level_with_original_lines_and_positions(self):
        self.do_import()
        p = self.profile
        self.assertEqual(Subject.objects.filter(profile=p).count(), 4)
        self.assertEqual(Topic.objects.filter(profile=p).count(), 3)
        self.assertEqual(Subtopic.objects.filter(profile=p).count(), 3)
        self.assertEqual(Section.objects.filter(profile=p).count(), 2)
        self.assertEqual(Item.objects.filter(profile=p).count(), 11)
        scope = Topic.objects.get(profile=p, name="Scope")
        self.assertEqual(scope.original_line, "Scope:")
        self.assertTrue(scope.import_ref.startswith("para-"))

    def test_main_and_other_subjects_are_placed_as_designed(self):
        self.do_import()
        arbitration = Subject.objects.get(name="Arbitration")
        self.assertTrue(arbitration.show_on_landing)
        self.assertEqual(arbitration.landing_position, 1)
        stamp = Subject.objects.get(name="Stamp Act")
        self.assertFalse(stamp.show_on_landing)
        self.assertEqual(stamp.other_acts_position, 1)
        self.assertEqual(Subtopic.objects.get(name="Duty").subject, stamp)
        self.assertEqual(Item.objects.get(original_line__startswith="Tender item").subject.name, "Tender")

    def test_clean_item_is_split_and_flagged_item_is_whole(self):
        self.do_import()
        clean = Item.objects.get(original_line__startswith="Clean proposition")
        self.assertEqual(clean.citation, "")  # the citation is the Item's first Case
        self.assertEqual([(c.citation, c.position, c.comment) for c in clean.cases.all()],
                         [("Alpha v Beta [(2010) 1 SCC 1]", 1, "")])
        self.assertEqual(clean.text_plain, "Clean proposition")
        self.assertFalse(clean.needs_review)
        whole = Item.objects.get(original_line="Only a case name")
        self.assertEqual((whole.citation, whole.text_plain), ("", "Only a case name"))
        self.assertFalse(whole.cases.exists())  # a line imported whole has no citation, so no Case
        self.assertTrue(whole.needs_review)
        self.assertTrue(whole.review_note)

    def test_sections_are_flagged_and_share_positions_with_items(self):
        self.do_import()
        a = Section.objects.get(name="Ex Parte")
        b = Section.objects.get(name="Determining")
        self.assertTrue(a.needs_review and b.needs_review)
        self.assertIn("confirm these are Sections", a.review_note)
        self.assertLess(a.position, b.position)

    def test_history_marks_everything_as_imported(self):
        self.do_import()
        total = sum(m.objects.filter(profile=self.profile).count() for m in (Subject, Topic, Subtopic, Section, Item, Case))
        history = VersionHistory.objects.filter(profile=self.profile, change_kind="import")
        self.assertEqual(history.count(), total)
        self.assertTrue(history.filter(record_type="item").exists())
        self.assertTrue(history.filter(record_type="case").exists())

    def test_backups_are_made_before_and_after(self):
        before = BackupFile.objects.count()
        _, notes = self.do_import()
        self.assertEqual(BackupFile.objects.count(), before + 2)
        self.assertEqual(BackupFile.objects.filter(kind="pre_import").count(), 1)
        self.assertEqual(BackupFile.objects.filter(kind="post_import").count(), 1)
        self.assertTrue(any(n.startswith("Backup before") and "Download it" in n for n in notes))
        self.assertTrue(any(n.startswith("Backup after") for n in notes))

    def test_failed_backup_before_the_import_aborts_with_nothing_written(self):
        with mock.patch("diary.importer.service.backup_services.create_backup", side_effect=RuntimeError("disk full")):
            with self.assertRaises(service.ImportRefused) as caught:
                self.do_import()
        self.assertIn("nothing was changed", str(caught.exception))
        self.assertEqual(Subject.objects.count(), 0)
        self.assertEqual(Item.objects.count(), 0)
        self.assertEqual(VersionHistory.objects.filter(change_kind="import").count(), 0)

    def test_failed_backup_after_the_import_is_a_visible_warning_and_the_data_stays(self):
        real = backup_services.create_backup

        def fail_after(kind, *args, **kwargs):
            if kind == "post_import":
                raise RuntimeError("disk full")
            return real(kind, *args, **kwargs)

        with mock.patch("diary.importer.service.backup_services.create_backup", side_effect=fail_after):
            text, notes = self.do_import()
        self.assertTrue(any(n.startswith("WARNING") and "backup after it failed" in n for n in notes))
        self.assertEqual(Subject.objects.filter(profile=self.profile).count(), 4)
        self.assertIn("RESULT: MATCH", text)
        self.assertEqual(BackupFile.objects.filter(kind="pre_import").count(), 1)
        self.assertEqual(BackupFile.objects.filter(kind="post_import").count(), 0)

    def test_running_twice_changes_nothing(self):
        self.do_import()
        counts = Item.objects.count(), Subject.objects.count(), BackupFile.objects.count()
        text, notes = self.do_import()
        self.assertEqual((Item.objects.count(), Subject.objects.count(), BackupFile.objects.count()), counts)
        self.assertIn("already imported", " ".join(notes))
        self.assertIn("RESULT: MATCH", text)

    def test_reconciliation_matches_and_lists_the_colon_changes(self):
        text, _ = self.do_import()
        self.assertIn("RESULT: MATCH", text)
        self.assertIn("UNEXPECTED differences: 0", text)
        self.assertIn("'Scope:' -> 'Scope'", text)
        self.assertIn("Expected 2; found 2.", text)

    def test_stored_positions_are_the_word_order_while_the_display_order_is_alphabetical(self):
        from diary.services.sequences import members

        text, _ = self.do_import()
        arbitration = Subject.objects.get(profile=self.profile, name="Arbitration")
        topics = list(Topic.objects.filter(subject=arbitration).order_by("position"))
        self.assertEqual([(t.name, t.position) for t in topics], [("Scope", 1), ("Direct items", 2)])  # Word order
        shown = members(self.profile.pk, ("topic", "subject", arbitration.pk))
        self.assertEqual([t.name for t in shown], ["Direct items", "Scope"])  # alphabetical
        self.assertIn("Stored Word order of records (their saved positions) matches the file: yes", text)
        self.assertIn("RESULT: MATCH", text)
        self.assertIn("UNEXPECTED differences: 0", text)
        self.assertEqual(Topic.objects.get(pk=topics[0].pk).version, 1)
        _, again = service.reconcile(self.data, "small.docx", self.profile)
        self.assertIn("UNEXPECTED differences: 0", again)

    def test_reconciliation_reports_a_changed_record_never_hides_it(self):
        self.do_import()
        case = Case.objects.get(item__original_line__startswith="Clean proposition")
        case.citation = "Changed"
        case.save()
        _, text = service.reconcile(self.data, "small.docx", self.profile)
        self.assertIn("RESULT:", text)
        self.assertNotIn("RESULT: MATCH", text)
        self.assertIn("UNEXPECTED differences: 1", text)

    def test_a_trashed_record_is_not_present_and_is_reported_apart(self):
        self.do_import()
        Item.objects.filter(original_line="Only a case name").update(deleted_at=timezone.now())
        _, text = service.reconcile(self.data, "small.docx", self.profile)
        self.assertNotIn("RESULT: MATCH", text)
        self.assertIn("Records in the Trash", text)
        self.assertIn("Lines missing from the database: 1", text)

    def test_reconciliation_reports_a_missing_record(self):
        self.do_import()
        Item.objects.get(original_line="Only a case name").delete()
        _, text = service.reconcile(self.data, "small.docx", self.profile)
        self.assertIn("Lines missing from the database: 1", text)
        self.assertNotIn("RESULT: MATCH", text)

    def test_import_goes_only_into_the_chosen_profile(self):
        junior = other_profile()
        self.do_import(junior)
        self.assertEqual(Item.objects.filter(profile=self.profile).count(), 0)
        self.assertGreater(Item.objects.filter(profile=junior).count(), 0)
        self.assertEqual(Subject.objects.exclude(profile=junior).count(), 0)

    def test_the_same_file_can_go_into_two_profiles(self):
        self.do_import()
        self.do_import(other_profile())
        self.assertEqual(Subject.objects.filter(name="Arbitration").count(), 2)

    def test_existing_subject_names_block_the_import_and_nothing_changes(self):
        Subject.objects.create(profile=self.profile, name="arbitration")
        backups = BackupFile.objects.count()
        with self.assertRaises(service.ImportRefused):
            self.do_import()
        self.assertEqual(Subject.objects.filter(profile=self.profile).count(), 1)
        self.assertEqual(BackupFile.objects.count(), backups)

    def test_other_live_data_with_a_different_name_is_refused_and_says_how_to_remove_it(self):
        Subject.objects.create(profile=self.profile, name="TEST SAMPLE: Something else", landing_position=1)
        backups = BackupFile.objects.count()
        with self.assertRaises(service.ImportRefused) as caught:
            self.do_import()
        message = str(caught.exception)
        self.assertIn("remove_sample_data --profile", message)
        self.assertIn("TEST SAMPLE: Something else", message)
        self.assertEqual(Subject.objects.filter(profile=self.profile).count(), 1)
        self.assertEqual(Item.objects.count(), 0)
        self.assertEqual(BackupFile.objects.count(), backups)  # refused before any backup
        _, text = service.dry_run(self.data, "small.docx", self.profile)
        self.assertIn("NOT READY", text)
        self.assertNotIn("Ready to import.", text)

    def test_a_trashed_subject_does_not_block_the_import(self):
        Subject.objects.create(profile=self.profile, name="Old", deleted_at=timezone.now())
        self.do_import()
        self.assertEqual(Subject.objects.filter(profile=self.profile, deleted_at__isnull=True).count(), 4)

    def test_other_live_data_in_another_profile_does_not_matter(self):
        Subject.objects.create(profile=other_profile(), name="Elsewhere", landing_position=1)
        self.do_import()
        self.assertEqual(Subject.objects.filter(profile=self.profile).count(), 4)

    def test_the_same_paragraph_cannot_be_stored_twice_in_one_profile(self):
        Subject.objects.create(profile=self.profile, name="One", import_ref="para-0001")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Subject.objects.create(profile=self.profile, name="Two", import_ref="para-0001")
        Subject.objects.create(profile=other_profile(), name="Three", import_ref="para-0001")
        Subject.objects.create(profile=self.profile, name="Four")
        Subject.objects.create(profile=self.profile, name="Five")  # blank import_ref is not restricted

    def test_a_blank_name_is_a_plan_problem_not_a_database_error(self):
        data = make_docx([("subject", "Contracts"), ("topic", ":"), ("item", "x - Case [(2010) 1 SCC 1]")])
        with self.assertRaises(service.ImportRefused) as caught:
            service.run_import(data, "bad.docx", self.profile)
        self.assertIn("name is empty", str(caught.exception))
        self.assertEqual(Subject.objects.count(), 0)

    def test_partial_earlier_import_is_refused(self):
        self.do_import()
        Item.objects.get(original_line="Only a case name").delete()
        with self.assertRaises(service.ImportRefused):
            self.do_import()

    def test_a_file_with_problems_is_refused(self):
        data = make_docx([("subject", "Miscellaneous"), ("subtopic", "Orphan")])
        with self.assertRaises(service.ImportRefused):
            service.run_import(data, "bad.docx", self.profile)
        self.assertEqual(Subject.objects.count(), 0)

    def test_a_different_file_than_the_dry_run_is_refused(self):
        with self.assertRaises(service.ImportRefused):
            service.run_import(self.data, "small.docx", self.profile, expected_sha256="0" * 64)
        self.assertEqual(Subject.objects.count(), 0)

    def test_failure_part_way_leaves_nothing(self):
        plan = service._prepare(self.data)
        plan.of("subtopic")[-1].name = ""  # the database refuses a blank Sub-topic name, late in the run
        with self.assertRaises(service.ImportRefused) as caught:
            loader.import_plan(plan, self.profile)
        self.assertIn("rolled back", str(caught.exception))
        self.assertEqual(Subject.objects.count(), 0)
        self.assertEqual(Item.objects.count(), 0)


FORMATTED = [
    ("subject", "Contracts"),
    ("topic", "Scope"),
    ("item", [("Bold ", True, False), ("start - ", False, False), ("Case [(2010) 1 SCC 1]", False, True)]),
    ("item", [("Plain ", False, False), ("bold", True, False), (" - Other [(2011) 2 SCC 2]", False, True)]),
]


class FormattingRoundTripTests(TestCase):
    def setUp(self):
        self.data = make_docx(FORMATTED)
        self.profile = main_profile()
        service.run_import(self.data, "f.docx", self.profile)

    def test_formatting_is_stored_and_matches(self):
        first = Item.objects.get(original_line__startswith="Bold ")
        self.assertEqual(first.text, "<p><b>Bold </b>start</p>")
        _, text = service.reconcile(self.data, "f.docx", self.profile)
        self.assertIn("RESULT: MATCH", text)
        self.assertIn("Formatting (bold/italic/underline runs) differs between the file and the database: 0", text)

    def test_lost_bold_is_detected_even_though_the_words_are_the_same(self):
        item = Item.objects.get(original_line__startswith="Bold ")
        item.text = "<p>Bold start</p>"
        item.save()
        _, text = service.reconcile(self.data, "f.docx", self.profile)
        self.assertNotIn("RESULT: MATCH", text)
        self.assertIn("UNEXPECTED differences: 0", text)  # the words are the same ...
        self.assertIn("differs between the file and the database: 1", text)  # ... the formatting is not

    def test_shifted_bold_is_detected(self):
        item = Item.objects.get(original_line__startswith="Plain ")
        item.text = "<p><b>Plain</b> bold</p>"
        item.save()
        _, text = service.reconcile(self.data, "f.docx", self.profile)
        self.assertNotIn("RESULT: MATCH", text)
        self.assertIn("differs between the file and the database: 1", text)


@skipUnless(REAL_FILE.exists(), "Case Law Diary.docx is not in the project folder")
class RealFileThroughTheDatabaseTests(TestCase):
    """The real 950-Item file, imported into a fresh profile and read back (Postgres constraints, order, MATCH)."""

    @classmethod
    def setUpTestData(cls):
        cls.data = REAL_FILE.read_bytes()
        cls.profile = other_profile("Real file")
        cls.text, cls.notes = service.run_import(cls.data, REAL_FILE.name, cls.profile)

    def test_every_figure_and_a_clean_match(self):
        p = self.profile
        self.assertEqual(Subject.objects.filter(profile=p).count(), EXPECTED["subjects"])
        self.assertEqual(Subject.objects.filter(profile=p, show_on_landing=True).count(), EXPECTED["main_subjects"])
        self.assertEqual(Topic.objects.filter(profile=p).count(), EXPECTED["topics"])
        self.assertEqual(Subtopic.objects.filter(profile=p).count(), EXPECTED["subtopics"])
        self.assertEqual(Section.objects.filter(profile=p).count(), EXPECTED["sections"])
        self.assertEqual(Item.objects.filter(profile=p).count(), EXPECTED["items"])
        self.assertEqual(Item.objects.filter(profile=p, needs_review=False).count(), EXPECTED["items_clean"])
        self.assertEqual(Item.objects.filter(profile=p, needs_review=True).count(), EXPECTED["items_flagged"])
        marked = (Item.objects.filter(profile=p, needs_review=True).count()
                  + Section.objects.filter(profile=p, needs_review=True).count())
        self.assertEqual(marked, EXPECTED["review_marked"])
        # One Case per split line (691 clean + 2 flagged lines that were still split); none for whole lines.
        self.assertEqual(Case.objects.filter(profile=p).count(), 693)
        self.assertEqual(Item.objects.filter(profile=p).exclude(citation="").count(), 0)
        self.assertEqual(Item.objects.filter(profile=p, cases__isnull=True).count(), EXPECTED["items"] - 693)
        self.assertIn("Citations (Cases, one per split line)", self.text)
        self.assertIn("RESULT: MATCH. Nothing lost, nothing invented.", self.text)
        self.assertIn("UNEXPECTED differences: 0", self.text)
        self.assertIn("Expected 19; found 19.", self.text)
        self.assertIn("Completeness: 1494 planned records + 1 skipped heading(s) + 11 blank + 0 problem(s) = 1506", self.text)
        _, again = service.reconcile(self.data, REAL_FILE.name, p)
        self.assertIn("RESULT: MATCH", again)

    def test_housing_the_loose_items_in_topic_1_keeps_the_reconciliation_a_match(self):
        """D61: the file puts 17 Items directly under 9 Subjects; housed in Topic "1" they still reconcile."""
        from django.apps import apps

        from diary import topic_one

        stats = topic_one.migrate_loose(apps)
        self.assertEqual((stats["subjects_housed"], stats["topics_made"], stats["items_moved"],
                          stats["left_under_subjects_with_subtopics"]), (9, 9, 17, 0))
        self.assertEqual(Topic.objects.filter(profile=self.profile, import_ref="", name="1").count(), 9)
        self.assertEqual(Item.objects.filter(profile=self.profile, subject__isnull=False).count(), 0)
        _, again = service.reconcile(self.data, REAL_FILE.name, self.profile)
        self.assertIn("RESULT: MATCH", again)
        self.assertIn("UNEXPECTED differences: 0", again)

    def test_per_reason_counts_in_the_database(self):
        expected = {"no_dash": 70, "many_dash": 70, "unbalanced": 49, "multi_marker": 32, "not_citation": 26,
                    "double_space": 6, "bracketed": 2, "flag": 1, "spaces": 1}
        for key, count in expected.items():
            note = f"Imported whole as Text with no Citation: {REASONS[key]}."
            with self.subTest(reason=key):
                self.assertEqual(Item.objects.filter(profile=self.profile, review_note=note).count(), count)
        restarts = Item.objects.filter(profile=self.profile, review_note__contains="Word list restarted here")
        self.assertEqual(sorted(restarts.values_list("import_ref", flat=True)), ["para-1033", "para-1356"])
        self.assertEqual(restarts.filter(cases__isnull=True).count(), 0)  # split normally, only flagged

    def test_sections_hold_two_and_ten_items(self):
        a = Section.objects.get(profile=self.profile, name__startswith="Ex Parte")
        b = Section.objects.get(profile=self.profile, name__startswith="Determining")
        after_a = Item.objects.filter(profile=self.profile, subtopic=a.subtopic, position__gt=a.position,
                                      position__lt=b.position).count()
        after_b = Item.objects.filter(profile=self.profile, subtopic=b.subtopic, position__gt=b.position).count()
        self.assertEqual((after_a, after_b), (2, 10))

    def test_both_backups_exist_and_import_is_a_no_op_second_time(self):
        self.assertEqual(BackupFile.objects.filter(kind="pre_import").count(), 1)
        self.assertEqual(BackupFile.objects.filter(kind="post_import").count(), 1)
        before = Item.objects.count()
        text, notes = service.run_import(self.data, REAL_FILE.name, self.profile)
        self.assertEqual(Item.objects.count(), before)
        self.assertIn("RESULT: MATCH", text)


@override_settings(SECURE_SSL_REDIRECT=False)
class ImportScreenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = join_main(User.objects.create_user("adam", password=PASSWORD, is_superuser=True), "editor")
        cls.editor = join_main(User.objects.create_user("ed", password=PASSWORD), "editor")
        cls.data = make_docx(SMALL)

    def upload(self):
        return SimpleUploadedFile("small.docx", self.data)

    def post(self, **fields):
        fields.setdefault("profile", main_profile().pk)
        fields["file"] = self.upload()
        return self.client.post(reverse("import_word"), fields)

    def test_admin_only(self):
        self.assertEqual(self.client.get(reverse("import_word")).status_code, 302)
        self.client.force_login(self.editor)
        self.assertEqual(self.client.get(reverse("import_word")).status_code, 403)
        self.assertEqual(self.post(action="dry_run").status_code, 403)
        self.assertEqual(Subject.objects.count(), 0)

    def test_dry_run_shows_the_report_and_saves_nothing(self):
        self.client.force_login(self.admin)
        resp = self.post(action="dry_run")
        self.assertContains(resp, "DRY RUN")
        self.assertContains(resp, file_digest(self.data)[:12])
        self.assertContains(resp, "python manage.py import_docx --profile &#x27;Main&#x27; --import")
        self.assertNotContains(resp, "Import into Main")
        self.assertEqual(Subject.objects.count(), 0)

    def test_dry_run_download_is_a_text_file(self):
        self.client.force_login(self.admin)
        resp = self.post(action="dry_run_download")
        self.assertEqual(resp["Content-Type"], "text/plain; charset=utf-8")
        self.assertIn("attachment", resp["Content-Disposition"])
        self.assertIn(b"DRY RUN", resp.content)

    def test_the_import_is_not_run_from_the_screen_the_shell_command_is_shown(self):
        self.client.force_login(self.admin)
        resp = self.post(action="import", sha256=file_digest(self.data), confirm_word="IMPORT")
        self.assertContains(resp, "not run from this screen")
        self.assertContains(resp, "python manage.py import_docx --profile")
        self.assertEqual(Subject.objects.count(), 0)
        ready = self.post(action="dry_run")
        self.assertContains(ready, "python manage.py import_docx --profile &#x27;Main&#x27; --import")

    def test_dry_run_says_what_is_in_the_way_and_offers_no_command(self):
        Subject.objects.create(profile=main_profile(), name="TEST SAMPLE: Other", landing_position=1)
        self.client.force_login(self.admin)
        resp = self.post(action="dry_run")
        self.assertContains(resp, "remove_sample_data --profile")
        self.assertContains(resp, "NOT READY")
        self.assertNotContains(resp, "Ready to import.")
        self.assertNotContains(resp, "--import")

    def test_reconciliation_after_an_import_and_the_review_list(self):
        self.client.force_login(self.admin)
        service.run_import(self.data, "small.docx", main_profile(), self.admin)
        resp = self.post(action="reconcile")
        self.assertContains(resp, "RESULT: MATCH")
        self.assertEqual(Subject.objects.filter(profile=main_profile()).count(), 4)
        resp = self.post(action="reconcile_download")
        self.assertIn(b"RESULT: MATCH", resp.content)
        listing = self.client.get(reverse("review_list"))
        self.assertContains(listing, "Only a case name")
        self.assertContains(listing, "Ex Parte")

    def test_an_unexpected_error_is_a_plain_message_not_a_server_error(self):
        self.client.force_login(self.admin)
        with mock.patch("diary.views.import_service.dry_run", side_effect=RuntimeError("boom")):
            resp = self.post(action="dry_run")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Something unexpected went wrong")

    def test_a_non_word_file_gives_a_message(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("import_word"), {
            "action": "dry_run", "profile": main_profile().pk,
            "file": SimpleUploadedFile("x.docx", b"not a word file"),
        })
        self.assertContains(resp, "not a readable Word")

    def test_home_nav_links_to_import_for_admins_only(self):
        # D86: Import is a tab of Backups & Import, which Home links to (Admin only).
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("home")), reverse("backup_list"))
        self.assertContains(self.client.get(reverse("backup_list")), reverse("import_word"))
        self.client.force_login(self.editor)
        self.assertNotContains(self.client.get(reverse("home")), reverse("import_word"))


@override_settings(SECURE_SSL_REDIRECT=False)
class ReviewListTests(TestCase):
    def test_lists_only_this_profile_and_live_records(self):
        reader = join_main(User.objects.create_user("rita", password=PASSWORD))
        main = main_profile()
        subject = Subject.objects.create(profile=main, name="Arbitration", landing_position=1)
        Item.objects.create(profile=main, subject=subject, text="<p>Mine</p>", needs_review=True, review_note="check")
        Item.objects.create(profile=main, subject=subject, text="<p>Fine</p>")
        Section.objects.create(profile=main, subject=subject, name="A section", needs_review=True)
        junior = other_profile()
        elsewhere = Subject.objects.create(profile=junior, name="Elsewhere")
        Item.objects.create(profile=junior, subject=elsewhere, text="<p>Theirs</p>", needs_review=True)
        self.client.force_login(reader)
        resp = self.client.get(reverse("review_list"))
        self.assertContains(resp, "Mine")
        self.assertContains(resp, "A section")
        self.assertNotContains(resp, "Theirs")
        self.assertNotContains(resp, "Fine")
        self.assertContains(resp, "2 records")

    def test_order_is_alphabetical_for_headings_and_by_position_for_items_inside_each_parent(self):
        reader = join_main(User.objects.create_user("rita", password=PASSWORD))
        main = main_profile()
        subject = Subject.objects.create(profile=main, name="Arbitration", landing_position=1)
        # stored (Word) positions say Zeta first; the alphabet says Alpha first
        late = Topic.objects.create(profile=main, subject=subject, name="Zeta", position=1)
        early = Topic.objects.create(profile=main, subject=subject, name="Alpha", position=2)
        # created in the "wrong" order on purpose: primary keys must not decide the order
        Item.objects.create(profile=main, topic=late, text="<p>zzitemL2</p>", position=2, needs_review=True)
        Section.objects.create(profile=main, topic=late, name="zzsectionL1", position=1, needs_review=True)
        Item.objects.create(profile=main, topic=early, text="<p>zzitemE1</p>", position=1, needs_review=True)
        Section.objects.create(profile=main, topic=early, name="zzsectionE2", position=2, needs_review=True)
        self.client.force_login(reader)
        body = self.client.get(reverse("review_list")).content.decode()
        positions = [body.index(x) for x in ("zzitemE1", "zzsectionE2", "zzsectionL1", "zzitemL2")]
        self.assertEqual(positions, sorted(positions))

    def test_subject_filter_count_path_note_and_context_link(self):
        reader = join_main(User.objects.create_user("rita", password=PASSWORD))
        main = main_profile()
        one = Subject.objects.create(profile=main, name="Arbitration", landing_position=1)
        two = Subject.objects.create(profile=main, name="Contracts", landing_position=2)
        topic = Topic.objects.create(profile=main, subject=one, name="Fraud")
        Item.objects.create(profile=main, topic=topic, text="<p>zzfraud</p>", needs_review=True, review_note="whynote")
        Section.objects.create(profile=main, subject=two, name="zzsection", needs_review=True)
        self.client.force_login(reader)
        resp = self.client.get(reverse("review_list"))
        self.assertContains(resp, "2 records")
        self.assertContains(resp, "Arbitration (1)")
        self.assertContains(resp, "Contracts (1)")
        self.assertContains(resp, "Arbitration &gt; Fraud")
        self.assertContains(resp, "whynote")
        item = Item.objects.get(topic=topic)
        self.assertContains(resp, 'href="%s#n-item-%d"' % (reverse("read_subject", args=[one.pk]), item.pk))
        self.assertContains(resp, "Open in context")
        self.assertContains(resp, 'class="col-kind"')
        resp = self.client.get(reverse("review_list"), {"subject": one.pk})
        self.assertContains(resp, "1 record ")
        self.assertContains(resp, "zzfraud")
        self.assertNotContains(resp, "zzsection")
        self.assertContains(resp, "of 2 in all")
        resp = self.client.get(reverse("review_list"), {"subject": "bogus"})
        self.assertContains(resp, "2 records")

    def test_requires_a_profile(self):
        user = User.objects.create_user("nobody", password=PASSWORD)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("review_list")).status_code, 403)

    def test_item_section_and_anchors_are_listed_and_trash_is_not(self):
        reader = join_main(User.objects.create_user("rita", password=PASSWORD))
        main = main_profile()
        subject = Subject.objects.create(profile=main, name="Arbitration", landing_position=1)
        topic = Topic.objects.create(profile=main, subject=subject, name="Fraud")
        child = Item.objects.create(profile=main, topic=topic, text="<p>zzchild</p>", needs_review=True)
        section = Section.objects.create(profile=main, topic=topic, name="zzsection", needs_review=True)
        gone = Item.objects.create(profile=main, topic=topic, text="<p>zzgone</p>", needs_review=True,
                                   deleted_at=timezone.now())
        dead_topic = Topic.objects.create(profile=main, subject=subject, name="Dead", deleted_at=timezone.now())
        Item.objects.create(profile=main, topic=dead_topic, text="<p>zzunder</p>", needs_review=True)
        self.client.force_login(reader)
        resp = self.client.get(reverse("review_list"))
        whole = reverse("read_subject", args=[subject.pk])
        self.assertContains(resp, "zzchild")
        self.assertContains(resp, 'href="%s#n-item-%d"' % (whole, child.pk))
        self.assertContains(resp, 'href="%s#n-section-%d"' % (whole, section.pk))
        self.assertContains(resp, "2 records")
        for text in ("zzgone", "zzunder"):
            self.assertNotContains(resp, text)
        self.assertNotEqual(gone.pk, child.pk)

    def test_review_list_and_search_for_review_only_return_the_same_records(self):
        from diary.search import run_search
        from diary.views import _review_rows

        main = main_profile()
        subject = Subject.objects.create(profile=main, name="Arbitration", landing_position=1)
        topic = Topic.objects.create(profile=main, subject=subject, name="Fraud")
        Item.objects.create(profile=main, topic=topic, text="<p>c</p>", needs_review=True)
        Item.objects.create(profile=main, subject=subject, text="<p>i</p>", needs_review=True)
        Section.objects.create(profile=main, topic=topic, name="s", needs_review=True)
        Item.objects.create(profile=main, topic=topic, text="<p>not marked</p>")
        rows = _review_rows(main)
        results = run_search(main, "", review_only=True)
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["url"] for r in rows], [r.url for r in results])

    def test_links_between_review_list_and_search(self):
        reader = join_main(User.objects.create_user("rita", password=PASSWORD))
        main = main_profile()
        subject = Subject.objects.create(profile=main, name="Arbitration", landing_position=1)
        Item.objects.create(profile=main, subject=subject, text="<p>x</p>", needs_review=True)
        self.client.force_login(reader)
        resp = self.client.get(reverse("review_list"), {"subject": subject.pk})
        self.assertContains(resp, 'href="%s?review=1&amp;subject=%d"' % (reverse("search"), subject.pk))
        resp = self.client.get(reverse("review_list"))
        self.assertContains(resp, 'href="%s?review=1"' % reverse("search"))


class ImportCommandTests(TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "small.docx"
        self.path.write_bytes(make_docx(SMALL))

    def run_command(self, *args):
        out = StringIO()
        call_command("import_docx", "--file", str(self.path), *args, stdout=out)
        return out.getvalue()

    def test_default_is_a_dry_run(self):
        out = self.run_command("--profile", "Main")
        self.assertIn("DRY RUN", out)
        self.assertEqual(Subject.objects.count(), 0)

    def test_import_then_reconcile(self):
        out = self.run_command("--profile", "Main", "--import")
        self.assertIn("RESULT: MATCH", out)
        self.assertIn("RESULT: MATCH", self.run_command("--profile", "Main", "--reconcile"))

    def test_dry_run_and_import_refuse_a_profile_with_other_live_data(self):
        Subject.objects.create(profile=main_profile(), name="TEST SAMPLE: Other", landing_position=1)
        self.assertIn("NOT READY", self.run_command("--profile", "Main"))
        with self.assertRaises(CommandError) as caught:
            self.run_command("--profile", "Main", "--import")
        self.assertIn("remove_sample_data --profile", str(caught.exception))
        self.assertEqual(Item.objects.count(), 0)

    def test_an_unexpected_error_is_a_plain_message(self):
        with mock.patch("diary.importer.service.run_import", side_effect=RuntimeError("boom")):
            with self.assertRaises(CommandError) as caught:
                self.run_command("--profile", "Main", "--import")
        self.assertIn("unexpected error: boom", str(caught.exception))

    def test_unknown_profile_and_missing_file(self):
        with self.assertRaises(CommandError):
            self.run_command("--profile", "Nope")
        with self.assertRaises(CommandError):
            call_command("import_docx", "--file", "/no/such.docx", "--profile", "Main")
