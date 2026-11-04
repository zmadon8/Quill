"""Round 19 (D98): the Offline copy, one read-only .html file, and export for every member of the profile."""
import re
from datetime import datetime, timezone

from django.test import Client
from django.urls import reverse

from accounts.models import User
from diary.models import Case, Note, NoteLink
from diary.tests.test_wordexport_db import PASSWORD, ExportCase, add_item
from diary.wordexport import offline, service
from diary.wordexport import model as m

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


class OfflineCopyTests(ExportCase):
    def url(self, **params):
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{reverse('export_download')}?{query}"

    def get(self, user, **params):
        return self.login(user).get(self.url(**params))

    def html(self, user=None, **params):
        resp = self.get(user or self.editor, **(params or {"type": "offline", "review": 1}))
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode("utf-8")

    def test_every_member_may_download_it_and_a_stranger_may_not(self):
        for user in (self.editor, self.reader, self.admin):
            resp = self.get(user, type="offline", review=1)
            self.assertEqual(resp.status_code, 200, user.username)
            self.assertTrue(resp["Content-Type"].startswith("text/html"))
            self.assertTrue(resp["Content-Disposition"].startswith("attachment"))
            self.assertRegex(resp["Content-Disposition"], r'filename="Case Law Diary Main Offline copy \d{4}-\d{2}-\d{2}\.html"')
        nobody = User.objects.create_user("nobody", password=PASSWORD)
        self.assertEqual(self.login(nobody).get(self.url(type="offline")).status_code, 403)
        self.assertEqual(Client().get(self.url(type="offline")).status_code, 302)

    def test_it_holds_the_live_diary_only_and_numbers_like_the_site(self):
        body = self.html()
        for text in ("Arbitration", "Contracts", "Stamp Act", "Arbitrability", "Fraud", "Duty", "Prop one", "After section",
                     "Fraud item", "Direct item", "Ex Parte", "(2020) 1 SCC 1"):
            self.assertIn(text, body)
        for text in ("TRASHED ITEM", "Gone Topic", "(2000) 9 SCC 9"):
            self.assertNotIn(text, body)
        self.assertIn("Other Subjects", body)
        self.assertIn("[Pending: check]", body)
        self.assertIn('id="item-%d"' % self.first.pk, body)
        self.assertIn('id="topic-%d"' % self.topic.pk, body)
        self.assertRegex(body, r'<span class="num">A\.</span> Arbitrability')

    def test_flags_follow_the_checkbox(self):
        self.assertNotIn("[Pending: check]", self.html(type="offline", review=0))

    def test_it_is_self_contained_and_cannot_edit(self):
        body = self.html()
        self.assertNotRegex(body, r'(src|href)="https?://')
        self.assertNotRegex(body, r"<link\b")
        self.assertNotRegex(body, r"<form[^>]*method=\"post\"")
        self.assertNotIn("csrf", body.lower())
        self.assertNotIn("data-edit-row", body)
        self.assertEqual(body.count("<script"), 1)
        self.assertEqual(body.count("<script"), body.count("</script>"))
        self.assertIn('id="q"', body)  # the search box
        self.assertIn("<style>", body)

    def test_citation_hyperlinks_and_see_also_links(self):
        case = Case.objects.get(item=self.first)
        case.url = "https://example.org/case?a=1&b=2"
        case.save()
        bad = Case.objects.get(item=self.after)
        bad.url = "javascript:alert(1)"
        bad.save()
        note = Note.objects.create(profile=self.profile, item=self.first, text="<p>Look</p>")
        NoteLink.objects.create(profile=self.profile, note=note, item=self.in_fraud, position=1)
        body = self.html()
        self.assertIn('href="https://example.org/case?a=1&amp;b=2"', body)
        self.assertNotIn("javascript:", body)
        self.assertIn('href="#item-%d"' % self.in_fraud.pk, body)

    def test_text_is_escaped(self):
        add_item(self.profile, ("subject", self.con), "<script>alert(1)</script> & co", "A <b>v</b> B", 5)
        body = self.html()
        self.assertEqual(body.count("<script"), 1)
        self.assertIn("A &lt;b&gt;v&lt;/b&gt; B", body)

    def test_parts_can_be_made_too(self):
        sub = self.html(type="offline_subject", subject_pk=self.con.pk)
        self.assertIn("Contract item", sub)
        self.assertNotIn("Prop one", sub)
        top = self.html(self.reader, type="offline_view", kind="topic", pk=self.topic.pk, review=1)
        self.assertIn("Prop one", top)
        self.assertIn("Fraud item", top)
        self.assertNotIn("Contract item", top)
        self.assertIn("On screen: Arbitration &gt; Arbitrability", top)
        subtopic = self.html(type="offline_view", kind="subtopic", pk=self.duty.pk)
        self.assertIn("Duty item", subtopic)
        self.assertNotIn("Direct item", subtopic)
        self.assertEqual(self.get(self.editor, type="offline_view", kind="topic", pk=999999).status_code, 404)
        self.assertEqual(self.get(self.editor, type="offline_subject", subject_pk=999999).status_code, 404)

    def test_another_profiles_part_is_not_found(self):
        from diary.models import Subject

        foreign = Subject.objects.create(profile=self.other_profile, name="Secret", position=1)
        self.assertEqual(self.get(self.editor, type="offline_subject", subject_pk=foreign.pk).status_code, 404)
        self.assertNotIn("Secret", self.html())

    def test_service_counts_items_and_names_the_file(self):
        result = service.offline_copy(self.profile, self.editor, True, now=NOW)
        self.assertEqual(result.items, 6)
        self.assertEqual(result.name, "Case Law Diary Main Offline copy 2026-11-01.html")
        part = service.offline_copy(self.profile, self.editor, True, "subject", self.arb.pk, now=NOW)
        self.assertEqual(part.name, "Case Law Diary Main Arbitration, Offline copy 2026-11-01.html")

    def test_the_page_describes_it_and_the_email_backups_do_not_include_it(self):
        body = self.login(self.reader).get(reverse("export")).content.decode()
        self.assertIn("Download the Offline copy", body)
        self.assertIn("not part of the scheduled email backups", body)
        import pathlib

        mailer = pathlib.Path(__file__).resolve().parents[2] / "mailer"
        for path in mailer.rglob("*.py"):
            if "tests" not in path.parts:
                self.assertNotIn("offline", path.read_text(encoding="utf-8").lower(), path.name)


class OfflineBuilderTests(ExportCase):
    """The pure builder, without the views."""

    def fmts(self):
        return service.user_options(None)[0]

    def test_a_search_index_row_for_every_item_and_heading(self):
        data = m.ExportInput(title="T", part="P", date_text="d", fmts=self.fmts(), include_review=True,
                             main=[m.XSubject("S", m.XContainer([m.XItem(html="<p>Hello</p>", pk=7)]), pk=3)])
        html = offline.build_html(data)
        self.assertIn('id="item-7" data-find', html)
        self.assertIn('id="subject-3"', html)
        self.assertEqual(len(re.findall(r'id="results"', html)), 1)
        self.assertIn("1 Item.", html)

    def test_an_empty_diary_still_makes_a_page(self):
        data = m.ExportInput(title="T", part="P", date_text="d", fmts=self.fmts())
        self.assertIn("There are no Subjects yet.", offline.build_html(data))
