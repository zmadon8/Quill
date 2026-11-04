"""Item editor and review marker switch (Milestone 3c); citation order and layout (round 10)."""
from django.test import Client, override_settings
from django.urls import reverse

from diary import services as svc
from diary.models import Case, Item
from diary.tests.test_views_edit import EditViewTestCase


@override_settings(SECURE_SSL_REDIRECT=False)
class ItemEditorTestCase(EditViewTestCase):
    def editor_url(self, item):
        return reverse("edit_item", args=[item.pk])

    def save(self, item, client=None, **fields):
        """POST the editor form for ``item`` as it is now, with ``fields`` changed."""
        current = self.get(item)
        data = {"version": current.version, "text": current.text, "citation": current.citation,
                "flag": current.flag, "flag_text": current.flag_text, "next": self.next}
        data.update(fields)
        return (client or self.client).post(self.editor_url(item), data)

    def cited(self, comments=("<b>note</b>", "")):
        """An Item with two citations (Cases), each with an optional comment."""
        item = self.make("item", ("topic", self.topic.pk), text="m")
        first = self.make("case", ("item", item.pk), citation="A v B", comment=comments[0])
        second = self.make("case", ("item", item.pk), citation="C v D", comment=comments[1])
        return item, first, second

    def case_rows(self, rows):
        """Form fields for Cases: rows are (case or None, citation, comment)."""
        return {
            "case_id": [c.pk if c else "" for c, _, _ in rows],
            "case_version": [self.get(c).version if c else "" for c, _, _ in rows],
            "case_citation": [cite for _, cite, _ in rows],
            "case_comment": [comment for _, _, comment in rows],
        }

    def live_cases(self, item):
        rows = Case._base_manager.filter(item=item, deleted_at__isnull=True).order_by("position", "pk")
        return [(c.citation, c.comment) for c in rows]


