"""Notes and cross-references in the views (Milestone 5): add, the Note editor, links, picker, display at both ends,
Trash, permanent delete refusal, Reader 403."""
from django.test import override_settings
from django.urls import reverse

from diary import services as svc
from diary.models import Note, NoteLink
from diary.services.links import link_target
from diary.tests.test_views_trash_history import TrashTestCase
from diary.undo_session import SESSION_KEY

FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


@override_settings(SECURE_SSL_REDIRECT=False)
class NoteViewCase(TrashTestCase):
    def setUp(self):
        super().setUp()
        self.note = self.make("note", ("topic", self.topic.pk), text="<p>Remember</p>")
        self.page = reverse("read_subject", args=[self.subject.pk])

    def link(self, kind, obj, note=None):
        return svc.add_link(self.profile, self.user, (note or self.note).pk, (kind, obj.pk)).record

    def targets(self, note=None):
        rows = NoteLink.objects.filter(note=note or self.note, deleted_at__isnull=True).order_by("position", "pk")
        return [link_target(row) for row in rows]

    def read(self, client=None, edit=False):
        resp = (client or self.client).get(self.page + ("?edit=1" if edit else ""))
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def link_post(self, op, client=None, **data):
        data = {"op": op, "note": self.note.pk, "next": self.next, **data}
        return (client or self.client).post(reverse("edit_note_link"), data)


class AccessTests(NoteViewCase):
    def test_readers_get_403_on_every_note_address(self):
        link = self.link("item", self.one)
        calls = [
            ("get", reverse("edit_note", args=[self.note.pk]), {}),
            ("post", reverse("edit_note", args=[self.note.pk]), {"text": "x", "version": 1}),
            ("post", reverse("edit_note_link"), {"op": "add", "note": self.note.pk, "target": f"item:{self.two.pk}"}),
            ("post", reverse("edit_note_link"), {"op": f"remove:{link.pk}", "note": self.note.pk}),
            ("post", reverse("edit_note_link"), {"op": "purge", "link": link.pk}),
            ("get", reverse("edit_note_pick"), {"purpose": "link", "note": self.note.pk}),
            ("post", reverse("edit_note_pick"), {"purpose": "link", "note": self.note.pk}),
            ("post", reverse("edit_add"), {"what": "note", "parent_type": "topic", "parent_id": self.topic.pk, "text": "x"}),
            ("post", reverse("edit_delete"), {"kind": "note", "id": self.note.pk, "confirmed": "1"}),
            ("post", reverse("edit_move"), {"kind": "note", "id": self.note.pk, "direction": "down"}),
        ]
        for method, url, data in calls:
            resp = getattr(self.reader_client, method)(url, data)
            self.assertEqual(resp.status_code, 403, url)
        self.assertEqual(self.targets(), [("item", self.one.pk)])
        self.assertEqual(Note.objects.count(), 1)
        self.assertEqual(self.get(self.note).text, "<p>Remember</p>")

    def test_another_profiles_note_is_404(self):
        subject = self.make("subject", profile=self.other_profile, name="Elsewhere")
        foreign = self.make("note", ("subject", subject.pk), profile=self.other_profile, text="x")
        self.assertEqual(self.client.get(reverse("edit_note", args=[foreign.pk])).status_code, 404)
        self.assertEqual(self.link_post("add", note=foreign.pk, target=f"item:{self.one.pk}").status_code, 404)

    def test_a_target_in_another_profile_is_404_and_nothing_is_linked(self):
        subject = self.make("subject", profile=self.other_profile, name="Elsewhere")
        resp = self.link_post("add", target=f"subject:{subject.pk}")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(NoteLink.objects.count(), 0)

    def test_unknown_targets_and_ops_are_404(self):
        for data in ({"op": "add", "target": "note:1"}, {"op": "add", "target": "item:x"}, {"op": "bogus:1"}, {"op": "up"}):
            self.assertEqual(self.link_post(**data).status_code, 404, data)

    def test_the_picker_rejects_bad_requests(self):
        url = reverse("edit_note_pick")
        for params in ({}, {"purpose": "bogus"}, {"purpose": "link"}, {"purpose": "link", "note": "x"},
                       {"purpose": "retarget", "link": "999999"},
                       {"purpose": "link", "note": self.note.pk, "at": "note:1"},
                       {"purpose": "link", "note": self.note.pk, "at": "item:999999"}):
            self.assertEqual(self.client.get(url, params).status_code, 404, params)


