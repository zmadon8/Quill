"""Word export with the database (Milestone 6): gathering, the three exports, permissions, settings, the round trip."""
import io
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest import skipUnless

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import Profile, User
from diary.importer import service as import_service
from diary.importer.docx_reader import read_docx
from diary.models import Case, Item, Note, NoteLink, Section, Subject, Subtopic, Topic, UserSettings
from diary.tests.docx_builder import SMALL, make_docx
from diary.tests.helpers import join_main, main_profile
from diary.views import item_counts_by_subject
from diary.wordexport import gather, service

PASSWORD = "x-long-pass-123"
REAL_FILE = Path(__file__).resolve().parents[2] / "Case Law Diary.docx"
NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def paragraphs(data):
    return read_docx(data)[0]


def texts(data, style=None):
    return [p.text for p in paragraphs(data) if style is None or p.style == style]


def add_item(profile, parent, text, citation="", position=1, **fields):
    column, obj = parent
    item = Item.objects.create(profile=profile, **{column: obj}, text=f"<p>{text}</p>", position=position, **fields)
    if citation:
        Case.objects.create(profile=profile, item=item, citation=citation, position=1)
    return item


@override_settings(SECURE_SSL_REDIRECT=False)
class ExportCase(TestCase):
    def setUp(self):
        self.profile = main_profile()
        self.other_profile = Profile.objects.create(program="diary", name="Elsewhere")
        self.editor = join_main(User.objects.create_user("editor", password=PASSWORD), "editor")
        self.reader = join_main(User.objects.create_user("reader", password=PASSWORD), "reader")
        self.admin = join_main(User.objects.create_user("boss", password=PASSWORD, is_superuser=True), "reader")
        p = self.profile
        self.arb = Subject.objects.create(profile=p, name="Arbitration", position=1)
        self.con = Subject.objects.create(profile=p, name="Contracts", position=2)
        self.stamp = Subject.objects.create(profile=p, name="Stamp Act", show_on_landing=False, other_acts_position=1)
        self.topic = Topic.objects.create(profile=p, subject=self.arb, name="Arbitrability", position=1)
        self.zed = Topic.objects.create(profile=p, subject=self.arb, name="Zed", position=2)
        self.fraud = Subtopic.objects.create(profile=p, topic=self.topic, name="Fraud", position=1)
        self.duty = Subtopic.objects.create(profile=p, subject=self.stamp, name="Duty", position=1)
        self.first = add_item(p, ("topic", self.topic), "Prop one", "(2020) 1 SCC 1", 1, flag="pending", flag_text="check")
        self.section = Section.objects.create(profile=p, topic=self.topic, name="Ex Parte", position=2, flag="other",
                                              flag_text="sec")
        self.after = add_item(p, ("topic", self.topic), "After section", "(2021) 2 SCC 2", 3)
        self.in_fraud = add_item(p, ("subtopic", self.fraud), "Fraud item", "(2019) 3 SCC 3", 1)
        self.in_duty = add_item(p, ("subtopic", self.duty), "Duty item", "(2018) 4 SCC 4", 1)
        self.direct = add_item(p, ("subject", self.stamp), "Direct item", "(2017) 5 SCC 5", 1)
        add_item(p, ("subject", self.con), "Contract item", "(2016) 6 SCC 6", 1)
        # Not exported: Trash, a Topic in Trash with its Item, another profile.
        self.trashed = add_item(p, ("topic", self.topic), "TRASHED ITEM", "(2000) 9 SCC 9", 9, deleted_at=NOW)
        self.gone_topic = Topic.objects.create(profile=p, subject=self.arb, name="Gone Topic", position=3, deleted_at=NOW)
        add_item(p, ("topic", self.gone_topic), "UNDER GONE TOPIC", "", 1)
        self.else_subject = Subject.objects.create(profile=self.other_profile, name="Elsewhere Subject", position=1)
        else_topic = Topic.objects.create(profile=self.other_profile, subject=self.else_subject, name="E", position=1)
        self.else_topic = else_topic
        add_item(self.other_profile, ("topic", else_topic), "ELSEWHERE ITEM", "", 1)
        # A Note with a link to the first Item and one to the trashed Item.
        self.note = Note.objects.create(profile=p, topic=self.topic, text="<p>Remember</p>", position=1)
        NoteLink.objects.create(profile=p, note=self.note, item=self.first, position=1)
        NoteLink.objects.create(profile=p, note=self.note, item=self.trashed, position=2)

    def login(self, user):
        client = Client()
        client.force_login(user)
        return client

    def full(self, user=None, **kw):
        return service.full(self.profile, user or self.editor, now=NOW, **kw)