class EditorAccessTests(ItemEditorTestCase):
    def test_readers_get_403_everywhere(self):
        item = self.get(self.one)
        for name, args in (("edit_item", [item.pk]),):
            url = reverse(name, args=args)
            self.assertEqual(self.reader_client.get(url).status_code, 403, name)
            resp = self.reader_client.post(url, {"kind": "item", "id": item.pk, "version": item.version, "set": "1",
                                                 "text": "hacked", "next": self.next})
            self.assertEqual(resp.status_code, 403, name)
        resp = self.save(self.one, client=self.reader_client, text="<p>hacked</p>")
        self.assertEqual(resp.status_code, 403)
        after = self.get(self.one)
        self.assertEqual((after.text, after.version, after.flag, after.kind), (item.text, item.version, "none", "plain"))

    def test_another_profiles_item_is_404_everywhere(self):
        subject = self.make("subject", profile=self.other_profile, name="Foreign")
        topic = self.make("topic", ("subject", subject.pk), profile=self.other_profile, name="T")
        foreign = self.make("item", ("topic", topic.pk), profile=self.other_profile, text="secret")
        self.assertEqual(self.client.get(self.editor_url(foreign)).status_code, 404)
        self.assertEqual(self.save(foreign, text="<p>x</p>").status_code, 404)
        foreign = self.get(foreign)
        self.assertEqual((foreign.text, foreign.version, foreign.flag), ("secret", 1, "none"))

    def test_unknown_and_trashed_items_are_404(self):
        self.assertEqual(self.client.get(reverse("edit_item", args=[999999])).status_code, 404)
        svc.delete(self.profile, self.user, "item", self.one.pk)
        self.assertEqual(self.client.get(self.editor_url(self.one)).status_code, 404)
        self.assertEqual(self.save(self.one, text="<p>x</p>").status_code, 404)

    def test_csrf_token_is_required_to_save_or_mark(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        self.assertEqual(strict.post(self.editor_url(self.one), {"text": "x"}).status_code, 403)
        self.assertEqual(self.get(self.one).version, 1)

    def test_the_for_review_switch_address_is_gone(self):
        # D88: For review was merged into the Flags; the one-click switch went with it.
        self.assertEqual(self.client.post("/caselaw/edit/review/", {"kind": "item", "id": self.one.pk, "set": "1"}).status_code, 404)


class EditorPageTests(ItemEditorTestCase):
    def test_the_editor_shows_the_fields_and_the_record_info(self):
        resp = self.client.get(self.editor_url(self.one), {"next": self.next})
        self.assertEqual(resp.status_code, 200)
        for needle in ("Edit Item", 'name="text"', 'name="case_citation"', 'name="flag"', 'name="flag_text"',
                       "data-flag-select", 'value="pending"', "data-richtext", "richtext-editor.js",
                       "IST by editor", "data-case-list", "Add a citation"):
            self.assertContains(resp, needle)
        self.assertNotContains(resp, "Multi-Item")
        self.assertNotContains(resp, 'id="id-citation"')
        self.assertContains(resp, 'name="version" value="%d"' % self.get(self.one).version)
        self.assertContains(resp, 'name="next" value="%s"' % self.next)
        self.assertNotContains(resp, "Change to")
        self.assertNotContains(resp, "Nested")
        self.assertNotContains(resp, "Original Word line")

    def test_an_imported_item_shows_its_original_word_line_read_only(self):
        Item.objects.filter(pk=self.one.pk).update(original_line="(1) The original Word line")
        resp = self.client.get(self.editor_url(self.one))
        self.assertContains(resp, "Original Word line")
        self.assertContains(resp, "(1) The original Word line")
        self.assertNotContains(resp, 'name="original_line"')

    def test_an_item_with_citations_lists_them_in_order(self):
        item, _, _ = self.cited()
        resp = self.client.get(self.editor_url(item))
        self.assertContains(resp, "data-case-list")
        self.assertContains(resp, 'name="case_citation" value="A v B"')
        self.assertContains(resp, 'name="case_citation" value="C v D"')
        self.assertContains(resp, "Citation 1")
        self.assertContains(resp, "Citation 2")
        self.assertNotContains(resp, 'name="citation"')

    def test_an_item_without_a_citation_still_shows_the_first_citation_box(self):
        resp = self.client.get(self.editor_url(self.one))
        self.assertContains(resp, 'name="case_citation" value=""')
        self.assertContains(resp, 'data-case-row', count=2)  # the one shown and the template for new ones
        self.assertContains(resp, "Citation 1")

    def test_show_citations_control_is_there_only_with_more_than_one_citation(self):
        item, _, _ = self.cited()
        shown = self.client.get(self.editor_url(item)).content.decode()
        self.assertIn('name="citation_layout" value="inline" checked', shown)
        self.assertIn('name="citation_layout" value="lines"', shown)
        self.assertNotIn("data-layout-control hidden", shown)
        single = self.client.get(self.editor_url(self.one)).content.decode()
        self.assertIn("data-layout-control hidden", single)

    def test_the_reading_view_links_to_the_editor_only_in_edit_mode(self):
        url = reverse("read_subject", args=[self.subject.pk])
        self.assertContains(self.client.get(url + "?edit=1"), self.editor_url(self.one))
        self.assertNotContains(self.client.get(url), self.editor_url(self.one))
        self.assertNotContains(self.reader_client.get(url + "?edit=1"), self.editor_url(self.one))


class SaveTests(ItemEditorTestCase):
    def test_bold_and_italic_are_saved_as_clean_html(self):
        before = self.get(self.one).version
        resp = self.save(self.one, text="<p><strong>Hi</strong> <em>there</em><script>alert(1)</script><span onclick='x()'>y</span></p>")
        self.assertRedirects(resp, self.next, fetch_redirect_response=False)
        item = self.get(self.one)
        self.assertEqual(item.text, "<p><b>Hi</b> <i>there</i>y</p>")
        self.assertEqual(item.text_plain, "Hi therey")
        self.assertEqual(item.version, before + 1)
        self.assertEqual(item.updated_by, self.user)

    def test_underline_and_line_breaks_stay(self):
        self.save(self.one, text="<p><u>under</u><br>line</p><p>two</p>")
        self.assertEqual(self.get(self.one).text, "<p><u>under</u><br>line</p><p>two</p>")

    def test_citation_is_one_line_and_becomes_case_a(self):
        self.save(self.one, **self.case_rows([(None, "  AIR 1950\n SC   27  ", "")]))
        self.assertEqual(self.get(self.one).citation, "")
        self.assertEqual(self.live_cases(self.one), [("AIR 1950 SC 27", "")])
        self.assertEqual(self.get(self.one).kind, "plain")

    def test_the_citation_layout_is_saved_and_a_bad_value_is_ignored(self):
        item, first, second = self.cited()
        self.assertEqual(self.get(item).citation_layout, "inline")
        self.save(item, citation_layout="lines", **self.case_rows([(first, "A v B", "<b>note</b>"), (second, "C v D", "")]))
        self.assertEqual(self.get(item).citation_layout, "lines")
        self.save(item, citation_layout="bogus")
        self.assertEqual(self.get(item).citation_layout, "lines")
        self.save(item, citation_layout="inline")
        self.assertEqual(self.get(item).citation_layout, "inline")

    def test_flag_and_its_text_are_saved_and_cleared(self):
        self.save(self.one, flag="overruled", flag_text="Overruled by X v Y")
        item = self.get(self.one)
        self.assertEqual((item.flag, item.flag_text), ("overruled", "Overruled by X v Y"))
        self.save(self.one, flag="none", flag_text="left over")
        item = self.get(self.one)
        self.assertEqual((item.flag, item.flag_text), ("none", ""))

    def test_pending_takes_text_and_the_old_review_fields_are_ignored(self):
        # D88: Pending sits after None; every flag but None takes text; For review is gone (posting it changes nothing).
        self.save(self.one, flag="pending", flag_text="  check   the year ", needs_review="1", review_note="ignored")
        item = self.get(self.one)
        self.assertEqual((item.flag, item.flag_text, item.needs_review, item.review_note), ("pending", "check the year", False, ""))
        page = self.client.get(self.editor_url(self.one)).content.decode()
        self.assertLess(page.index('value="none"'), page.index('value="pending"'))
        self.assertLess(page.index('value="pending"'), page.index('value="overruled"'))
        self.assertNotIn('name="needs_review"', page)

    def test_saving_without_changes_writes_no_new_version(self):
        before = self.get(self.one).version
        self.save(self.one)
        self.assertEqual(self.get(self.one).version, before)

    def test_a_bad_value_shows_the_form_again_with_what_was_typed(self):
        resp = self.save(self.one, flag="bogus", text="<p>keep me</p>")
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "is not a flag choice", status_code=400)
        self.assertContains(resp, "keep me", status_code=400)
        self.assertEqual(self.get(self.one).text, "one")

    def test_a_too_long_citation_is_refused_and_nothing_is_saved(self):
        resp = self.save(self.one, text="<p>changed</p>", **self.case_rows([(None, "x" * 1001, "")]))
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "too long", status_code=400)
        self.assertEqual(self.get(self.one).text, "one")
        self.assertEqual(self.live_cases(self.one), [])

    def test_a_too_long_flag_text_is_refused(self):
        resp = self.save(self.one, flag="other", flag_text="x" * 2001)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.get(self.one).flag, "none")

    def test_next_must_stay_on_this_site(self):
        resp = self.save(self.one, text="<p>x</p>", next="https://evil.example/")
        expected = reverse("read_subject", args=[self.subject.pk]) + "?edit=1#n-item-%d" % self.one.pk
        self.assertRedirects(resp, expected, fetch_redirect_response=False)