class AddNoteTests(NoteViewCase):
    def add(self, ref, obj, text="<p>typed</p>", **extra):
        data = {"ref": ref, "choice": "inside:note", "after_version": self.get(obj).version, "next": self.next,
                "text": text, "text_format": "html", **extra}
        return self.client.post(reverse("edit_add"), data, **FETCH)

    def test_add_note_on_a_subject_topic_subtopic_section_and_item(self):
        sub = self.make("subtopic", ("topic", self.topic.pk), name="Offer")
        for kind, obj in (("subject", self.subject), ("topic", self.topic), ("subtopic", sub), ("section", self.sec),
                          ("item", self.one)):
            resp = self.add(f"{kind}:{obj.pk}", obj, text=f"<p>on {kind}</p>")
            self.assertEqual(resp.status_code, 200, kind)
            self.assertTrue(resp.json()["ok"])
            note = Note.objects.get(text_plain=f"on {kind}")
            self.assertEqual(getattr(note, f"{kind}_id"), obj.pk)

    def test_a_note_on_a_nested_item_child_and_a_nested_item(self):
        nested = self.make("item", ("topic", self.topic.pk), kind="nested", text="group")
        child = self.make("item", ("item", nested.pk), text="child")
        self.assertEqual(self.add(f"item:{nested.pk}", nested, text="<p>n1</p>").status_code, 200)
        self.assertEqual(self.add(f"item:{child.pk}", child, text="<p>n2</p>").status_code, 200)
        self.assertEqual(Note.objects.get(text_plain="n1").item_id, nested.pk)
        self.assertEqual(Note.objects.get(text_plain="n2").item_id, child.pk)

    def test_new_notes_go_last_among_the_notes_of_their_parent(self):
        self.add(f"topic:{self.topic.pk}", self.topic, text="<p>second</p>")
        second = Note.objects.get(text_plain="second")
        self.assertEqual((self.get(self.note).position, second.position), (1, 2))

    def test_an_empty_note_is_refused(self):
        resp = self.add(f"topic:{self.topic.pk}", self.topic, text="")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Note.objects.count(), 1)

    def test_the_add_form_offers_note_everywhere(self):
        for ref in (f"subject:{self.subject.pk}", f"topic:{self.topic.pk}", f"item:{self.one.pk}", f"section:{self.sec.pk}"):
            body = self.client.get(reverse("edit_inline_add"), {"ref": ref, "next": self.next}).json()
            self.assertIn(("inside:note", "Note"), [(c["value"], c["label"]) for c in body["choices"]], ref)

    def test_without_javascript_a_note_is_added_then_the_editor_opens(self):
        resp = self.client.post(reverse("edit_add"), {"what": "note", "parent_type": "item", "parent_id": self.one.pk,
                                                       "text": "plain typed", "next": self.next})
        note = Note.objects.get(text_plain="plain typed")
        self.assertEqual(note.item_id, self.one.pk)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith(reverse("edit_note", args=[note.pk])))

    def test_the_add_page_offers_note(self):
        resp = self.client.get(reverse("edit_add"), {"parent": f"section:{self.sec.pk}", "next": self.next})
        self.assertContains(resp, '<option value="note">Note</option>', html=False)


