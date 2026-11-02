"""Edit mode endpoints (Milestone 3b): roles, profile isolation, POST only, CSRF, each action and its renumbering."""
import re

from django.contrib.messages import get_messages
from django.test import Client, override_settings
from django.urls import reverse

from diary import services as svc
from diary.models import Case, Item, Section, Subject, Subtopic, Topic
from diary.services.sequences import members
from diary.tests.helpers import join_main
from diary.tests.service_helpers import ServiceTestCase
from diary.undo_session import SESSION_KEY

ENDPOINTS = ["edit_add", "edit_rename", "edit_delete", "edit_move", "edit_move_to", "edit_landing"]


@override_settings(SECURE_SSL_REDIRECT=False)
class EditViewTestCase(ServiceTestCase):
    """Subject "Contract" > Topic "Formation" with one, two, Section S, three, four; an Editor and a Reader of Main."""

    def setUp(self):
        super().setUp()
        join_main(self.user, "editor")
        join_main(self.user2, "reader")
        self.build_topic()
        self.client.force_login(self.user)
        self.reader_client = Client()
        self.reader_client.force_login(self.user2)
        self.next = reverse("read_subject", args=[self.subject.pk]) + "?edit=1"

    def post(self, name, data=None, client=None):
        data = dict(data or {})
        data.setdefault("next", self.next)
        return (client or self.client).post(reverse(name), data)

    def msgs(self, response):
        return [str(m) for m in get_messages(response.wsgi_request)]

    def rec(self, obj):
        return {"kind": self.ref(obj)[0], "id": obj.pk, "version": self.get(obj).version}

    def order(self):
        return [text for _, text in self.numbered(self.topic)]