class GatherTests(ExportCase):
    def test_only_live_records_of_the_profile_in_diary_order(self):
        snap = gather.load(self.profile)
        self.assertEqual([s.name for s in snap.main], ["Arbitration", "Contracts"])
        self.assertEqual([s.name for s in snap.others], ["Stamp Act"])
        arb = snap.main[0]
        self.assertEqual([t.name for t in arb.topics], ["Arbitrability", "Zed"])  # not "Gone Topic": it is in Trash
        self.assertEqual([t.index for t in arb.topics], [1, 2])
        entries = arb.topics[0].container.entries
        self.assertEqual([type(e).__name__ for e in entries], ["XItem", "XSection", "XItem"])  # the trashed Item is not there
        self.assertNotIn("Elsewhere Subject", [s.name for s in snap.main + snap.others])

    def test_the_number_of_queries_does_not_depend_on_the_size(self):
        with CaptureQueriesContext(connection) as small:
            gather.load(self.profile)
        for n in range(40):
            add_item(self.profile, ("topic", self.zed), f"extra {n}", f"(2000) {n} SCC 1", n + 1)
        with CaptureQueriesContext(connection) as larger:
            gather.load(self.profile)
        self.assertEqual(len(small), len(larger))
        self.assertLess(len(larger), 30)

    def test_note_links_print_the_target_path_and_mark_a_trashed_target(self):
        note = gather.load(self.profile).main[0].topics[0].container.notes[0]
        self.assertEqual([(link.path, link.deleted) for link in note.links], [
            ("Arbitration > Arbitrability > Prop one", False),
            ("Arbitration > Arbitrability > TRASHED ITEM", True),
        ])


    def test_links_follow_their_set_order_not_their_creation_order(self):
        note = Note.objects.create(profile=self.profile, topic=self.zed, text="<p>Ordered links</p>", position=1)
        NoteLink.objects.create(profile=self.profile, note=note, item=self.in_fraud, position=2)  # created first, shown second
        NoteLink.objects.create(profile=self.profile, note=note, item=self.after, position=1)
        zed = next(t for t in gather.load(self.profile).main[0].topics if t.name == "Zed")
        self.assertEqual([link.path for link in zed.container.notes[0].links],
                         ["Arbitration > Arbitrability > After section", "Arbitration > Arbitrability > Fraud > Fraud item"])
        page = self.login(self.reader).get(reverse("read_subject", args=[self.arb.pk])).content.decode()
        self.assertLess(page.index("After section</a>", page.index("Ordered links")), page.index("Fraud item</a>", page.index("Ordered links")))


