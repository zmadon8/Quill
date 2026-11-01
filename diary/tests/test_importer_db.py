"""Database and screen tests of the Word import (Milestone 2)."""
from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Profile, User
from backups.models import BackupFile
from diary.importer import loader, service
from diary.importer.docx_reader import file_digest
from diary.models import Item, Section, Subject, Subtopic, Topic, VersionHistory
from diary.tests.docx_builder import SMALL, make_docx
from diary.tests.helpers import join_main, main_profile

PASSWORD = "x-long-pass-123"


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
        self.assertEqual(clean.citation, "Alpha v Beta [(2010) 1 SCC 1]")
        self.assertEqual(clean.text_plain, "Clean proposition")
        self.assertFalse(clean.needs_review)
        whole = Item.objects.get(original_line="Only a case name")
        self.assertEqual((whole.citation, whole.text_plain), ("", "Only a case name"))
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
        total = sum(m.objects.filter(profile=self.profile).count() for m in (Subject, Topic, Subtopic, Section, Item))
        history = VersionHistory.objects.filter(profile=self.profile, change_kind="import")
        self.assertEqual(history.count(), total)
        self.assertTrue(history.filter(record_type="item").exists())

    def test_backups_are_made_before_and_after(self):
        before = BackupFile.objects.count()
        _, notes = self.do_import()
        self.assertEqual(BackupFile.objects.count(), before + 2)
        self.assertTrue(any(n.startswith("Backup before") for n in notes))
        self.assertTrue(any(n.startswith("Backup after") for n in notes))

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

    def test_reconciliation_reports_a_changed_record_never_hides_it(self):
        self.do_import()
        item = Item.objects.get(original_line__startswith="Clean proposition")
        item.citation = "Changed"
        item.save()
        _, text = service.reconcile(self.data, "small.docx", self.profile)
        self.assertIn("RESULT:", text)
        self.assertNotIn("RESULT: MATCH", text)
        self.assertIn("UNEXPECTED differences: 1", text)

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
        with self.assertRaises(Exception):
            loader.import_plan(plan, self.profile)
        self.assertEqual(Subject.objects.count(), 0)
        self.assertEqual(Item.objects.count(), 0)


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
        self.assertContains(resp, "Import into Main")
        self.assertEqual(Subject.objects.count(), 0)

    def test_dry_run_download_is_a_text_file(self):
        self.client.force_login(self.admin)
        resp = self.post(action="dry_run_download")
        self.assertEqual(resp["Content-Type"], "text/plain; charset=utf-8")
        self.assertIn("attachment", resp["Content-Disposition"])
        self.assertIn(b"DRY RUN", resp.content)

    def test_import_needs_the_word_and_the_approved_fingerprint(self):
        self.client.force_login(self.admin)
        sha = file_digest(self.data)
        self.assertContains(self.post(action="import", sha256=sha, confirm_word="no"), "Type IMPORT")
        self.assertContains(self.post(action="import", confirm_word="IMPORT"), "Run the dry run first")
        self.assertContains(self.post(action="import", sha256="0" * 64, confirm_word="IMPORT"), "not the same file")
        self.assertEqual(Subject.objects.count(), 0)

    def test_import_then_reconciliation_then_review_list(self):
        self.client.force_login(self.admin)
        resp = self.post(action="import", sha256=file_digest(self.data), confirm_word="IMPORT")
        self.assertContains(resp, "RESULT: MATCH")
        self.assertEqual(Subject.objects.filter(profile=main_profile()).count(), 4)
        resp = self.post(action="reconcile_download")
        self.assertIn(b"RESULT: MATCH", resp.content)
        listing = self.client.get(reverse("review_list"))
        self.assertContains(listing, "Only a case name")
        self.assertContains(listing, "Ex Parte")

    def test_a_non_word_file_gives_a_message(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("import_word"), {
            "action": "dry_run", "profile": main_profile().pk,
            "file": SimpleUploadedFile("x.docx", b"not a word file"),
        })
        self.assertContains(resp, "not a readable Word")

    def test_home_nav_links_to_import_for_admins_only(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("home")), reverse("import_word"))
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

    def test_requires_a_profile(self):
        user = User.objects.create_user("nobody", password=PASSWORD)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("review_list")).status_code, 403)


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

    def test_unknown_profile_and_missing_file(self):
        with self.assertRaises(CommandError):
            self.run_command("--profile", "Nope")
        with self.assertRaises(CommandError):
            call_command("import_docx", "--file", "/no/such.docx", "--profile", "Main")