class AccessTests(EditViewTestCase):
    def test_readers_get_403_on_every_endpoint(self):
        for name in ENDPOINTS:
            resp = self.post(name, {"kind": "item", "id": self.one.pk}, client=self.reader_client)
            self.assertEqual(resp.status_code, 403, name)
            self.assertEqual(self.reader_client.get(reverse(name)).status_code, 403, name)
        self.assertEqual(self.order(), ["one", "two", "S", "three", "four"])

    def test_a_reader_cannot_change_anything(self):
        self.post("edit_rename", {"kind": "topic", "id": self.topic.pk, "name": "Hacked"}, client=self.reader_client)
        self.post("edit_delete", {"kind": "item", "id": self.one.pk, "confirmed": "1"}, client=self.reader_client)
        self.post("edit_add", {"what": "item", "parent_type": "topic", "parent_id": self.topic.pk, "text": "x"},
                  client=self.reader_client)
        self.assertEqual(self.get(self.topic).name, "Formation")
        self.assertIsNone(self.get(self.one).deleted_at)
        self.assertEqual(Item.objects.filter(topic=self.topic).count(), 4)

    def test_every_endpoint_is_post_only_for_editors(self):
        for name in ENDPOINTS:
            if name != "edit_add":  # the Add page answers GET (it needs a place: ?after= or ?parent=)
                self.assertEqual(self.client.get(reverse(name)).status_code, 405, name)
        self.assertEqual(self.client.get(reverse("edit_add")).status_code, 404)

    def test_csrf_token_is_required(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        resp = strict.post(reverse("edit_add"), {"what": "item", "parent_type": "topic", "parent_id": self.topic.pk, "text": "x"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Item.objects.filter(topic=self.topic).count(), 4)

    def test_a_failed_csrf_check_on_a_fetch_request_says_the_session_expired(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        resp = strict.post(reverse("edit_add"), {"what": "item", "text": "x"}, HTTP_X_REQUESTED_WITH="fetch")
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(resp.json()["csrf"])

    def test_readers_see_no_edit_controls_and_editors_see_them_only_in_edit_mode(self):
        url = reverse("read_subject", args=[self.subject.pk])
        for query in ("", "?edit=1"):
            resp = self.reader_client.get(url + query)
            self.assertEqual(resp.status_code, 200)
            for absent in ("data-edit-switch", "data-row-actions", "data-edit-row", "edit-mode.js", "data-undo-form"):
                self.assertNotContains(resp, absent)
        plain = self.client.get(url)
        self.assertContains(plain, "data-edit-switch")
        self.assertContains(plain, 'aria-checked="false"')
        self.assertNotContains(plain, "data-row-actions")
        self.assertNotContains(plain, "data-edit-row")
        self.assertNotContains(plain, "data-undo-form")
        editing = self.client.get(url + "?edit=1")
        self.assertContains(editing, 'aria-checked="true"')
        self.assertContains(editing, "data-row-actions")
        self.assertContains(editing, "data-drag-handle")
        self.assertContains(editing, "data-edit-done")
        self.assertContains(editing, "data-undo-form")
        self.assertContains(editing, "edit-mode.js")
        self.assertContains(editing, "css/edit.css")
        self.assertContains(editing, 'class="edit-on"')
        # The old icon edit bars are gone.
        for old in ("data-edit-bar", "Edit mode", "Done editing", "quick-add"):
            self.assertNotContains(editing, old)

    def test_subject_lists_show_controls_only_to_editors_in_edit_mode(self):
        self.assertNotContains(self.reader_client.get(reverse("diary_home") + "?edit=1"), "data-row-actions")
        self.assertNotContains(self.reader_client.get(reverse("diary_home")), "data-edit-switch")
        self.assertNotContains(self.client.get(reverse("diary_home")), "data-row-actions")
        self.assertContains(self.client.get(reverse("diary_home")), "data-edit-switch")
        self.assertContains(self.client.get(reverse("diary_home") + "?edit=1"), "data-row-actions")
        self.make("subject", name="Elsewhere", show_on_landing=False)
        # Both lists are on the one page, but Subjects are alphabetical: no reorder run, no drag handle.
        resp = self.client.get(reverse("diary_home") + "?edit=1")
        self.assertNotContains(resp, "data-run=")
        self.assertNotContains(resp, "data-drag-handle")
        self.assertContains(resp, "data-edit-open")

    def test_next_address_must_stay_on_this_site(self):
        for bad in ("https://evil.example/", "//evil.example/x", "javascript:alert(1)"):
            resp = self.post("edit_rename", {"kind": "topic", "id": self.topic.pk, "name": "Formation", "next": bad})
            self.assertRedirects(resp, reverse("diary_home"), fetch_redirect_response=False)


class OtherProfileTests(EditViewTestCase):
    def test_ids_from_another_profile_give_404_and_change_nothing(self):
        subject = self.make("subject", profile=self.other_profile, name="Foreign")
        topic = self.make("topic", ("subject", subject.pk), profile=self.other_profile, name="Foreign topic")
        item = self.make("item", ("topic", topic.pk), profile=self.other_profile, text="foreign")
        calls = [
            ("edit_rename", {"kind": "subject", "id": subject.pk, "name": "Mine now"}),
            ("edit_rename", {"kind": "topic", "id": topic.pk, "name": "Mine now"}),
            ("edit_delete", {"kind": "item", "id": item.pk}),
            ("edit_delete", {"kind": "item", "id": item.pk, "confirmed": "1"}),
            ("edit_move", {"kind": "item", "id": item.pk, "direction": "up"}),
            ("edit_move", {"kind": "item", "id": item.pk, "index": "0", "confirmed": "1"}),
            ("edit_move", {"kind": "item", "id": self.one.pk, "parent": f"topic:{topic.pk}"}),
            ("edit_move", {"kind": "item", "id": self.one.pk, "parent": f"topic:{topic.pk}", "confirmed": "1"}),
            ("edit_move_to", {"kind": "item", "id": item.pk}),
            ("edit_landing", {"id": subject.pk, "show": "0"}),
            ("edit_add", {"what": "item", "parent_type": "topic", "parent_id": topic.pk, "text": "sneaky"}),
            ("edit_add", {"what": "section", "parent_type": "subject", "parent_id": subject.pk, "name": "sneaky"}),
        ]
        for name, data in calls:
            self.assertEqual(self.post(name, data).status_code, 404, (name, data))
        self.assertEqual(self.get(subject).name, "Foreign")
        self.assertEqual(self.get(topic).name, "Foreign topic")
        self.assertIsNone(self.get(item).deleted_at)
        self.assertEqual(self.get(item).version, 1)
        self.assertTrue(self.get(subject).show_on_landing)
        self.assertEqual(Item.objects.filter(profile=self.other_profile).count(), 1)
        self.assertEqual(Section.objects.filter(profile=self.other_profile).count(), 0)
        self.assertEqual(self.get(self.one).topic_id, self.topic.pk)

    def test_unknown_kinds_and_bad_ids_give_404(self):
        self.assertEqual(self.post("edit_rename", {"kind": "note", "id": self.one.pk, "name": "x"}).status_code, 404)
        self.assertEqual(self.post("edit_rename", {"kind": "topic", "id": "abc", "name": "x"}).status_code, 404)
        self.assertEqual(self.post("edit_rename", {"kind": "topic", "name": "x"}).status_code, 404)
        self.assertEqual(self.post("edit_rename", {"kind": "topic", "id": 999999, "name": "x"}).status_code, 404)


class AddTests(EditViewTestCase):
    def add(self, what, parent, **fields):
        return self.post("edit_add", {"what": what, "parent_type": parent[0], "parent_id": parent[1], **fields})

    def test_add_item_goes_last_and_continues_the_numbering(self):
        resp = self.add("item", ("topic", self.topic.pk), text="five\nsix", citation="  (2020) 1 SCC 1 ")
        self.assertRedirects(resp, self.next, fetch_redirect_response=False)
        new = Item.objects.get(topic=self.topic, position=6)
        self.assertIn("five", new.text)
        self.assertIn("six", new.text)
        self.assertEqual(new.citation, "")  # an Item's citation is its first Case
        self.assertEqual([(c.citation, c.position) for c in Case.objects.filter(item=new)], [("(2020) 1 SCC 1", 1)])
        self.assertEqual(new.kind, "plain")
        self.assertEqual(self.numbered(self.topic)[-1][0], "(3)")
        self.assertEqual(self.positions([self.one, self.two, self.sec, self.three, self.four]), [1, 2, 3, 4, 5])
        self.assertEqual(new.created_by, self.user)

    def test_item_text_is_escaped_not_trusted(self):
        self.add("item", ("topic", self.topic.pk), text="<script>alert(1)</script>")
        new = Item.objects.get(topic=self.topic, position=6)
        self.assertNotIn("<script>", new.text)

    def test_add_an_item_without_text_or_citation_is_refused(self):
        resp = self.add("item", ("topic", self.topic.pk), text="  ", citation="")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Item.objects.filter(topic=self.topic).count(), 4)
        self.assertTrue(self.msgs(resp))

    def test_add_nested_item_then_an_item_beneath_it(self):
        self.add("nested", ("topic", self.topic.pk), text="nested heading")
        nested = Item.objects.get(topic=self.topic, kind="nested")
        self.assertEqual(nested.position, 6)
        self.add("item", ("item", nested.pk), text="child")
        child = Item.objects.get(parent_item=nested)
        self.assertEqual((child.kind, child.position, child.topic_id), ("plain", 1, None))

    def test_an_item_cannot_go_beneath_a_plain_item(self):
        resp = self.add("item", ("item", self.one.pk), text="child")
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Item.objects.filter(parent_item=self.one).exists())
        self.assertTrue(self.msgs(resp))

    def test_add_section_with_a_name(self):
        self.add("section", ("topic", self.topic.pk), name="  Later   part ")
        section = Section.objects.get(topic=self.topic, position=6)
        self.assertEqual(section.name, "Later part")

    def test_add_topic_and_subtopic(self):
        self.add("topic", ("subject", self.subject.pk), name="Performance")
        topic = Topic.objects.get(subject=self.subject, name="Performance")
        self.assertEqual(topic.position, 2)  # next free stored number; shown alphabetically
        self.add("subtopic", ("topic", topic.pk), name="Time")
        sub = Subtopic.objects.get(topic=topic)
        self.assertEqual((sub.name, sub.position), ("Time", 1))

    def test_a_subject_with_topics_refuses_a_direct_subtopic(self):
        resp = self.add("subtopic", ("subject", self.subject.pk), name="Direct")
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Subtopic.objects.filter(subject=self.subject).exists())
        self.assertTrue(self.msgs(resp))

    def test_a_blank_heading_name_is_refused(self):
        resp = self.add("topic", ("subject", self.subject.pk), name="   ")
        self.assertEqual(Topic.objects.filter(subject=self.subject).count(), 1)
        self.assertTrue(self.msgs(resp))

    def test_add_subjects_to_either_list(self):
        self.post("edit_add", {"what": "subject", "name": "Tort", "landing": "1"})
        self.post("edit_add", {"what": "subject", "name": "Misc", "landing": "0"})
        tort, misc = Subject.objects.get(name="Tort"), Subject.objects.get(name="Misc")
        self.assertEqual((tort.show_on_landing, tort.landing_position), (True, 2))
        self.assertEqual((misc.show_on_landing, misc.other_acts_position), (False, 1))

    def test_a_duplicate_subject_name_is_refused(self):
        resp = self.post("edit_add", {"what": "subject", "name": "contract", "landing": "1"})
        self.assertEqual(Subject.objects.filter(profile=self.profile).count(), 1)
        self.assertTrue(self.msgs(resp))

    def test_the_one_text_box_is_the_name_of_each_heading_kind_and_section(self):
        self.add("topic", ("subject", self.subject.pk), text="Performance")
        self.assertTrue(Topic.objects.filter(subject=self.subject, name="Performance").exists())
        self.add("subtopic", ("topic", self.topic.pk), text="Time")
        self.assertTrue(Subtopic.objects.filter(topic=self.topic, name="Time").exists())
        self.add("section", ("topic", self.topic.pk), text="  Later   part ")
        self.assertTrue(Section.objects.filter(topic=self.topic, name="Later part").exists())
        self.post("edit_add", {"what": "subject", "text": "Tort", "landing": "1"})
        self.assertTrue(Subject.objects.filter(profile=self.profile, name="Tort").exists())

    def test_the_one_text_box_is_the_text_of_an_item_and_a_nested_item(self):
        self.add("item", ("topic", self.topic.pk), text="plain words")
        self.add("nested", ("topic", self.topic.pk), text="nested words")
        self.assertEqual(Item.objects.get(topic=self.topic, text="<p>plain words</p>").kind, "plain")
        self.assertEqual(Item.objects.get(topic=self.topic, text="<p>nested words</p>").kind, "nested")

    def test_item_text_sent_as_html_by_the_script_is_sanitised_not_escaped(self):
        self.add("item", ("topic", self.topic.pk), text="<p>Some <b>bold</b><script>x</script></p>", text_format="html")
        new = Item.objects.get(topic=self.topic, position=6)
        self.assertIn("<b>bold</b>", new.text)
        self.assertNotIn("<script>", new.text)

    def test_tags_and_newlines_are_stripped_from_a_heading_name(self):
        self.add("topic", ("subject", self.subject.pk), text="<b>Per</b>form\nance<script>alert(1)</script>")
        topic = Topic.objects.exclude(pk=self.topic.pk).get(subject=self.subject)
        self.assertNotIn("<", topic.name)
        self.assertNotIn("\n", topic.name)
        self.assertTrue(topic.name.startswith("Perform ance"))

    def test_an_empty_text_is_refused_for_every_heading_kind(self):
        before = (Topic.objects.count(), Subtopic.objects.count(), Section.objects.count(), Subject.objects.count())
        for what, parent in (("topic", ("subject", self.subject.pk)), ("subtopic", ("topic", self.topic.pk)),
                             ("section", ("topic", self.topic.pk))):
            resp = self.add(what, parent, text="  <b></b> ")
            self.assertTrue(self.msgs(resp))
        resp = self.post("edit_add", {"what": "subject", "text": " ", "landing": "1"})
        self.assertTrue(self.msgs(resp))
        self.assertEqual(before, (Topic.objects.count(), Subtopic.objects.count(), Section.objects.count(), Subject.objects.count()))

    def test_a_too_long_name_is_refused(self):
        from diary.views_edit import HEADING_LIMITS

        for what, parent, model in (("topic", ("subject", self.subject.pk), Topic), ("section", ("topic", self.topic.pk), Section)):
            count = model.objects.count()
            resp = self.add(what, parent, text="x" * (HEADING_LIMITS[what] + 1))
            self.assertTrue(self.msgs(resp))
            self.assertEqual(model.objects.count(), count)
        self.add("topic", ("subject", self.subject.pk), text="y" * HEADING_LIMITS["topic"])
        self.assertTrue(Topic.objects.filter(subject=self.subject, name="y" * HEADING_LIMITS["topic"]).exists())

    def test_a_citation_is_ignored_for_headings_and_sections_even_when_posted(self):
        self.add("topic", ("subject", self.subject.pk), text="Performance", citation="A v B")
        self.add("subtopic", ("topic", self.topic.pk), text="Time", citation="A v B")
        self.add("section", ("topic", self.topic.pk), text="Later", citation="A v B")
        self.post("edit_add", {"what": "subject", "text": "Tort", "citation": "A v B", "landing": "1"})
        self.assertFalse(Section.objects.filter(topic=self.topic, name__contains="A v B").exists())
        for model in (Subject, Topic, Subtopic, Section):
            self.assertFalse(model.objects.filter(name__contains="A v B").exists())
        self.assertFalse(Item.objects.filter(citation="A v B").exists())
        self.assertFalse(Case.objects.filter(citation="A v B").exists())

    def test_a_citation_is_saved_for_an_item_and_a_nested_item(self):
        self.add("item", ("topic", self.topic.pk), text="one more", citation=" A v B ")
        self.add("nested", ("topic", self.topic.pk), text="n", citation="C v D")
        item = Item.objects.get(topic=self.topic, text="<p>one more</p>")
        self.assertEqual([c.citation for c in Case.objects.filter(item=item)], ["A v B"])
        self.assertEqual(Item.objects.get(topic=self.topic, text="<p>n</p>").citation, "C v D")

    def test_the_full_add_page_has_one_text_box_and_a_citation_box(self):
        resp = self.client.get(reverse("edit_add") + f"?parent=topic:{self.topic.pk}")
        self.assertContains(resp, "data-add-form")
        self.assertContains(resp, "data-add-citation")
        self.assertNotContains(resp, "Name (headings and Sections)")
        self.assertNotContains(resp, "Text (Items)")
        # The reading page no longer carries add forms; they are fetched when "+ Add" is pressed.
        self.assertNotContains(self.client.get(self.next), "data-add-form")

    def test_every_row_has_exactly_two_buttons_with_words_and_tooltips(self):
        resp = self.client.get(self.next)
        html = resp.content.decode()
        rows = html.count("data-row-actions")
        self.assertGreater(rows, 3)
        self.assertEqual(html.count("data-add-here"), rows)
        self.assertEqual(html.count("data-edit-open"), rows)
        self.assertContains(resp, 'title="Add something')
        self.assertContains(resp, "<span>Add</span>")
        self.assertContains(resp, "<span>Edit</span>")
        self.assertContains(resp, 'title="Edit this Item"')
        self.assertContains(resp, 'title="Edit this Topic"')
        for gone in ("Mark for review", "Rename", 'class="icon"', "Move up", "Move down"):
            self.assertNotContains(resp, gone)

    def test_choosing_nothing_to_add_is_refused(self):
        resp = self.post("edit_add", {"what": "", "parent_type": "topic", "parent_id": self.topic.pk})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(self.msgs(resp))


FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


class AddAfterTests(EditViewTestCase):
    """Add after a record (R5-10b quick-add, R5-10c add after): placement, numbering, Undo, roles, JSON, the Add page."""

    def add_after(self, obj, what="item", client=None, **fields):
        data = {"what": what, "after": "%s:%d" % self.ref(obj), "after_version": self.get(obj).version, **fields}
        return self.post("edit_add", data, client=client)

    def test_add_after_an_item_shifts_the_later_siblings_and_the_numbers(self):
        self.add_after(self.three, text="new")
        self.assertEqual(self.order(), ["one", "two", "S", "three", "new", "four"])
        self.assertEqual(self.numbered(self.topic)[-3:], [("(1)", "three"), ("(2)", "new"), ("(3)", "four")])
        self.assertEqual(self.positions([self.one, self.two, self.sec, self.three, self.four]), [1, 2, 3, 4, 6])
        self.assertEqual(Item.objects.get(topic=self.topic, text_plain="new").position, 5)

    def test_add_after_the_last_item_goes_last(self):
        self.add_after(self.four, text="end")
        self.assertEqual(self.order()[-2:], ["four", "end"])

    def test_add_after_a_section_goes_directly_after_the_section(self):
        self.add_after(self.sec, text="first under S")
        self.assertEqual(self.order(), ["one", "two", "S", "first under S", "three", "four"])

    def test_add_a_section_after_an_item(self):
        self.add_after(self.one, what="section", name="Early")
        self.assertEqual(self.order(), ["one", "Early", "two", "S", "three", "four"])

    def test_add_after_a_nested_child_stays_inside_the_nested_item(self):
        nested = self.make("item", ("topic", self.topic.pk), kind="nested", text="nested")
        child = self.make("item", ("item", nested.pk), text="child one")
        self.make("item", ("item", nested.pk), text="child two")
        self.add_after(child, text="between")
        kids = list(Item.objects.filter(parent_item=nested).order_by("position").values_list("text_plain", "position"))
        self.assertEqual(kids, [("child one", 1), ("between", 2), ("child two", 3)])

    def test_add_a_topic_after_a_topic(self):
        later = self.make("topic", ("subject", self.subject.pk), name="Later")
        self.add_after(self.topic, what="topic", name="Between")
        names = [t.name for t in members(self.profile.pk, ("topic", "subject", self.subject.pk))]
        self.assertEqual(names, ["Between", "Formation", "Later"])  # alphabetical wherever it was added after
        self.assertEqual((self.get(self.topic).position, self.get(later).position), (1, 2))
        self.assertEqual(Topic.objects.get(name="Between").position, 3)
        self.assertEqual((self.get(later).version, self.get(self.topic).version), (1, 1))

    def test_add_inside_a_heading_at_the_end_or_first(self):
        self.post("edit_add", {"what": "item", "parent_type": "topic", "parent_id": self.topic.pk, "text": "last"})
        self.post("edit_add", {"what": "item", "parent_type": "topic", "parent_id": self.topic.pk, "text": "top", "first": "1"})
        self.assertEqual(self.order(), ["top", "one", "two", "S", "three", "four", "last"])

    def test_the_new_entry_has_history_and_the_siblings_are_reordered_in_the_same_step(self):
        self.add_after(self.one, text="new")
        new = Item.objects.get(topic=self.topic, text_plain="new")
        self.assertEqual(self.history_kinds(new), ["create"])
        self.assertIn("reorder", self.history_kinds(self.two))

    def test_undo_removes_an_entry_added_after_and_restores_the_numbers(self):
        self.add_after(self.two, text="new")
        self.assertEqual(self.order(), ["one", "two", "new", "S", "three", "four"])
        group = self.client.session[SESSION_KEY][-1]["group"]
        resp = self.client.post(reverse("edit_undo"), {"group": group, "next": self.next})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.order(), ["one", "two", "S", "three", "four"])
        self.assertEqual(self.positions([self.one, self.two, self.sec, self.three, self.four]), [1, 2, 3, 4, 5])

    def test_readers_get_403_for_add_and_add_after(self):
        resp = self.add_after(self.one, text="sneaky", client=self.reader_client)
        self.assertEqual(resp.status_code, 403)
        resp = self.reader_client.post(reverse("edit_add"), {"what": "item", "after": "item:%d" % self.one.pk, "text": "x"}, **FETCH)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self.reader_client.get(reverse("edit_add") + "?after=item:%d" % self.one.pk).status_code, 403)
        self.assertEqual(self.order(), ["one", "two", "S", "three", "four"])

    def test_a_missing_or_invalid_after_is_rejected(self):
        for bad in ("item:999999", "item:x", "bogus:1", "item", "subject:%d" % self.subject.pk):
            resp = self.post("edit_add", {"what": "item", "after": bad, "text": "x"})
            self.assertEqual(resp.status_code, 404, bad)
        self.assertEqual(self.order(), ["one", "two", "S", "three", "four"])

    def test_after_in_another_profile_is_404(self):
        subject = self.make("subject", profile=self.other_profile, name="Elsewhere")
        topic = self.make("topic", ("subject", subject.pk), profile=self.other_profile, name="T")
        foreign = self.make("item", ("topic", topic.pk), profile=self.other_profile, text="foreign")
        resp = self.post("edit_add", {"what": "item", "after": "item:%d" % foreign.pk, "text": "sneaky"})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(Item.objects.filter(topic=topic).count(), 1)

    def test_after_a_trashed_record_is_refused(self):
        svc.delete(self.profile, self.user, "item", self.two.pk)
        resp = self.add_after(self.two, text="x")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(self.msgs(resp))
        self.assertFalse(Item.objects.filter(text_plain="x").exists())

    def test_a_mismatched_kind_after_a_record_is_refused_before_placing(self):
        for obj, what, fields in ((self.topic, "section", {"name": "Nope2"}), (self.one, "subtopic", {"name": "Nope3"})):
            resp = self.add_after(obj, what=what, **fields)
            self.assertEqual(resp.status_code, 302)
            self.assertTrue(self.msgs(resp))
        self.assertFalse(Section.objects.filter(name="Nope2").exists())
        self.assertFalse(Subtopic.objects.filter(name="Nope3").exists())

    def test_the_add_page_for_a_parent_puts_the_entry_first_like_the_inline_form(self):
        resp = self.client.get(reverse("edit_add") + "?parent=topic:%d" % self.topic.pk)
        self.assertContains(resp, 'name="first" value="1"')
        self.assertContains(resp, "at the top of")

    def test_a_kind_that_cannot_sit_there_is_refused(self):
        resp = self.add_after(self.one, what="topic", name="Nope")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(self.msgs(resp))
        self.assertFalse(Topic.objects.filter(name="Nope").exists())

    def test_a_stale_after_version_shows_the_conflict_page_and_adds_nothing(self):
        stale = self.get(self.one).version
        svc.edit(self.profile, self.user2, "item", self.one.pk, {"text": "changed elsewhere"})
        resp = self.post("edit_add", {"what": "item", "after": "item:%d" % self.one.pk, "after_version": stale, "text": "new"})
        self.assertEqual(resp.status_code, 409)
        self.assertFalse(Item.objects.filter(text_plain="new").exists())

    def test_json_success_gives_the_new_id_and_the_place_for_the_next_add(self):
        resp = self.client.post(reverse("edit_add"), {
            "what": "item", "after": "item:%d" % self.two.pk, "after_version": self.get(self.two).version, "text": "typed"}, **FETCH)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        new = Item.objects.get(topic=self.topic, text_plain="typed")
        self.assertEqual((body["ok"], body["id"], body["kind"], body["after"]), (True, new.pk, "item", "item:%d" % new.pk))
        self.assertEqual(body["version"], new.version)
        self.assertEqual(self.order(), ["one", "two", "typed", "S", "three", "four"])

    def test_json_errors_for_blank_text_and_nothing_is_added(self):
        for what, extra in (("item", {"text": "  ", "text_format": "html"}), ("section", {"text": " "})):
            resp = self.client.post(reverse("edit_add"), {"what": what, "after": "item:%d" % self.two.pk, **extra}, **FETCH)
            self.assertEqual(resp.status_code, 400)
            body = resp.json()
            self.assertFalse(body["ok"])
            self.assertTrue(body["errors"])
        self.assertEqual(self.order(), ["one", "two", "S", "three", "four"])

    def test_json_conflict_and_refusals_are_json_too(self):
        stale = self.get(self.one).version
        svc.edit(self.profile, self.user2, "item", self.one.pk, {"text": "changed elsewhere"})
        resp = self.client.post(reverse("edit_add"), {"what": "item", "after": "item:%d" % self.one.pk, "after_version": stale, "text": "n"}, **FETCH)
        self.assertEqual(resp.status_code, 409)
        self.assertFalse(resp.json()["ok"])
        resp = self.client.post(reverse("edit_add"), {"what": "topic", "after": "item:%d" % self.one.pk, "text": "n"}, **FETCH)
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(resp.json()["errors"])

    def test_the_add_page_preselects_the_place_without_javascript(self):
        resp = self.client.get(reverse("edit_add") + "?after=item:%d&next=%s" % (self.two.pk, self.next))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="after" value="item:%d"' % self.two.pk)
        self.assertContains(resp, "directly after")
        self.assertContains(resp, '<option value="item">')
        self.assertContains(resp, 'name="next"')
        resp = self.client.get(reverse("edit_add") + "?parent=topic:%d" % self.topic.pk)
        self.assertContains(resp, 'name="parent_type" value="topic"')
        self.assertContains(resp, '<option value="subtopic">')

    def test_the_add_page_form_posts_to_the_same_add(self):
        self.client.get(reverse("edit_add") + "?after=item:%d" % self.one.pk)
        self.add_after(self.one, text="from the page")
        self.assertEqual(self.order()[:3], ["one", "from the page", "two"])

    def test_the_add_page_rejects_bad_places(self):
        for query in ("?after=item:999999", "?after=bogus:1", "?parent=item:x", ""):
            self.assertEqual(self.client.get(reverse("edit_add") + query).status_code, 404, query)

    def test_the_plus_is_in_edit_mode_only_and_never_for_readers(self):
        url = reverse("read_subject", args=[self.subject.pk])
        self.assertNotContains(self.client.get(url), "data-add-here")
        page = self.client.get(url + "?edit=1")
        self.assertContains(page, "data-add-here")
        self.assertContains(page, 'data-ref="item:%d"' % self.one.pk)
        self.assertContains(page, 'data-ref="section:%d"' % self.sec.pk)
        self.assertContains(page, 'data-ref="topic:%d"' % self.topic.pk)
        self.assertContains(page, reverse("edit_inline_add"))
        self.assertContains(page, reverse("edit_inline_card"))
        for query in ("", "?edit=1"):
            self.assertNotContains(self.reader_client.get(url + query), "data-add-here")

    def test_edit_mode_has_the_plus_on_items_and_sections_as_a_link_to_the_add_page(self):
        page = self.client.get(self.next)
        self.assertContains(page, "?after=item:%d" % self.one.pk)
        self.assertContains(page, "?after=section:%d" % self.sec.pk)
        self.assertContains(page, "?parent=topic:%d" % self.topic.pk)


