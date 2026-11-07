"""Round 16 (D87): a hyperlink on each citation, kept exactly as typed; the header switch; keep my place."""
from pathlib import Path

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from diary import services as svc
from diary.models import Case
from diary.services.records import clean_url
from diary.tests.test_views_item_editor import ItemEditorTestCase

EXACT = "https://www.SCConline.com/Members/SearchResult.aspx?Doc=%2F2016%2F10%2FSCC%2F386&Ref=AbC#Para_12"
ROOT = Path(__file__).resolve().parents[2]


class CleanUrlTests(SimpleTestCase):
    def test_kept_exactly_as_typed_apart_from_outer_spaces(self):
        self.assertEqual(clean_url(EXACT), EXACT)
        self.assertEqual(clean_url("  " + EXACT + "  "), EXACT)
        self.assertEqual(clean_url("HTTP://Example.COM/Path?Q=A"), "HTTP://Example.COM/Path?Q=A")
        self.assertEqual(clean_url(""), "")
        self.assertEqual(clean_url("   "), "")

    def test_only_web_addresses_are_accepted(self):
        for bad in ("javascript:alert(1)", "www.example.com", "ftp://example.com/x", "data:text/html,x",
                    "https://exa mple.com", "https://a.com/\nb", "https://" + "a" * 2000):
            with self.assertRaises(svc.ValidationFailed, msg=bad):
                clean_url(bad)


@override_settings(SECURE_SSL_REDIRECT=False)
class HyperlinkEditingTests(ItemEditorTestCase):
    def rows_with_urls(self, rows):
        """rows are (case or None, citation, comment, url)."""
        data = self.case_rows([(c, cite, comment) for c, cite, comment, _ in rows])
        data["case_url"] = [url for _, _, _, url in rows]
        return data

    def test_the_item_editor_saves_the_address_exactly(self):
        item, first, second = self.cited()
        self.save(item, **self.rows_with_urls([(first, "A v B", "<b>note</b>", "  " + EXACT + " "), (second, "C v D", "", "")]))
        self.assertEqual(self.get(first).url, EXACT)
        self.assertEqual(self.get(second).url, "")
        page = self.client.get(self.editor_url(item)).content.decode()
        self.assertIn('name="case_url"', page)
        self.assertIn('value="%s"' % EXACT.replace("&", "&amp;"), page)

    def test_a_page_without_the_address_field_leaves_addresses_alone(self):
        item, first, second = self.cited()
        Case.objects.filter(pk=first.pk).update(url=EXACT)
        self.save(item, **self.case_rows([(first, "A v B (2)", "<b>note</b>"), (second, "C v D", "")]))
        self.assertEqual((self.get(first).citation, self.get(first).url), ("A v B (2)", EXACT))

    def test_a_bad_address_is_refused_and_nothing_is_saved(self):
        item, first, second = self.cited()
        resp = self.save(item, text="<p>changed</p>",
                         **self.rows_with_urls([(first, "A v B", "<b>note</b>", "javascript:alert(1)"), (second, "C v D", "", "")]))
        self.assertEqual(resp.status_code, 400)  # the editor is shown again with the message and what was typed
        self.assertContains(resp, "must start with https://", status_code=400)
        self.assertContains(resp, 'value="javascript:alert(1)"', status_code=400)
        self.assertEqual(self.get(first).url, "")
        self.assertNotEqual(self.get(item).text, "<p>changed</p>")

    def test_a_new_citation_with_only_an_address_is_kept(self):
        item, first, second = self.cited()
        self.save(item, **self.rows_with_urls([(first, "A v B", "<b>note</b>", ""), (second, "C v D", "", ""),
                                               (None, "", "", EXACT)]))
        self.assertEqual(Case._base_manager.filter(item=item, deleted_at__isnull=True, url=EXACT).count(), 1)

    def test_the_reading_view_links_the_citation_and_the_bar_has_the_switch(self):
        item, first, second = self.cited()
        Case.objects.filter(pk=first.pk).update(url=EXACT)
        html = self.client.get(reverse("read_topic", args=[self.topic.pk])).content.decode()
        self.assertIn('<a class="cite-link" href="%s" target="_blank" rel="noopener noreferrer"' % EXACT.replace("&", "&amp;"), html)
        self.assertIn("C v D", html)
        self.assertEqual(html.count('class="cite-link"'), 1)  # the citation without an address is plain text
        self.assertIn('data-links-toggle', html)
        self.assertIn('role="switch"', html)
        self.assertIn('localStorage.getItem("quill.links")', html)  # applied before the page is drawn: no reload
        self.assertIn("js/keep-place.js", html)

    def test_the_links_toggle_sits_on_the_edit_bar_left_of_edit_for_an_editor(self):
        # The toggle moved from the header onto the same bar as Edit, just to its left.
        html = self.client.get(reverse("read_topic", args=[self.topic.pk]) + "?edit=1").content.decode()
        self.assertIn('data-bar-tools', html)
        self.assertIn('data-links-toggle', html)
        self.assertIn('data-edit-switch', html)
        self.assertLess(html.index('data-links-toggle'), html.index('data-edit-switch'))  # Links is left of Edit

    def test_a_reader_still_gets_the_links_toggle_on_a_reading_page(self):
        # Readers have no Edit button, but the Links toggle still works for them on reading pages.
        html = self.reader_client.get(reverse("read_topic", args=[self.topic.pk])).content.decode()
        self.assertIn('data-bar-tools', html)
        self.assertIn('data-links-toggle', html)
        self.assertNotIn('data-edit-switch', html)

    def test_history_and_undo_carry_the_address(self):
        item, first, second = self.cited()
        result = svc.edit(self.profile, self.user, "case", first.pk, {"url": EXACT})
        self.assertEqual(self.get(first).url, EXACT)
        svc.undo_group(self.profile, self.user, result.group)
        self.assertEqual(self.get(first).url, "")


class ScriptTests(SimpleTestCase):
    def test_the_switch_never_reloads_and_the_place_is_kept(self):
        site = (ROOT / "static" / "js" / "site.js").read_text()
        block = site[site.index("data-links-toggle"):]
        self.assertNotIn("location.reload", block)
        self.assertNotIn("location.assign", block)
        keep = (ROOT / "static" / "js" / "keep-place.js").read_text()
        for needed in ('"reload"', '"back_forward"', "scrollRestoration", "sessionStorage", '"submit"', "pagehide"):
            self.assertIn(needed, keep, needed)
        self.assertIn("quillKeepPlace.restoring", site)  # the #entry jump does not fight a restore