class EditorTests(NoteViewCase):
    def url(self):
        return reverse("edit_note", args=[self.note.pk])

    def test_the_editor_shows_text_links_and_more(self):
        self.link("item", self.one)
        self.link("section", self.sec)
        resp = self.client.get(self.url(), {"next": self.next})
        self.assertContains(resp, "Remember")
        self.assertContains(resp, "Add a link")
        self.assertContains(resp, "Move to")
        self.assertContains(resp, "History")
        self.assertContains(resp, "Delete")
        self.assertContains(resp, "Move this link up", count=2)
        self.assertContains(resp, "Remove this link", count=2)
        self.assertContains(resp, 'name="csrfmiddlewaretoken"')
        self.assertEqual(len(resp.context["links"]), 2)

    def test_saving_the_text_makes_a_new_version_and_returns_to_reading(self):
        resp = self.client.post(self.url(), {"text": "<p>Changed</p>", "version": 1, "next": self.next})
        self.assertRedirects(resp, self.next, fetch_redirect_response=False)
        self.assertEqual(self.get(self.note).text_plain, "Changed")
        self.assertEqual(self.get(self.note).version, 2)

    def test_a_stale_save_shows_the_conflict_screen_and_saves_nothing(self):
        svc.edit(self.profile, self.user, "note", self.note.pk, {"text": "<p>Theirs</p>"})
        resp = self.client.post(self.url(), {"text": "<p>Mine</p>", "version": 1, "next": self.next})
        self.assertEqual(resp.status_code, 409)
        self.assertContains(resp, "Edit and merge", status_code=409)
        self.assertEqual(self.get(self.note).text_plain, "Theirs")

    def test_keep_mine_after_a_conflict_saves_over_it(self):
        svc.edit(self.profile, self.user, "note", self.note.pk, {"text": "<p>Theirs</p>"})
        conflict = self.client.post(self.url(), {"text": "<p>Mine</p>", "version": 1, "next": self.next})
        self.assertEqual(self.resend(conflict).status_code, 302)
        self.assertEqual(self.get(self.note).text_plain, "Mine")

    def test_edit_and_merge_shows_the_editor_with_the_typed_text(self):
        svc.edit(self.profile, self.user, "note", self.note.pk, {"text": "<p>Theirs</p>"})
        conflict = self.client.post(self.url(), {"text": "<p>Mine</p>", "version": 1, "next": self.next})
        merged = self.resend(conflict, merge="1")
        self.assertContains(merged, "Mine")
        self.assertContains(merged, "The saved version")

    def test_a_note_in_trash_has_no_editor(self):
        svc.delete(self.profile, self.user, "note", self.note.pk)
        self.assertEqual(self.client.get(self.url()).status_code, 404)