class RenameTests(EditViewTestCase):
    def test_rename_each_heading_type_and_a_section(self):
        sub = self.make("subtopic", ("topic", self.topic.pk), name="Old sub")
        for obj, name in ((self.subject, "Contracts"), (self.topic, "Making"), (sub, "New sub"), (self.sec, "Part two")):
            resp = self.post("edit_rename", {**self.rec(obj), "name": f"  {name}  "})
            self.assertRedirects(resp, self.next, fetch_redirect_response=False)
            self.assertEqual(self.get(obj).name, name)
            self.assertEqual(self.get(obj).version, 2)

    def test_a_section_name_may_be_cleared(self):
        self.post("edit_rename", {**self.rec(self.sec), "name": ""})
        self.assertEqual(self.get(self.sec).name, "")

    def test_a_blank_heading_name_and_a_duplicate_subject_name_are_refused(self):
        other = self.make("subject", name="Tort")
        for data in ({**self.rec(self.topic), "name": " "}, {**self.rec(other), "name": "CONTRACT"}):
            resp = self.post("edit_rename", data)
            self.assertEqual(resp.status_code, 302)
            self.assertTrue(self.msgs(resp))
        self.assertEqual(self.get(self.topic).name, "Formation")
        self.assertEqual(self.get(other).name, "Tort")

    def test_items_are_not_renamed_here(self):
        resp = self.post("edit_rename", {**self.rec(self.one), "name": "x"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.get(self.one).version, 1)
        self.assertTrue(self.msgs(resp))

    def test_a_stale_version_shows_the_conflict_page_and_saves_nothing(self):
        stale = self.rec(self.topic)
        svc.edit(self.profile, self.user2, "topic", self.topic.pk, {"name": "Changed elsewhere"})
        resp = self.post("edit_rename", {**stale, "name": "Mine"})
        self.assertEqual(resp.status_code, 409)
        self.assertContains(resp, "This Topic has changed", status_code=409)
        self.assertContains(resp, "Mine", status_code=409)
        self.assertEqual(self.get(self.topic).name, "Changed elsewhere")


class DeleteTests(EditViewTestCase):
    def test_delete_first_shows_the_renumbering_and_changes_nothing(self):
        resp = self.post("edit_delete", self.rec(self.sec))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Move to Trash")
        ids = {c["id"] for c in resp.context["changes"]}
        self.assertEqual(ids, {self.three.pk, self.four.pk})
        self.assertIsNone(self.get(self.sec).deleted_at)

    def test_confirmed_delete_of_a_section_renumbers_the_items_after_it(self):
        resp = self.post("edit_delete", {**self.rec(self.sec), "confirmed": "1"})
        self.assertRedirects(resp, self.next, fetch_redirect_response=False)
        self.assertIsNotNone(self.get(self.sec).deleted_at)
        self.assertEqual(self.numbered(self.topic), [("(1)", "one"), ("(2)", "two"), ("(3)", "three"), ("(4)", "four")])

    def test_delete_an_item(self):
        self.post("edit_delete", {**self.rec(self.two), "confirmed": "1"})
        self.assertIsNotNone(self.get(self.two).deleted_at)
        self.assertEqual(self.order(), ["one", "S", "three", "four"])

    def test_delete_a_topic_takes_its_items_and_goes_to_the_subject(self):
        resp = self.post("edit_delete", {**self.rec(self.topic), "confirmed": "1"})
        self.assertRedirects(resp, reverse("read_subject", args=[self.subject.pk]) + "?edit=1", fetch_redirect_response=False)
        self.assertIsNotNone(self.get(self.topic).deleted_at)
        self.assertIsNotNone(self.get(self.one).deleted_at)

    def test_delete_a_subject_goes_to_the_subjects_page(self):
        resp = self.post("edit_delete", {**self.rec(self.subject), "confirmed": "1"})
        self.assertRedirects(resp, reverse("diary_home"), fetch_redirect_response=False)
        self.assertIsNotNone(self.get(self.subject).deleted_at)

    def test_the_preview_counts_what_goes_with_a_heading(self):
        resp = self.post("edit_delete", self.rec(self.topic))
        self.assertEqual(resp.context["count"], 6)

    def test_delete_with_a_stale_version_is_a_conflict(self):
        stale = self.rec(self.one)
        svc.edit(self.profile, self.user, "item", self.one.pk, {"text": "uno"})
        resp = self.post("edit_delete", {**stale, "confirmed": "1"})
        self.assertEqual(resp.status_code, 409)
        self.assertIsNone(self.get(self.one).deleted_at)

    def test_deleting_twice_is_harmless(self):
        data = {**self.rec(self.one), "confirmed": "1"}
        self.post("edit_delete", data)
        resp = self.post("edit_delete", data)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.get(self.one).version, 2)