class StaleSaveTests(ItemEditorTestCase):
    def test_a_stale_save_shows_the_conflict_page_and_keeps_what_was_typed(self):
        opened = self.get(self.one).version
        svc.edit(self.profile, self.user2, "item", self.one.pk, {"text": "<p>theirs</p>"})
        resp = self.client.post(self.editor_url(self.one), {
            "version": opened, "text": "<p>My typed words</p>", "flag": "none",
            "flag_text": "", "next": self.next, **self.case_rows([(None, "My citation", "")])})
        self.assertEqual(resp.status_code, 409)
        self.assertContains(resp, "has changed", status_code=409)
        self.assertContains(resp, "My typed words", status_code=409)
        self.assertContains(resp, "My citation", status_code=409)
        item = self.get(self.one)
        self.assertEqual((item.text, item.citation, item.version), ("<p>theirs</p>", "", opened + 1))
        self.assertEqual(self.live_cases(self.one), [])

    def test_a_stale_case_rolls_back_the_whole_save(self):
        multi, first, second = self.cited()
        rows = self.case_rows([(first, "A v B", ""), (second, "C v D", "")])
        svc.edit(self.profile, self.user2, "case", first.pk, {"citation": "Changed"})
        resp = self.client.post(self.editor_url(multi), {
            "version": self.get(multi).version, "text": "<p>new text</p>", "flag": "none", "next": self.next, **rows})
        self.assertEqual(resp.status_code, 409)
        self.assertContains(resp, "new text", status_code=409)
        self.assertEqual(self.get(multi).text, "m")
        self.assertEqual(self.live_cases(multi), [("Changed", "<b>note</b>"), ("C v D", "")])