class LinkOperationTests(NoteViewCase):
    def test_several_links_are_added_one_after_another(self):
        for target in (f"item:{self.one.pk}", f"section:{self.sec.pk}", f"topic:{self.topic.pk}",
                       f"subject:{self.subject.pk}"):
            resp = self.link_post("add", target=target)
            self.assertEqual(resp.status_code, 302, target)
            self.assertTrue(resp["Location"].startswith(reverse("edit_note", args=[self.note.pk])))
        self.assertEqual(self.targets(), [("item", self.one.pk), ("section", self.sec.pk), ("topic", self.topic.pk),
                                          ("subject", self.subject.pk)])

    def test_typed_text_is_saved_with_the_link_in_one_undo_step(self):
        resp = self.link_post("add", target=f"item:{self.one.pk}", text="<p>Typed first</p>", version=1)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.get(self.note).text_plain, "Typed first")
        self.assertEqual(self.targets(), [("item", self.one.pk)])
        group = self.client.session[SESSION_KEY][-1]["group"]
        self.assertEqual(sorted({r.record_type for r in self.history_rows(group)}), ["note", "notelink"])

    def history_rows(self, group):
        from diary.models import VersionHistory

        return VersionHistory.objects.filter(group=group)

    def test_up_down_and_remove(self):
        a, b, c = (self.link("item", o) for o in (self.one, self.two, self.three))
        self.link_post(f"up:{c.pk}")
        self.assertEqual(self.targets()[1], ("item", self.three.pk))
        self.link_post(f"down:{a.pk}")
        self.assertEqual(self.targets(), [("item", self.three.pk), ("item", self.one.pk), ("item", self.two.pk)])
        resp = self.link_post(f"remove:{b.pk}", **{f"lv_{b.pk}": self.get(b).version})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.targets(), [("item", self.three.pk), ("item", self.one.pk)])
        self.assertIsNotNone(self.get(b).deleted_at)  # in the Trash, not gone

    def test_a_removed_link_can_be_undone(self):
        a = self.link("item", self.one)
        self.link_post(f"remove:{a.pk}")
        self.client.post(reverse("edit_undo"), {"group": self.client.session[SESSION_KEY][-1]["group"], "next": self.next})
        self.assertEqual(self.targets(), [("item", self.one.pk)])

    def test_retarget_from_the_editor_returns_to_the_editor(self):
        a = self.link("item", self.one)
        resp = self.client.post(reverse("edit_note_link"), {"op": "retarget", "link": a.pk, "note": self.note.pk,
                                                            "target": f"item:{self.two.pk}", "next": self.next})
        self.assertTrue(resp["Location"].startswith(reverse("edit_note", args=[self.note.pk])))
        self.assertEqual(self.targets(), [("item", self.two.pk)])

    def test_purge_is_for_the_admin_only(self):
        a = self.link("item", self.one)
        self.assertEqual(self.client.post(reverse("edit_note_link"), {"op": "purge", "link": a.pk, "next": self.next}).status_code, 403)
        self.assertTrue(NoteLink.objects.filter(pk=a.pk).exists())
        resp = self.admin_client.post(reverse("edit_note_link"), {"op": "purge", "link": a.pk, "next": self.trash_url})
        self.assertRedirects(resp, self.trash_url, fetch_redirect_response=False)
        self.assertFalse(NoteLink.objects.filter(pk=a.pk).exists())


class PickerTests(NoteViewCase):
    def pick(self, **params):
        params.setdefault("purpose", "link")
        params.setdefault("note", self.note.pk)
        params.setdefault("next", self.next)
        return self.client.get(reverse("edit_note_pick"), params)

    def test_the_top_lists_subjects_and_drilling_down_reaches_sections_and_items(self):
        top = self.pick()
        self.assertContains(top, "Contract")
        inside = self.pick(at=f"subject:{self.subject.pk}")
        self.assertContains(inside, "Formation")
        topic = self.pick(at=f"topic:{self.topic.pk}")
        for text in ("one", "two", "three", "four"):
            self.assertContains(topic, text)
        self.assertContains(topic, "Section")
        self.assertContains(topic, f'value="item:{self.one.pk}"')
        self.assertContains(topic, f'value="section:{self.sec.pk}"')
        self.assertContains(topic, f'value="topic:{self.topic.pk}"')  # the place itself can be chosen too

    def test_nested_items_open_to_their_items(self):
        nested = self.make("item", ("topic", self.topic.pk), kind="nested", text="group")
        self.make("item", ("item", nested.pk), text="child text")
        page = self.pick(at=f"item:{nested.pk}")
        self.assertContains(page, "child text")
        self.assertContains(self.pick(at=f"topic:{self.topic.pk}"), f"&amp;at=item:{nested.pk}", html=False)

    def test_trashed_places_are_not_offered(self):
        svc.delete(self.profile, self.user, "item", self.two.pk)
        self.assertNotContains(self.pick(at=f"topic:{self.topic.pk}"), f'value="item:{self.two.pk}"')

    def test_the_pick_form_adds_a_link(self):
        page = self.pick(at=f"topic:{self.topic.pk}")
        self.assertContains(page, f'action="{reverse("edit_note_link")}"')
        self.assertContains(page, 'name="op" value="add"')

    def test_the_move_picker_posts_to_move_with_the_version(self):
        page = self.pick(purpose="move", at=f"topic:{self.topic.pk}")
        self.assertContains(page, f'action="{reverse("edit_move")}"')
        self.assertContains(page, 'name="kind" value="note"')
        resp = self.client.post(reverse("edit_move"), {"kind": "note", "id": self.note.pk, "version": 1,
                                                       "parent": f"item:{self.one.pk}", "confirmed": "1",
                                                       "next": self.next})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.get(self.note).item_id, self.one.pk)
        self.assertIsNone(self.get(self.note).topic_id)

    def test_move_to_on_a_note_goes_to_the_picker(self):
        resp = self.client.post(reverse("edit_move_to"), {"kind": "note", "id": self.note.pk, "version": 1, "next": self.next})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith(reverse("edit_note_pick")))
        self.assertIn("purpose=move", resp["Location"])

    def test_the_editor_add_button_saves_the_text_and_opens_the_picker(self):
        resp = self.client.post(reverse("edit_note_pick"), {"purpose": "link", "note": self.note.pk, "text": "<p>kept</p>",
                                                            "version": 1, "next": self.next})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith(reverse("edit_note_pick")))
        self.assertEqual(self.get(self.note).text_plain, "kept")

    def test_retarget_picker_for_a_link(self):
        a = self.link("item", self.one)
        page = self.pick(purpose="retarget", link=a.pk, note="")
        self.assertContains(page, 'name="op" value="retarget"')
        self.assertContains(page, f'name="link" value="{a.pk}"')