class MoveTests(EditViewTestCase):
    def test_up_and_down_swap_neighbours_and_renumber(self):
        self.post("edit_move", {**self.rec(self.two), "direction": "up"})
        self.assertEqual(self.order(), ["two", "one", "S", "three", "four"])
        self.post("edit_move", {**self.rec(self.sec), "direction": "up"})
        self.assertEqual(self.numbered(self.topic)[:3], [("(1)", "two"), ("(a)", "S"), ("(1)", "one")])
        self.post("edit_move", {**self.rec(self.sec), "direction": "down"})
        self.assertEqual(self.order(), ["two", "one", "S", "three", "four"])
        self.assertEqual(self.positions([self.two, self.one, self.sec, self.three, self.four]), [1, 2, 3, 4, 5])

    def test_up_at_the_top_does_nothing(self):
        resp = self.post("edit_move", {**self.rec(self.one), "direction": "up"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.get(self.one).version, 1)
        self.assertEqual(self.order(), ["one", "two", "S", "three", "four"])

    def test_headings_and_subjects_cannot_be_moved_up_down_or_to_an_index(self):
        topic2 = self.make("topic", ("subject", self.subject.pk), name="Second")
        sub1 = self.make("subtopic", ("topic", topic2.pk), name="Alpha")
        sub2 = self.make("subtopic", ("topic", topic2.pk), name="Beta")
        other = self.make("subject", name="Tort")
        for obj in (topic2, sub2, other):
            for extra in ({"direction": "up"}, {"direction": "down"}, {"index": "0", "confirmed": "1"}, {"index": "0"}):
                resp = self.post("edit_move", {**self.rec(obj), **extra})
                self.assertEqual(resp.status_code, 302)
                self.assertTrue(any("alphabetically" in m for m in self.msgs(resp)), (obj, extra))
        self.assertEqual(self.positions([self.topic, topic2]), [1, 2])
        self.assertEqual(self.positions([sub1, sub2]), [1, 2])
        self.assertEqual((self.get(other).landing_position, self.get(self.subject).landing_position), (2, 1))
        for obj in (topic2, sub2, other):
            self.assertEqual(self.get(obj).version, 1)

    def test_drop_at_an_index_moves_without_asking(self):
        resp = self.post("edit_move", {**self.rec(self.four), "index": "0", "confirmed": "1"})
        self.assertRedirects(resp, self.next, fetch_redirect_response=False)
        self.assertEqual(self.order(), ["four", "one", "two", "S", "three"])
        self.assertEqual(self.positions([self.four, self.one, self.two, self.sec, self.three]), [1, 2, 3, 4, 5])

    def test_up_with_a_stale_version_is_a_conflict(self):
        stale = self.rec(self.two)
        svc.edit(self.profile, self.user, "item", self.two.pk, {"text": "dos"})
        resp = self.post("edit_move", {**stale, "direction": "up"})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(self.order(), ["one", "dos", "S", "three", "four"])

    def test_a_section_move_to_another_place_shows_the_renumbering_first(self):
        sub = self.make("subtopic", ("topic", self.topic.pk), name="Sub")
        data = {**self.rec(self.sec), "parent": f"subtopic:{sub.pk}"}
        resp = self.post("edit_move", data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["title"], "Move")
        self.assertEqual({c["id"] for c in resp.context["changes"]}, {self.three.pk, self.four.pk})
        self.assertEqual(self.get(self.sec).topic_id, self.topic.pk)
        resp = self.post("edit_move", {**data, "confirmed": "1"})
        self.assertRedirects(resp, self.next, fetch_redirect_response=False)
        moved = self.get(self.sec)
        self.assertEqual((moved.subtopic_id, moved.topic_id), (sub.pk, None))
        self.assertEqual(self.numbered(self.topic), [("(1)", "one"), ("(2)", "two"), ("(3)", "three"), ("(4)", "four")])

    def test_move_an_item_to_a_subtopic(self):
        sub = self.make("subtopic", ("topic", self.topic.pk), name="Sub")
        data = {**self.rec(self.one), "parent": f"subtopic:{sub.pk}"}
        resp = self.post("edit_move", data)
        self.assertEqual([c["id"] for c in resp.context["changes"]], [self.two.pk])
        self.post("edit_move", {**data, "confirmed": "1"})
        moved = self.get(self.one)
        self.assertEqual((moved.subtopic_id, moved.topic_id, moved.position), (sub.pk, None, 1))
        self.assertEqual(self.numbered(self.topic), [("(1)", "two"), ("(a)", "S"), ("(1)", "three"), ("(2)", "four")])

    def test_move_a_subtopic_to_another_topic(self):
        topic2 = self.make("topic", ("subject", self.subject.pk), name="Second")
        sub = self.make("subtopic", ("topic", self.topic.pk), name="Sub")
        self.post("edit_move", {**self.rec(sub), "parent": f"topic:{topic2.pk}", "confirmed": "1"})
        self.assertEqual(self.get(sub).topic_id, topic2.pk)

    def test_a_refused_move_is_a_message_and_changes_nothing(self):
        data = {**self.rec(self.two), "parent": f"item:{self.one.pk}"}
        for extra in ({}, {"confirmed": "1"}):
            resp = self.post("edit_move", {**data, **extra})
            self.assertEqual(resp.status_code, 302)
            self.assertTrue(self.msgs(resp))
        self.assertEqual(self.order(), ["one", "two", "S", "three", "four"])

    def test_a_topic_cannot_go_inside_a_subtopic(self):
        sub = self.make("subtopic", ("topic", self.topic.pk), name="Sub")
        resp = self.post("edit_move", {**self.rec(self.topic), "parent": f"subtopic:{sub.pk}", "confirmed": "1"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.get(self.topic).subject_id, self.subject.pk)

    def test_malformed_places_give_404(self):
        for parent in ("nonsense", "topic:x", "note:1"):
            resp = self.post("edit_move", {**self.rec(self.one), "parent": parent})
            self.assertEqual(resp.status_code, 404, parent)


class PickerTests(EditViewTestCase):
    def entries(self, obj):
        resp = self.post("edit_move_to", self.rec(obj))
        self.assertEqual(resp.status_code, 200)
        return resp, {(e["type"], e["id"]): e for e in resp.context["entries"]}

    def test_the_picker_lists_this_profile_only_with_valid_places_pickable(self):
        sub = self.make("subtopic", ("topic", self.topic.pk), name="Sub")
        nested = self.make("item", ("topic", self.topic.pk), kind="nested", text="group")
        self.make("subject", profile=self.other_profile, name="Foreign")
        resp, found = self.entries(self.one)
        self.assertNotContains(resp, "Foreign")
        self.assertTrue(found[("subject", self.subject.pk)]["pick"])
        self.assertTrue(found[("topic", self.topic.pk)]["pick"])
        self.assertTrue(found[("subtopic", sub.pk)]["pick"])
        self.assertTrue(found[("item", nested.pk)]["pick"])
        self.assertNotIn(("item", self.one.pk), found)
        self.assertEqual(found[("subtopic", sub.pk)]["depth"], 2)

    def test_a_topic_can_only_go_under_a_subject(self):
        sub = self.make("subtopic", ("topic", self.topic.pk), name="Sub")
        _, found = self.entries(self.topic)
        self.assertTrue(found[("subject", self.subject.pk)]["pick"])
        self.assertFalse(found[("topic", self.topic.pk)]["pick"])
        self.assertFalse(found[("subtopic", sub.pk)]["pick"])

    def test_a_nested_item_cannot_go_beneath_another_nested_item(self):
        nested = self.make("item", ("topic", self.topic.pk), kind="nested", text="group")
        other = self.make("item", ("topic", self.topic.pk), kind="nested", text="other group")
        _, found = self.entries(nested)
        self.assertFalse(found[("item", other.pk)]["pick"])
        self.assertTrue(found[("topic", self.topic.pk)]["pick"])

    def test_picker_choices_post_to_the_move_endpoint(self):
        resp, _ = self.entries(self.one)
        self.assertContains(resp, f'value="topic:{self.topic.pk}"')
        self.assertContains(resp, reverse("edit_move"))


class LandingTests(EditViewTestCase):
    def test_a_subject_moves_to_other_subjects_and_back(self):
        tort = self.make("subject", name="Tort")
        resp = self.post("edit_landing", {**self.rec(self.subject), "show": "0"})
        self.assertRedirects(resp, self.next, fetch_redirect_response=False)
        moved = self.get(self.subject)
        self.assertEqual((moved.show_on_landing, moved.other_acts_position), (False, 1))
        self.assertEqual(self.get(tort).landing_position, 2)
        self.post("edit_landing", {**self.rec(self.subject), "show": "1"})
        back = self.get(self.subject)
        self.assertEqual((back.show_on_landing, back.landing_position), (True, 3))  # next free stored number
        self.assertEqual(self.get(tort).landing_position, 2)  # the list it left is not renumbered

    def test_stale_version_is_a_conflict(self):
        stale = self.rec(self.subject)
        svc.edit(self.profile, self.user, "subject", self.subject.pk, {"name": "Renamed"})
        resp = self.post("edit_landing", {**stale, "show": "0"})
        self.assertEqual(resp.status_code, 409)
        self.assertTrue(self.get(self.subject).show_on_landing)


class AlphabeticalHeadingTests(EditViewTestCase):
    """Subjects, Topics and Sub-topics are listed alphabetically everywhere; only Sections and Items can be reordered."""

    def order_in(self, html, names):
        spots = [html.index(n) for n in names]
        self.assertEqual(spots, sorted(spots), names)

    def test_subjects_index_lists_each_group_alphabetically_with_numbers_as_numbers(self):
        for name in ("S. 11", "S. 9", "Banana", "apple"):
            self.make("subject", name=name)
        for name in ("Zz 10", "Zz 2", "Mm"):
            self.make("subject", name=name, show_on_landing=False)
        html = self.client.get(reverse("diary_home")).content.decode()
        self.order_in(html, [">apple<", ">Banana<", ">Contract<", ">S. 9<", ">S. 11<"])
        self.order_in(html, [">Mm<", ">Zz 2<", ">Zz 10<"])
        self.assertLess(html.index(">S. 11<"), html.index('class="other-divider"'))
        self.assertLess(html.index('class="other-divider"'), html.index(">Mm<"))

    def test_topics_and_subtopics_are_read_alphabetically_and_lettered_in_that_order(self):
        zed = self.make("topic", ("subject", self.subject.pk), name="Zed")
        apple = self.make("topic", ("subject", self.subject.pk), name="Apple")
        self.make("subtopic", ("topic", apple.pk), name="Time 10")
        self.make("subtopic", ("topic", apple.pk), name="Time 9")
        html = self.client.get(reverse("read_subject", args=[self.subject.pk])).content.decode()
        self.order_in(html, ["Apple", "Formation", "Zed"])
        self.order_in(html, ["Time 9", "Time 10"])
        # Letters follow the alphabet: Apple is A, Formation B, Zed C.
        from diary.services.sequences import ident, labels, members

        key = ("topic", "subject", self.subject.pk)
        objs = members(self.profile.pk, key)
        gen = labels(key, objs, {"topic_format": "A"})
        self.assertEqual([(gen[ident(o)], o.name) for o in objs], [("A", "Apple"), ("B", "Formation"), ("C", "Zed")])
        self.assertEqual(self.get(zed).position, 2)

    def test_adding_headings_never_touches_their_siblings(self):
        zed = self.make("topic", ("subject", self.subject.pk), name="Zed")
        self.add_heading("topic", name="Alpha", first="1")
        self.add_heading("topic", name="Mid")
        after = {"what": "topic", "name": "Beta", "after": "%s:%d" % self.ref(zed), "after_version": 1}
        self.post("edit_add", after)
        for obj, pos in ((self.topic, 1), (zed, 2)):
            row = self.get(obj)
            self.assertEqual((row.position, row.version), (pos, 1))
            self.assertEqual(self.history_kinds(obj), ["create"])
        names = [t.name for t in Topic.objects.filter(subject=self.subject).order_by("position")]
        self.assertEqual(names, ["Formation", "Zed", "Alpha", "Mid", "Beta"])  # stored order = creation order
        from diary.services.sequences import members

        shown = [t.name for t in members(self.profile.pk, ("topic", "subject", self.subject.pk))]
        self.assertEqual(shown, ["Alpha", "Beta", "Formation", "Mid", "Zed"])

    def add_heading(self, what, **fields):
        return self.post("edit_add", {"what": what, "parent_type": "subject", "parent_id": self.subject.pk, **fields})

    def test_headings_have_no_drag_grip_but_sections_and_items_do(self):
        self.make("topic", ("subject", self.subject.pk), name="Second")
        self.make("subtopic", ("topic", self.topic.pk), name="Sub")
        html = self.client.get(self.next).content.decode()
        by_kind = {}
        for kind, rest in re.findall(r'<div[^>]*?data-edit-row data-kind="(\w+)"([^>]*)>', html):
            by_kind.setdefault(kind, []).append(rest)
        for kind in ("subject", "topic", "subtopic"):
            self.assertTrue(by_kind[kind], kind)
            for rest in by_kind[kind]:
                self.assertNotIn("data-run", rest, kind)
        for kind in ("item", "section"):
            self.assertTrue(by_kind[kind], kind)
            for rest in by_kind[kind]:
                self.assertRegex(rest, r'data-run="[^"]+"', kind)
        self.assertEqual(html.count("data-drag-handle"), len(by_kind["item"]) + len(by_kind["section"]))

    def test_move_to_another_parent_lands_alphabetically_and_previews_the_new_letters(self):
        s2 = self.make("subject", name="Torts")
        self.make("topic", ("subject", s2.pk), name="Aaa")
        self.make("topic", ("subject", s2.pk), name="Zzz")
        data = {**self.rec(self.topic), "parent": f"subject:{s2.pk}"}
        resp = self.post("edit_move", data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["title"], "Move")
        self.assertTrue(resp.context["changes"])  # Zzz goes from B to C
        self.assertEqual(self.get(self.topic).subject_id, self.subject.pk)
        self.post("edit_move", {**data, "confirmed": "1"})
        from diary.services.sequences import members

        shown = [t.name for t in members(self.profile.pk, ("topic", "subject", s2.pk))]
        self.assertEqual(shown, ["Aaa", "Formation", "Zzz"])
        self.assertEqual(self.get(self.topic).position, 3)

    def test_moving_a_subtopic_to_another_topic_lands_alphabetically(self):
        t2 = self.make("topic", ("subject", self.subject.pk), name="Second")
        self.make("subtopic", ("topic", t2.pk), name="Bbb")
        self.make("subtopic", ("topic", t2.pk), name="Ddd")
        mine = self.make("subtopic", ("topic", self.topic.pk), name="Ccc")
        preview = svc.preview_move(self.profile, self.user, "subtopic", mine.pk, ("topic", t2.pk))
        self.assertEqual([(c["label"], c["before"], c["after"]) for c in preview["changes"]],
            [("Ccc", "1", "2"), ("Ddd", "2", "3")],  # the moved one is listed too: 1st of its old topic, 2nd of the new
        )
        svc.move(self.profile, self.user, "subtopic", mine.pk, ("topic", t2.pk))
        from diary.services.sequences import members

        self.assertEqual([s.name for s in members(self.profile.pk, ("subtopic", "topic", t2.pk))], ["Bbb", "Ccc", "Ddd"])

    def test_a_move_to_the_parent_it_already_has_changes_nothing(self):
        result = svc.move(self.profile, self.user, "topic", self.topic.pk, ("subject", self.subject.pk))
        self.assertFalse(result.changed)
        self.assertEqual(self.get(self.topic).version, 1)

    def test_the_move_to_picker_lists_headings_alphabetically(self):
        self.make("subject", name="Aardvark")
        self.make("subject", name="Other act", show_on_landing=False)
        self.make("topic", ("subject", self.subject.pk), name="Abc")
        resp = self.post("edit_move_to", self.rec(self.one))
        names = [e["label"] for e in resp.context["entries"] if e["type"] in ("subject", "topic")]
        self.assertEqual(names, ["Aardvark", "Contract", "Abc", "Formation", "Other act"])

    def test_restoring_a_heading_from_the_trash_puts_it_back_in_the_alphabet(self):
        a = self.make("topic", ("subject", self.subject.pk), name="Alpha")
        svc.delete(self.profile, self.user, "topic", a.pk)
        svc.restore(self.profile, self.user, "topic", a.pk)
        from diary.services.sequences import members

        shown = [t.name for t in members(self.profile.pk, ("topic", "subject", self.subject.pk))]
        self.assertEqual(shown, ["Alpha", "Formation"])
        self.assertEqual(self.get(self.topic).version, 1)

    def test_the_reading_page_and_its_side_panel_use_the_alphabet(self):
        self.make("topic", ("subject", self.subject.pk), name="Aaa")
        resp = self.client.get(reverse("read_subject", args=[self.subject.pk]))
        self.order_in(resp.content.decode(), ["Aaa", "Formation"])