class CaseTests(ItemEditorTestCase):
    def post_cases(self, multi, rows, **extra):
        data = {"version": self.get(multi).version, "text": multi.text, "flag": "none", "next": self.next}
        data.update(self.case_rows(rows))
        data.update(extra)
        return self.client.post(self.editor_url(multi), data)

    def test_edit_a_case_citation_and_comment(self):
        multi, first, second = self.cited()
        resp = self.post_cases(multi, [(first, "E v F", "<p><em>why</em><script>x</script></p>"), (second, "C v D", "")])
        self.assertRedirects(resp, self.next, fetch_redirect_response=False)
        self.assertEqual(self.live_cases(multi), [("E v F", "<p><i>why</i></p>"), ("C v D", "")])

    def test_add_a_case(self):
        multi, first, second = self.cited()
        self.post_cases(multi, [(first, "A v B", "<b>note</b>"), (second, "C v D", ""), (None, "G v H", "<p>new</p>"),
                                (None, "", "  ")])
        self.assertEqual(self.live_cases(multi), [("A v B", "<b>note</b>"), ("C v D", ""), ("G v H", "<p>new</p>")])

    def test_delete_a_case_moves_it_to_the_trash(self):
        multi, first, second = self.cited()
        self.post_cases(multi, [(first, "A v B", "<b>note</b>")], case_gone="%d:%d" % (second.pk, self.get(second).version))
        self.assertEqual(self.live_cases(multi), [("A v B", "<b>note</b>")])
        self.assertIsNotNone(self.get(second).deleted_at)

    def test_reorder_cases(self):
        multi, first, second = self.cited()
        self.post_cases(multi, [(second, "C v D", ""), (first, "A v B", "<b>note</b>")])
        self.assertEqual(self.live_cases(multi), [("C v D", ""), ("A v B", "<b>note</b>")])
        self.assertEqual((self.get(second).position, self.get(first).position), (1, 2))

    def test_add_delete_and_reorder_in_one_save(self):
        multi, first, second = self.cited()
        self.post_cases(multi, [(None, "N v O", ""), (second, "C v D", "")])
        self.assertEqual(self.live_cases(multi), [("N v O", ""), ("C v D", "")])
        self.assertIsNotNone(self.get(first).deleted_at)

    def test_an_item_with_cases_keeps_no_citation_of_its_own(self):
        multi, first, second = self.cited()
        resp = self.post_cases(multi, [(first, "A v B", "<b>note</b>"), (second, "C v D", "")], citation="Ignored")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.get(multi).citation, "")

    def test_a_case_of_another_item_is_404(self):
        multi, first, _ = self.cited()
        other, other_case, _ = self.cited()
        resp = self.post_cases(multi, [(other_case, "A v B", "")])
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(self.get(other_case).item_id, other.pk)
        self.assertIsNone(self.get(first).deleted_at)

    def test_the_first_citation_of_an_item_without_any_is_case_a(self):
        resp = self.post_cases(self.one, [(None, "X v Y", "")])
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.live_cases(self.one), [("X v Y", "")])
        self.assertEqual(Case.objects.get(item=self.one).position, 1)

    def test_one_save_is_one_undo_step_for_the_item_and_its_citations(self):
        item, first, second = self.cited()
        before = len(self.history(first))
        self.post_cases(item, [(first, "E v F", "<b>note</b>"), (second, "C v D", ""), (None, "G v H", "")],
                        text="<p>new text</p>")
        edited = self.history(item)[-1]
        self.assertEqual(self.history(first)[-1].group, edited.group)
        self.assertEqual(len(self.history(first)), before + 1)
        made = Case.objects.get(item=item, citation="G v H")
        self.assertEqual(self.history(made)[0].group, edited.group)

    def test_a_citation_with_a_comment_only_is_kept(self):
        item, first, second = self.cited()
        self.post_cases(item, [(first, "", "<b>note</b>"), (second, "C v D", "")])
        self.assertEqual(self.live_cases(item), [("", "<b>note</b>"), ("C v D", "")])

    def test_emptying_both_boxes_of_a_saved_citation_moves_it_to_the_trash(self):
        item, first, second = self.cited()
        self.post_cases(item, [(first, "", ""), (second, "C v D", "")])
        self.assertEqual(self.live_cases(item), [("C v D", "")])
        self.assertIsNotNone(self.get(first).deleted_at)
        self.assertIsNotNone(self.get(first).delete_batch)

    def test_a_save_without_the_citations_list_leaves_the_citations_alone(self):
        item, first, second = self.cited()
        resp = self.client.post(self.editor_url(item), {
            "version": self.get(item).version, "text": "<p>only text</p>", "flag": "none", "next": self.next})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.live_cases(item), [("A v B", "<b>note</b>"), ("C v D", "")])


class FlagShownTests(ItemEditorTestCase):
    def test_the_flag_is_in_the_editing_card_and_shows_on_the_reading_row(self):
        url = reverse("read_subject", args=[self.subject.pk])
        editing = self.client.get(url + "?edit=1")
        self.assertContains(editing, "data-edit-open")
        self.assertNotContains(editing, "Mark for review")
        self.assertNotContains(self.reader_client.get(url + "?edit=1"), "data-edit-open")
        card = self.client.get(reverse("edit_inline_card"), {"kind": "item", "id": self.one.pk}).json()["html"]
        self.assertIn("data-flag-select", card)
        self.assertNotIn('name="needs_review"', card)
        self.save(self.one, flag="pending", flag_text="ask the client")
        self.assertContains(self.client.get(url), "[Pending: ask the client]")
        self.save(self.one, flag="other", flag_text="see the appeal")
        self.assertContains(self.client.get(url), "[see the appeal]")
        self.assertNotContains(self.client.get(url), "For review")
