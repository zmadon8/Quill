"""CSRF in edit mode, with the real check switched on (the normal test client skips it).

Round 8 root cause: ``postPlain`` in edit-mode.js copied no fields, so Move to... posted without a token.
Every POST of edit mode must refuse a missing token and accept the one the page or card rendered.
"""
import html
import re
from pathlib import Path

from django.conf import settings
from django.test import Client, override_settings
from django.urls import reverse

from diary import services as svc
from diary.tests.helpers import join_main
from diary.tests.service_helpers import ServiceTestCase

TOKEN = re.compile(r'name="csrfmiddlewaretoken" value="([^"]+)"')
HIDDEN = re.compile(r'<input type="hidden" name="([^"]*)" value="([^"]*)">')


def fields_of(markup):
    """The hidden inputs of a rendered fragment, as the browser's form would send them."""
    return {name: html.unescape(value) for name, value in HIDDEN.findall(markup)}


@override_settings(SECURE_SSL_REDIRECT=False)
class CsrfEditModeTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        join_main(self.user, "editor")
        self.user.is_superuser = True  # the permanent delete is Admin only
        self.user.save()
        self.build_topic()
        self.note = self.make("note", ("topic", self.topic.pk), text="<p>csrf note</p>")
        self.note_link = svc.add_link(self.profile, self.user, self.note.pk, ("item", self.one.pk)).record
        self.strict = Client(enforce_csrf_checks=True)
        self.strict.force_login(self.user)
        self.next = reverse("read_subject", args=[self.subject.pk]) + "?edit=1"

    def card(self, kind, record):
        resp = self.strict.get(reverse("edit_inline_card"), {"kind": kind, "id": record.pk, "next": self.next})
        self.assertEqual(resp.status_code, 200)
        return resp.json()["html"]

    def token(self):
        return TOKEN.search(self.card("item", self.one)).group(1)

    def rec(self, kind, obj):
        return {"kind": kind, "id": obj.pk, "version": self.get(obj).version, "next": self.next}

    def cases(self):
        """(name, data[, record id for the address]) for every POST of edit mode."""
        return [
            ("edit_add", {"what": "item", "parent_type": "topic", "parent_id": self.topic.pk, "text": "x"}),
            ("edit_rename", {**self.rec("topic", self.topic), "name": "Formation 2"}),
            ("edit_delete", {**self.rec("item", self.four), "confirmed": "1"}),
            ("edit_move", {**self.rec("item", self.three), "direction": "up"}),
            ("edit_move", {**self.rec("item", self.three), "index": "0", "confirmed": "1"}),
            ("edit_move_to", self.rec("item", self.one)),
            ("edit_landing", {**self.rec("subject", self.subject), "show": "0"}),
            ("edit_item", {**self.rec("item", self.two), "text": "two!", "citation": ""}, self.two.pk),
            ("edit_item_convert", {**self.rec("item", self.two), "to_kind": "nested"}, self.two.pk),
            # Milestone 5: Notes and their links.
            ("edit_add", {"what": "note", "parent_type": "topic", "parent_id": self.topic.pk, "text": "new note"}),
            ("edit_note", {"text": "<p>edited</p>", "version": self.note.version, "next": self.next}, self.note.pk),
            ("edit_note_link", {"op": "add", "note": self.note.pk, "target": f"item:{self.two.pk}", "next": self.next}),
            ("edit_note_link", {"op": f"up:{self.note_link.pk}", "note": self.note.pk, "next": self.next}),
            ("edit_note_link", {"op": "retarget", "link": self.note_link.pk, "target": f"item:{self.three.pk}",
                                "next": self.next}),
            ("edit_note_link", {"op": f"remove:{self.note_link.pk}", "note": self.note.pk, "next": self.next}),
            ("edit_note_link", {"op": "purge", "link": self.note_link.pk, "next": self.next}),
            ("edit_note_pick", {"purpose": "link", "note": self.note.pk, "next": self.next}),
            ("edit_move_to", self.rec("note", self.note)),
            ("edit_move", {**self.rec("note", self.note), "direction": "down"}),
            ("edit_delete", {**self.rec("note", self.note), "confirmed": "1"}),
            ("edit_review", {**self.rec("item", self.two)}),
            ("edit_undo", {"next": self.next}),
            ("history_restore", {**self.rec("item", self.one), "restore_version": "x"}),
            ("trash_restore", {**self.rec("item", self.one)}),
            ("trash_permanent", {**self.rec("item", self.one)}),
        ]

    def url(self, case):
        return reverse(case[0], args=[case[2]]) if len(case) > 2 else reverse(case[0])

    def test_a_missing_token_is_refused_on_every_post(self):
        for case in self.cases():
            resp = self.strict.post(self.url(case), case[1])
            self.assertEqual(resp.status_code, 403, case[0])
            self.assertContains(resp, "security check", status_code=403)
            fetch = self.strict.post(self.url(case), case[1], HTTP_X_REQUESTED_WITH="fetch")
            self.assertEqual(fetch.status_code, 403, case[0])
            self.assertTrue(fetch.json()["csrf"], case[0])

    def test_the_rendered_token_is_accepted_on_every_post(self):
        token = self.token()
        for case in self.cases():
            resp = self.strict.post(self.url(case), {**case[1], "csrfmiddlewaretoken": token})
            self.assertNotEqual(resp.status_code, 403, case[0])

    def test_the_header_form_of_the_token_is_accepted(self):
        self.token()
        resp = self.strict.post(reverse("edit_rename"), {**self.rec("topic", self.topic), "name": "Header"},
                                HTTP_X_CSRFTOKEN=self.token(), HTTP_X_REQUESTED_WITH="fetch")
        self.assertEqual(resp.status_code, 200)

    def test_every_fragment_edit_mode_loads_carries_a_token(self):
        pages = [
            self.card("item", self.one), self.card("topic", self.topic), self.card("section", self.sec),
            self.card("subject", self.subject),
            self.strict.get(reverse("edit_inline_add"), {"ref": f"topic:{self.topic.pk}", "next": self.next}).json()["html"],
            self.strict.post(reverse("edit_move_to"),
                             {**self.rec("item", self.one), "csrfmiddlewaretoken": self.token()}).content.decode(),
        ]
        for markup in pages:
            found = TOKEN.search(markup)
            self.assertIsNotNone(found)
            self.assertGreater(len(found.group(1)), 20)

    def test_the_note_pages_carry_a_token_on_every_form(self):
        editor = self.strict.get(reverse("edit_note", args=[self.note.pk]), {"next": self.next}).content.decode()
        picker = self.strict.get(reverse("edit_note_pick"), {"purpose": "link", "note": self.note.pk,
                                                             "at": f"topic:{self.topic.pk}", "next": self.next}).content.decode()
        for markup in (editor, picker):
            tokens = TOKEN.findall(markup)
            self.assertGreater(len(tokens), 0)
            self.assertGreaterEqual(len(tokens), markup.count("<form method=\"post\""))

    def test_the_whole_note_link_flow_works_with_the_check_on(self):
        # 1. The editor's Add a link button posts the whole form (token included) and saves the typed text.
        editor = self.strict.get(reverse("edit_note", args=[self.note.pk]), {"next": self.next}).content.decode()
        sent = fields_of(editor)
        self.assertIn("csrfmiddlewaretoken", sent)
        sent.update(purpose="link", text="<p>typed</p>")
        step = self.strict.post(reverse("edit_note_pick"), sent)
        self.assertEqual(step.status_code, 302)
        self.assertEqual(self.get(self.note).text_plain, "typed")
        # 2. The picker page: choose a Section. Its form has its own token.
        picker = self.strict.get(step["Location"]).content.decode()
        self.assertEqual(self.strict.get(step["Location"]).status_code, 200)
        form = re.search(r'<form method="post" action="[^"]*note-link/" class="pick-form">(.*?)</form>', picker, re.S)
        choose = fields_of(form.group(1))
        self.assertIn("csrfmiddlewaretoken", choose)
        done = self.strict.post(reverse("edit_note_link"), choose)
        self.assertEqual(done.status_code, 302)
        self.assertEqual(self.note.links.filter(deleted_at__isnull=True).count(), 2)

    def test_the_whole_move_to_flow_works_with_the_check_on(self):
        other = self.make("topic", ("subject", self.subject.pk), name="Other")
        # 1. The card's own fields, which postPlain must copy into the hidden form.
        sent = fields_of(self.card("item", self.one))
        self.assertIn("csrfmiddlewaretoken", sent)
        self.assertEqual({"kind", "id", "version", "next"} - set(sent), set())
        picker = self.strict.post(reverse("edit_move_to"), sent)
        self.assertEqual(picker.status_code, 200)
        # 2. Choose a place on the picker (its form has its own token and the same hidden fields).
        picked = fields_of(picker.content.decode())
        self.assertIn("csrfmiddlewaretoken", picked)
        picked["parent"] = f"topic:{other.pk}"
        confirm = self.strict.post(reverse("edit_move"), picked)
        self.assertEqual(confirm.status_code, 200)
        self.assertEqual(self.get(self.one).topic_id, self.topic.pk)
        # 3. Confirm.
        final = fields_of(confirm.content.decode())
        self.assertIn("csrfmiddlewaretoken", final)
        final["confirmed"] = "1"
        done = self.strict.post(reverse("edit_move"), final)
        self.assertNotEqual(done.status_code, 403)
        self.assertEqual(self.get(self.one).topic_id, other.pk)

    def test_move_to_without_the_card_fields_is_the_failure_the_owner_saw(self):
        resp = self.strict.post(reverse("edit_move_to"), {})
        self.assertEqual(resp.status_code, 403)

    def test_edit_mode_js_no_longer_iterates_form_data_entries_with_forEach_call(self):
        source = (Path(settings.BASE_DIR) / "static" / "js" / "edit-mode.js").read_text(encoding="utf-8")
        self.assertNotIn("forEach.call(new FormData", source)
        self.assertIn("new FormData(form).forEach(", source)