class FullExportTests(ExportCase):
    def test_file_name_and_content_type(self):
        result = self.full()
        self.assertEqual(result.name, "Case Law Diary Main Full 2026-11-01.docx")
        self.assertEqual(result.content_type, DOCX)
        self.assertEqual(result.items, 6)

    def test_content_excludes_trash_and_other_profiles(self):
        everything = "\n".join(texts(self.full().data))
        self.assertNotIn("TRASHED", "\n".join(line for line in everything.split("\n") if not line.startswith("See also:")))
        self.assertNotIn("UNDER GONE", everything)
        self.assertNotIn("Gone Topic", everything)
        self.assertNotIn("ELSEWHERE", everything)
        self.assertNotIn("Elsewhere Subject", everything)

    def test_structure_numbers_and_order(self):
        data = self.full().data
        self.assertEqual(texts(data, "Heading1"), ["Arbitration", "Contracts", "Other Subjects"])
        self.assertEqual(texts(data, "Heading2"), ["A\tArbitrability", "B\tZed", "Stamp Act"])
        self.assertEqual(texts(data, "DiarySubtopic"), ["1\tFraud", "1\tDuty"])
        self.assertEqual(texts(data, "DiarySection"), ["(a)\tEx Parte"])
        items = texts(data, "DiaryItem")
        self.assertIn("(1)\tProp one - (2020) 1 SCC 1", items)
        self.assertIn("(1)\tAfter section - (2021) 2 SCC 2", items)  # restarts after the Section

    def test_notes_print_see_also_and_a_deleted_target_says_so(self):
        everything = "\n".join(texts(self.full().data))
        self.assertIn("See also: Arbitration > Arbitrability > Prop one", everything)
        self.assertIn("See also: Arbitration > Arbitrability > TRASHED ITEM (target deleted)", everything)

    def test_flags_only_when_asked(self):
        # D88: "Include flags" (it was "Include review markers") covers every flag of Items and Sections.
        plain = "\n".join(texts(self.full().data))
        marked = "\n".join(texts(self.full(include_review=True).data))
        self.assertNotIn("[Pending", plain)
        self.assertNotIn("[sec]", plain)
        self.assertIn("Flags: not included.", plain)
        self.assertIn("Prop one - (2020) 1 SCC 1 [Pending: check]", marked)
        self.assertIn("(a)\tEx Parte [sec]", marked)
        self.assertNotIn("For review", marked)

    def test_numbers_follow_the_users_settings(self):
        UserSettings.objects.create(user=self.editor, topic_format="upper_roman", item_format="lower_alpha",
                                    section_format="section_n")
        data = self.full().data
        self.assertEqual(texts(data, "Heading2")[:2], ["I\tArbitrability", "II\tZed"])
        self.assertIn("a\tProp one - (2020) 1 SCC 1", texts(data, "DiaryItem"))
        self.assertEqual(texts(data, "DiarySection"), ["Section 1\tEx Parte"])

    def test_date_format_and_time_zone_in_the_name(self):
        UserSettings.objects.create(user=self.editor, export_date_format="D Month YYYY")
        self.assertEqual(self.full().name, "Case Law Diary Main Full 1 November 2026.docx")
        late = datetime(2026, 11, 1, 20, 0, tzinfo=timezone.utc)  # already 2 November in India
        UserSettings.objects.filter(user=self.editor).update(export_date_format="DD-MM-YYYY")
        fresh = User.objects.get(pk=self.editor.pk)  # the first user object still holds the earlier settings
        self.assertEqual(service.full(self.profile, fresh, now=late).name, "Case Law Diary Main Full 02-11-2026.docx")

    def test_a_name_that_cleans_to_nothing_uses_the_profile_name_like_the_preview(self):
        self.profile.export_name = " . "
        self.profile.save()
        self.assertEqual(self.full().name, "Main Full 2026-11-01.docx")

    def test_profile_export_name_and_cleaning(self):
        self.profile.export_name = 'Madon: "Law"/Diary'
        self.profile.save()
        self.assertEqual(self.full().name, "Madon- -Law--Diary Full 2026-11-01.docx")