class DisplayTests(NoteViewCase):
    def test_both_ends_are_shown_and_clickable(self):
        self.link("item", self.one)
        self.link("section", self.sec)
        html = self.read()
        self.assertContains(self.client.get(self.page), "See also: ", count=2)
        self.assertIn(f'href="{self.page}#n-item-{self.one.pk}"', html)
        self.assertIn(f'href="{self.page}#n-section-{self.sec.pk}"', html)
        self.assertIn('id="n-note-%d"' % self.note.pk, html)
        # The targets say where they are linked from, and the line goes back to the Note.
        self.assertEqual(html.count("Linked from: "), 2)
        self.assertIn(f'href="{self.page}#n-note-{self.note.pk}"', html)
        self.assertIn("Contract &gt; Formation", html)

    def test_headings_show_linked_from_too(self):
        self.link("topic", self.topic)
        self.link("subject", self.subject)
        html = self.read()
        self.assertEqual(html.count("Linked from: "), 2)
        self.assertIn(f'href="{self.page}#n-topic-{self.topic.pk}"', html)
        self.assertIn(f'href="{self.page}#n-subject-{self.subject.pk}"', html)

    def test_one_line_per_incoming_note(self):
        second = self.make("note", ("item", self.two.pk), text="<p>Another</p>")
        self.link("item", self.one)
        self.link("item", self.one, second)
        self.assertEqual(self.read().count("Linked from: "), 2)

    def test_a_trashed_target_says_target_deleted_and_is_not_clickable(self):
        self.link("item", self.one)
        svc.delete(self.profile, self.user, "item", self.one.pk)
        html = self.read()
        self.assertIn("(target deleted)", html)
        self.assertNotIn(f'href="{self.page}#n-item-{self.one.pk}"', html)
        self.assertEqual(NoteLink.objects.filter(note=self.note, deleted_at__isnull=True).count(), 1)  # never silently removed

    def test_a_target_inside_a_trashed_topic_also_says_target_deleted(self):
        other = self.make("topic", ("subject", self.subject.pk), name="Other")
        inner = self.make("item", ("topic", other.pk), text="inner item")
        self.link("item", inner)
        svc.delete(self.profile, self.user, "topic", other.pk)
        self.assertIn("(target deleted)", self.read())

    def test_restoring_the_target_revives_the_link(self):
        self.link("item", self.one)
        svc.delete(self.profile, self.user, "item", self.one.pk)
        svc.restore(self.profile, self.user, "item", self.one.pk)
        html = self.read()
        self.assertNotIn("(target deleted)", html)
        self.assertIn(f'href="{self.page}#n-item-{self.one.pk}"', html)
        self.assertIn("Linked from: ", html)

    def test_a_trashed_note_shows_no_linked_from_and_restoring_it_brings_everything_back(self):
        self.link("item", self.one)
        svc.delete(self.profile, self.user, "note", self.note.pk)
        html = self.read()
        self.assertNotIn("Linked from: ", html)
        self.assertNotIn("Remember", html)
        svc.restore(self.profile, self.user, "note", self.note.pk)
        html = self.read()
        self.assertIn("Linked from: ", html)
        self.assertIn("See also: ", html)

    def test_a_note_under_a_trashed_topic_shows_no_linked_from(self):
        other = self.make("topic", ("subject", self.subject.pk), name="Other")
        inner = self.make("note", ("topic", other.pk), text="<p>inner</p>")
        self.link("item", self.one, inner)
        svc.delete(self.profile, self.user, "topic", other.pk)
        self.assertNotIn("Linked from: ", self.read())

    def test_a_note_on_an_item_sits_directly_beneath_it(self):
        self.make("note", ("item", self.one.pk), text="<p>beneath one</p>")
        html = self.read()
        self.assertLess(html.index('id="n-item-%d"' % self.one.pk), html.index("beneath one"))
        self.assertLess(html.index("beneath one"), html.index('id="n-item-%d"' % self.two.pk))

    def test_notes_come_after_the_items_and_sections_and_before_the_child_headings(self):
        sub = self.make("subtopic", ("topic", self.topic.pk), name="Offer heading")
        html = self.read()
        self.assertLess(html.index('id="n-item-%d"' % self.four.pk), html.index('id="n-note-%d"' % self.note.pk))
        self.assertLess(html.index('id="n-note-%d"' % self.note.pk), html.index('id="n-subtopic-%d"' % sub.pk))

    def test_notes_reorder_among_themselves(self):
        second = self.make("note", ("topic", self.topic.pk), text="<p>Second note</p>")
        self.client.post(reverse("edit_move"), {"kind": "note", "id": second.pk, "direction": "up", "next": self.next})
        html = self.read()
        self.assertLess(html.index("Second note"), html.index("Remember"))

    def test_the_target_in_another_subject_links_to_that_subject(self):
        other = self.make("subject", name="Tort")
        self.link("subject", other)
        self.assertIn(f'href="{reverse("read_subject", args=[other.pk])}#n-subject-{other.pk}"', self.read())
        theirs = self.client.get(reverse("read_subject", args=[other.pk])).content.decode()
        self.assertIn("Linked from: ", theirs)
        self.assertIn(f'href="{self.page}#n-note-{self.note.pk}"', theirs)