class BySubjectTests(ExportCase):
    def archive(self, **kw):
        result = service.by_subject(self.profile, self.editor, now=NOW, **kw)
        return result, zipfile.ZipFile(io.BytesIO(result.data))

    def test_zip_holds_one_file_per_subject_the_other_subjects_together_and_a_manifest(self):
        result, archive = self.archive()
        self.assertEqual(result.name, "Case Law Diary Main Full - by Subject 2026-11-01.zip")
        self.assertEqual(sorted(archive.namelist()), [
            "Case Law Diary Main Arbitration 2026-11-01.docx",
            "Case Law Diary Main Contracts 2026-11-01.docx",
            "Case Law Diary Main Other Subjects 2026-11-01.docx",
            "manifest.txt",
        ])
        other = archive.read("Case Law Diary Main Other Subjects 2026-11-01.docx")
        self.assertEqual(texts(other, "Heading1"), ["Other Subjects"])
        self.assertEqual(texts(other, "Heading2"), ["Stamp Act"])
        arb = archive.read("Case Law Diary Main Arbitration 2026-11-01.docx")
        self.assertEqual(texts(arb, "Heading1"), ["Arbitration"])

    def test_manifest_counts_match_each_document_the_screen_and_the_full_export(self):
        result, archive = self.archive()
        manifest = archive.read("manifest.txt").decode()
        self.assertIn("Case Law Diary Main Arbitration 2026-11-01.docx: 3 Items", manifest)
        self.assertIn("Case Law Diary Main Contracts 2026-11-01.docx: 1 Item\n", manifest)
        self.assertIn("Case Law Diary Main Other Subjects 2026-11-01.docx: 2 Items", manifest)
        self.assertIn("Total: 6 Items in 3 documents.", manifest)
        counts = item_counts_by_subject(self.profile)
        self.assertEqual(result.items, sum(n for n, _ in counts.values()))  # the Subjects page counts
        self.assertEqual(result.items, self.full().items)
        for subject, expected in ((self.arb, 3), (self.con, 1)):
            self.assertEqual(counts[subject.pk][0], expected)

    def test_each_document_carries_its_own_count_and_date_line(self):
        _, archive = self.archive()
        arb = archive.read("Case Law Diary Main Arbitration 2026-11-01.docx")
        self.assertIn("Exported 2026-11-01. Records in this document: 3 Items.", texts(arb))

    def test_flags_apply_to_the_zip_too(self):
        _, archive = self.archive(include_review=True)
        arb = "\n".join(texts(archive.read("Case Law Diary Main Arbitration 2026-11-01.docx")))
        self.assertIn("[Pending: check]", arb)

    def test_two_subjects_with_the_same_cleaned_name_do_not_overwrite_each_other(self):
        Subject.objects.create(profile=self.profile, name="Tort?", position=5)
        Subject.objects.create(profile=self.profile, name="Tort*", position=6)
        _, archive = self.archive()
        names = sorted(n for n in archive.namelist() if "Tort" in n)
        self.assertEqual(names, ["Case Law Diary Main Tort- (2) 2026-11-01.docx", "Case Law Diary Main Tort- 2026-11-01.docx"])


class CurrentViewTests(ExportCase):
    def view(self, kind, pk, **kw):
        return service.current_view(self.profile, self.editor, kind, pk, now=NOW, **kw)

    def test_subject_topic_and_subtopic_scopes(self):
        subject = self.view("subject", self.arb.pk)
        self.assertEqual(subject.name, "Case Law Diary Main Arbitration 2026-11-01.docx")
        self.assertEqual(texts(subject.data, "Heading1"), ["Arbitration"])
        topic = self.view("topic", self.zed.pk)
        self.assertEqual(topic.name, "Case Law Diary Main Arbitration, Zed 2026-11-01.docx")
        self.assertEqual(texts(topic.data, "Heading1"), ["B\tZed"])  # the on-screen letter is kept
        sub = self.view("subtopic", self.fraud.pk)
        self.assertEqual(sub.name, "Case Law Diary Main Arbitration, Arbitrability, Fraud 2026-11-01.docx")
        self.assertEqual(texts(sub.data, "Heading1"), ["1\tFraud"])
        self.assertIn("(1)\tFraud item - (2019) 3 SCC 3", texts(sub.data))
        self.assertIn("On screen: Arbitration > Arbitrability > Fraud", texts(sub.data))

    def test_a_single_other_subject_is_heading_one_alone(self):
        result = self.view("subject", self.stamp.pk)
        self.assertEqual(texts(result.data, "Heading1"), ["Stamp Act"])
        self.assertEqual(texts(result.data, "Heading2"), [])
        self.assertEqual(texts(result.data, "DiarySubtopic"), ["1\tDuty"])

    def test_the_whole_subtree_is_exported_without_trash(self):
        everything = "\n".join(texts(self.view("subject", self.arb.pk).data))
        self.assertIn("Fraud item", everything)
        # Only a "See also" line may name a trashed Item (marked "target deleted"); it is never printed as content.
        self.assertNotIn("TRASHED", "\n".join(line for line in everything.split("\n") if not line.startswith("See also:")))
        self.assertEqual(self.view("subject", self.arb.pk).items, 3)

    def test_scope_outside_the_profile_or_in_trash_is_refused(self):
        for kind, pk in (("subject", self.else_subject.pk), ("topic", self.else_topic.pk), ("topic", self.gone_topic.pk),
                         ("subject", 10**9), ("nonsense", 1)):
            with self.assertRaises(service.ExportError):
                self.view(kind, pk)

    def test_flags_in_a_view(self):
        marked = "\n".join(texts(self.view("topic", self.topic.pk, include_review=True).data))
        self.assertIn("[Pending: check]", marked)