class ReaderDisplayTests(NoteViewCase):
    def test_readers_see_notes_and_linked_from_but_no_edit_controls(self):
        self.link("item", self.one)
        for suffix in ("", "?edit=1"):
            resp = self.reader_client.get(self.page + suffix)
            self.assertContains(resp, "Remember")
            self.assertContains(resp, "See also: ")
            self.assertContains(resp, "Linked from: ")
            self.assertNotContains(resp, "/edit/note/")
            self.assertNotContains(resp, "note-edit")
            self.assertNotContains(resp, "data-add-url")

    def test_editors_get_an_edit_button_on_each_note_in_edit_mode_only(self):
        self.assertNotContains(self.client.get(self.page), "/edit/note/")
        self.assertContains(self.client.get(self.page + "?edit=1"), reverse("edit_note", args=[self.note.pk]))


class TrashAndPermanentDeleteTests(NoteViewCase):
    def test_a_removed_link_is_listed_in_the_trash_and_can_be_restored(self):
        a = self.link("item", self.one)
        svc.delete(self.profile, self.user, "notelink", a.pk)
        resp = self.client.get(self.trash_url)
        self.assertEqual([e["type"] for e in resp.context["entries"]], ["notelink"])
        self.assertIn("Link to", resp.context["entries"][0]["label"])
        done = self.trash_post("trash_restore", {"kind": "notelink", "id": a.pk, "version": self.get(a).version})
        self.assertEqual(done.status_code, 302)
        self.assertEqual(self.targets(), [("item", self.one.pk)])

    def test_deleting_a_note_through_the_view_takes_the_links_to_trash(self):
        a = self.link("item", self.one)
        resp = self.client.post(reverse("edit_delete"), {"kind": "note", "id": self.note.pk, "confirmed": "1", "next": self.next})
        self.assertEqual(resp.status_code, 302)
        self.assertIsNotNone(self.get(self.note).deleted_at)
        self.assertIsNotNone(self.get(a).deleted_at)

    def test_the_refusal_screen_offers_to_retarget_or_remove_each_link(self):
        a = self.link("item", self.one)
        svc.delete(self.profile, self.user, "item", self.one.pk)
        resp = self.admin_client.post(reverse("trash_permanent"), {"kind": "item", "id": self.one.pk, "confirmed": "1",
                                                                   "next": self.trash_url})
        self.assertContains(resp, "Refused", status_code=409)
        self.assertContains(resp, "Remember", status_code=409)
        self.assertContains(resp, f"purpose=retarget&amp;link={a.pk}", status_code=409)
        self.assertContains(resp, f'name="link" value="{a.pk}"', status_code=409)
        self.assertContains(resp, "Remove this link for good", status_code=409)
        self.assertNotContains(resp, "Yes, delete", status_code=409)

    def test_after_the_link_is_removed_the_permanent_delete_goes_through(self):
        a = self.link("item", self.one)
        svc.delete(self.profile, self.user, "item", self.one.pk)
        self.admin_client.post(reverse("edit_note_link"), {"op": "purge", "link": a.pk, "next": self.trash_url})
        resp = self.admin_client.post(reverse("trash_permanent"), {"kind": "item", "id": self.one.pk, "confirmed": "1",
                                                                   "next": self.trash_url})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(type(self.one).objects.filter(pk=self.one.pk).exists())

    def test_after_the_link_is_retargeted_the_permanent_delete_goes_through(self):
        a = self.link("item", self.one)
        svc.delete(self.profile, self.user, "item", self.one.pk)
        self.admin_client.post(reverse("edit_note_link"), {"op": "retarget", "link": a.pk, "target": f"item:{self.two.pk}",
                                                           "next": self.trash_url})
        resp = self.admin_client.post(reverse("trash_permanent"), {"kind": "item", "id": self.one.pk, "confirmed": "1",
                                                                   "next": self.trash_url})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.targets(), [("item", self.two.pk)])


class HistoryAndSearchTests(NoteViewCase):
    def test_note_history_pages_open(self):
        svc.edit(self.profile, self.user, "note", self.note.pk, {"text": "<p>v2</p>"})
        resp = self.client.get(reverse("history", args=["note", self.note.pk]), {"next": self.next})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.client.get(reverse("history_version", args=["note", self.note.pk, 1])).status_code, 200)

    def test_a_search_hit_on_a_note_opens_it_in_context(self):
        svc.edit(self.profile, self.user, "note", self.note.pk, {"text": "<p>zebrafinch remark</p>"})
        resp = self.client.get(reverse("search"), {"q": "zebrafinch"})
        self.assertContains(resp, f'href="{self.page}#n-note-{self.note.pk}"')
        page = self.client.get(self.page)
        self.assertContains(page, f'id="n-note-{self.note.pk}"')