class ViewTests(ExportCase):
    def url(self, **params):
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{reverse('export_download')}?{query}"

    def test_sign_in_is_needed(self):
        for url in (reverse("export"), self.url(type="full")):
            self.assertEqual(Client().get(url).status_code, 302)

    def test_the_page_shows_full_buttons_to_editors_and_admin_but_not_readers(self):
        for user, full in ((self.editor, True), (self.admin, True), (self.reader, False)):
            body = self.login(user).get(reverse("export")).content.decode()
            self.assertEqual('value="full"' in body, full, user.username)
            self.assertEqual('value="by_subject"' in body, full, user.username)
            self.assertIn("Download this Subject", body)

    def test_editor_and_admin_download_full_and_zip(self):
        for user in (self.editor, self.admin):
            client = self.login(user)
            resp = client.get(self.url(type="full"))
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp["Content-Type"], DOCX)
            self.assertIn('filename="Case Law Diary Main Full ', resp["Content-Disposition"])
            self.assertTrue(resp["Content-Disposition"].startswith("attachment"))
            self.assertEqual(resp["X-Export-Items"], "6")
            zipped = client.get(self.url(type="by_subject"))
            self.assertEqual(zipped["Content-Type"], "application/zip")
            self.assertIn("manifest.txt", zipfile.ZipFile(io.BytesIO(zipped.content)).namelist())

    def test_a_reader_gets_403_for_both_full_exports_but_can_export_a_view(self):
        client = self.login(self.reader)
        self.assertEqual(client.get(self.url(type="full")).status_code, 403)
        self.assertEqual(client.get(self.url(type="by_subject")).status_code, 403)
        resp = client.get(self.url(type="view", kind="topic", pk=self.topic.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(texts(resp.content, "Heading1"), ["A\tArbitrability"])

    def test_review_option_in_the_download(self):
        client = self.login(self.editor)
        plain = texts(client.get(self.url(type="view", kind="topic", pk=self.topic.pk)).content)
        marked = texts(client.get(self.url(type="view", kind="topic", pk=self.topic.pk, review=1)).content)
        self.assertFalse(any("[Pending" in t for t in plain))
        self.assertTrue(any("[Pending" in t for t in marked))

    def test_another_profiles_records_and_bad_input_are_404(self):
        client = self.login(self.editor)
        for params in (dict(type="view", kind="subject", pk=self.else_subject.pk),
                       dict(type="view", kind="topic", pk=self.else_topic.pk),
                       dict(type="view", kind="topic", pk=self.gone_topic.pk),
                       dict(type="view", kind="topic", pk="abc"), dict(type="view", kind="x", pk=1),
                       dict(type="view"), dict(type="zip"), dict()):
            self.assertEqual(client.get(self.url(**params)).status_code, 404, params)
        self.assertEqual(client.get(f"{reverse('export')}?kind=topic&pk={self.else_topic.pk}").status_code, 404)

    def test_a_user_of_another_profile_never_sees_this_profiles_data(self):
        outsider = User.objects.create_user("outsider", password=PASSWORD)
        from accounts.profiles import set_user_profile

        set_user_profile(outsider, self.other_profile, "editor")
        client = self.login(outsider)
        self.assertEqual(client.get(self.url(type="view", kind="topic", pk=self.topic.pk)).status_code, 404)
        full = client.get(self.url(type="full"))
        everything = "\n".join(texts(full.content))
        self.assertIn("ELSEWHERE ITEM", everything)
        self.assertNotIn("Prop one", everything)
        self.assertTrue(full["Content-Disposition"].count("Elsewhere"))  # that profile's own default export name

    def test_a_user_without_a_profile_gets_the_no_profile_page(self):
        nobody = User.objects.create_user("nobody", password=PASSWORD)
        self.assertEqual(self.login(nobody).get(reverse("export")).status_code, 403)

    def test_header_export_opens_the_page_ready_for_this_view_and_there_is_no_floating_button(self):
        # Round 18: the Export button in the sticky breadcrumb row is gone; the header's Export carries the page.
        pages = {
            reverse("read_subject", args=[self.arb.pk]): f"kind=subject&amp;pk={self.arb.pk}",
            reverse("read_topic", args=[self.topic.pk]): f"kind=topic&amp;pk={self.topic.pk}",
            reverse("read_subtopic", args=[self.fraud.pk]): f"kind=subtopic&amp;pk={self.fraud.pk}",
            reverse("subject_contents", args=[self.arb.pk]): f"kind=subject&amp;pk={self.arb.pk}",
        }
        for user in (self.editor, self.reader):
            client = self.login(user)
            for page, query in pages.items():
                body = client.get(page).content.decode()
                self.assertIn(f'href="{reverse("export")}?{query}"', body)
                self.assertEqual(body.count('aria-label="Export"'), 1, page)
                self.assertNotIn("export-split", body)
                self.assertNotIn("export-menu", body)
                self.assertNotIn("type=view&amp;", body)

    def test_settings_gear_is_named_settings(self):
        self.editor.header_style = "words"  # D84: with Words the link reads "Settings"; with Icons it is a gear named Settings
        self.editor.save(update_fields=["header_style"])
        body = self.login(self.editor).get(reverse("diary_home")).content.decode()
        self.assertRegex(body, r'<a href="[^"]*"[^>]*aria-label="Settings"[^>]*>Settings</a>')
        self.assertNotIn("Profile settings", body)

    def test_current_view_is_not_offered_on_search_review_trash_or_history(self):
        from diary.models import VersionHistory

        VersionHistory.objects.create(profile=self.profile, record_type="item", record_id=self.first.pk, version=1,
                                      snapshot={"text": "<p>Prop one</p>"}, change_kind="create")
        client = self.login(self.editor)
        for url in (reverse("search"), reverse("flags"), reverse("flag_links"), reverse("trash"),
                    reverse("history", args=["item", self.first.pk])):
            self.assertNotContains(client.get(url), f'href="{reverse("export")}?kind=')

    def test_the_export_page_with_a_view_shows_its_path(self):
        body = self.login(self.reader).get(f"{reverse('export')}?kind=subtopic&pk={self.fraud.pk}").content.decode()
        self.assertIn("Arbitration > Arbitrability > Fraud", body)
        self.assertIn('value="view"', body)

    def test_export_page_is_tidied_and_flags_are_checked_by_default(self):
        body = self.login(self.editor).get(reverse("export")).content.decode()
        self.assertEqual(body.count('type="checkbox"'), 1)
        self.assertIn('name="review" value="1" checked> Include flags</label>', body)
        self.assertNotIn("amber", body)
        self.assertNotIn("A whole Subject", body)
        self.assertIn("<h2>Subject</h2>", body)
        self.assertEqual(body.count(">Subject</label>"), 1)  # the hidden label for the picker, not a visible second heading
        self.assertIn('class="visually-hidden" for="export-subject">Subject</label>', body)
        unchecked = self.login(self.editor).get(reverse("export") + "?review=0").content.decode()
        self.assertNotIn("checked>", unchecked)

    def test_subject_picker_downloads_a_subject_with_the_single_checkbox(self):
        client = self.login(self.reader)
        marked = texts(client.get(self.url(type="subject", subject_pk=self.arb.pk, review=1)).content)
        plain = texts(client.get(self.url(type="subject", subject_pk=self.arb.pk)).content)
        self.assertTrue(any("[Pending" in t for t in marked))
        self.assertFalse(any("[Pending" in t for t in plain))
        self.assertEqual(client.get(self.url(type="subject", subject_pk="x")).status_code, 404)

    def test_nav_has_an_export_link(self):
        self.assertContains(self.login(self.reader).get(reverse("diary_home")), f'href="{reverse("export")}"')


class SettingsTests(ExportCase):
    def test_date_format_is_saved_from_my_settings(self):
        client = self.login(self.editor)
        resp = client.post(reverse("my_settings"), {"landing_program": "", "export_date_format": "DD-MM-YYYY"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(UserSettings.objects.get(user=self.editor).export_date_format, "DD-MM-YYYY")
        # A form that does not send it leaves it alone.
        client.post(reverse("my_settings"), {"landing_program": ""})
        self.assertEqual(UserSettings.objects.get(user=self.editor).export_date_format, "DD-MM-YYYY")

    def test_junk_date_format_is_refused(self):
        client = self.login(self.editor)
        resp = client.post(reverse("my_settings"), {"landing_program": "", "export_date_format": "MM/DD/YY"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(UserSettings.objects.filter(user=self.editor, export_date_format="MM/DD/YY").exists())

    def test_the_date_choice_and_file_name_are_on_the_export_page_not_settings(self):
        # Round 18 (D97): both moved from Settings to the Export page.
        body = self.login(self.reader).get(reverse("export")).content.decode()
        self.assertIn("Date in Word file names", body)
        self.assertIn('name="export_name"', body)
        self.assertIn('name="export_date_format"', body)
        settings_page = self.login(self.reader).get(reverse("my_settings")).content.decode()
        self.assertNotIn("Date in Word file names", settings_page)
        self.assertNotIn('name="export_name"', settings_page)

    def test_a_reader_can_change_the_export_file_name_and_their_date_format(self):
        client = self.login(self.reader)
        resp = client.post(reverse("export_settings"), {"export_name": "  A:B  ", "export_date_format": "DD-MM-YYYY"})
        self.assertRedirects(resp, reverse("export"))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.export_name, "A:B")
        self.assertEqual(UserSettings.objects.get(user=self.reader).export_date_format, "DD-MM-YYYY")
        self.assertFalse(UserSettings.objects.filter(user=self.editor, export_date_format="DD-MM-YYYY").exists())
        body = client.get(reverse("export")).content.decode()
        self.assertIn("A-B", body)
        self.assertIn("&#x27;:&#x27; was replaced with &#x27;-&#x27;", body)

    def test_export_settings_keep_the_view_and_refuse_junk(self):
        client = self.login(self.editor)
        resp = client.post(reverse("export_settings"), {"export_name": "", "export_date_format": "DD-MM-YYYY",
                                                        "kind": "topic", "pk": self.topic.pk})
        self.assertRedirects(resp, f"{reverse('export')}?kind=topic&pk={self.topic.pk}", fetch_redirect_response=False)
        bad = client.post(reverse("export_settings"), {"export_name": "X", "export_date_format": "MM/DD/YY"})
        self.assertEqual(bad.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.export_name, "")
        self.assertEqual(client.get(reverse("export_settings")).status_code, 405)


class RoundTripDbTests(TestCase):
    def test_a_small_file_imported_then_exported_matches(self):
        profile = Profile.objects.create(program="diary", name="Trip")
        import_service.run_import(make_docx(SMALL), "small.docx", profile)
        result = service.roundtrip(profile, make_docx(SMALL), now=NOW)
        self.assertTrue(result.ok, result.text)
        self.assertIn("RESULT: PASS", result.text)

    def test_a_record_lost_from_the_database_fails_the_check(self):
        profile = Profile.objects.create(program="diary", name="Trip")
        import_service.run_import(make_docx(SMALL), "small.docx", profile)
        Item.objects.filter(profile=profile, text__contains="Clean proposition").update(deleted_at=NOW)
        result = service.roundtrip(profile, make_docx(SMALL), now=NOW)
        self.assertFalse(result.ok)
        self.assertTrue(any("Clean proposition" in line for line in result.unexpected))

    def test_the_command_prints_the_report_and_fails_on_a_difference(self):
        profile = Profile.objects.create(program="diary", name="Trip")
        data = make_docx(SMALL)
        import_service.run_import(data, "small.docx", profile)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "original.docx"
        path.write_bytes(data)
        out = StringIO()
        call_command("check_export_roundtrip", profile="Trip", file=str(path), stdout=out)
        self.assertIn("RESULT: PASS", out.getvalue())
        Item.objects.filter(profile=profile, text__contains="Clean proposition").update(deleted_at=NOW)
        with self.assertRaises(CommandError):
            call_command("check_export_roundtrip", profile="Trip", file=str(path), stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command("check_export_roundtrip", profile="No such profile", file=str(path), stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command("check_export_roundtrip", profile="Trip", file="missing.docx", stdout=StringIO())


@skipUnless(REAL_FILE.exists(), "Case Law Diary.docx is not in the project folder")
class RealFileRoundTripTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.data = REAL_FILE.read_bytes()
        cls.profile = Profile.objects.create(program="diary", name="Real")
        import_service.run_import(cls.data, REAL_FILE.name, cls.profile)

    def test_export_of_the_imported_file_has_zero_unexpected_differences(self):
        result = service.roundtrip(self.profile, self.data, now=NOW)
        print("\n" + result.text)
        self.assertEqual(result.unexpected, [], result.text)
        self.assertEqual(result.stats["items_export"], 950)
        self.assertEqual(result.stats["citations_checked"], 693)
        self.assertEqual(result.stats["citations_italic"], 693)

    def test_the_zip_counts_match_the_screen_and_the_full_export(self):
        user = User.objects.create_user("viewer", password=PASSWORD)
        full = service.full(self.profile, user, now=NOW)
        zipped = service.by_subject(self.profile, user, now=NOW)
        counts = item_counts_by_subject(self.profile)
        self.assertEqual(full.items, 950)
        self.assertEqual(zipped.items, full.items)
        self.assertEqual(sum(n for n, _ in counts.values()), full.items)
        manifest = zipfile.ZipFile(io.BytesIO(zipped.data)).read("manifest.txt").decode()
        self.assertIn("Total: 950 Items in 11 documents.", manifest)  # 10 main Subjects and one Other Subjects file

    def test_every_subject_file_count_equals_the_subjects_page_count(self):
        user = User.objects.create_user("viewer2", password=PASSWORD)
        counts = item_counts_by_subject(self.profile)
        for subject in Subject.objects.filter(profile=self.profile, show_on_landing=True):
            result = service.current_view(self.profile, user, "subject", subject.pk, now=NOW)
            self.assertEqual(result.items, counts[subject.pk][0], subject.name)


@override_settings(SECURE_SSL_REDIRECT=False)
class PerformanceTests(TestCase):
    def test_five_thousand_items_full_export_and_zip(self):
        profile = Profile.objects.create(program="diary", name="Big")
        user = join_main(User.objects.create_user("big", password=PASSWORD), "editor")
        subject = Subject.objects.create(profile=profile, name="Big Subject", position=1)
        topics = Topic.objects.bulk_create([Topic(profile=profile, subject=subject, name=f"Topic {i:02d}", position=i)
                                           for i in range(50)])
        subtopics = Subtopic.objects.bulk_create([Subtopic(profile=profile, topic=t, name=f"Sub {j}", position=j)
                                                  for t in topics for j in range(5)])
        items = Item.objects.bulk_create([
            Item(profile=profile, subtopic=s, text=f"<p>Proposition {n} of {s.name} with a few words of text</p>",
                 text_plain="x", position=n)
            for s in subtopics for n in range(1, 21)
        ])
        Case.objects.bulk_create([Case(profile=profile, item=i, citation=f"(20{i.pk % 25:02d}) {i.pk} SCC 1", position=1)
                                  for i in items])
        self.assertEqual(len(items), 5000)
        started = time.monotonic()
        full = service.full(profile, user, now=NOW)
        full_seconds = time.monotonic() - started
        started = time.monotonic()
        zipped = service.by_subject(profile, user, now=NOW)
        zip_seconds = time.monotonic() - started
        print(f"\nExport of 5,000 Items: Full {full_seconds:.2f} s ({full.size} bytes), zip {zip_seconds:.2f} s ({zipped.size} bytes)")
        self.assertEqual(full.items, 5000)
        self.assertEqual(zipped.items, 5000)
        self.assertLess(full_seconds, 30)  # Render's request limit is 60 s
        self.assertLess(zip_seconds, 30)
