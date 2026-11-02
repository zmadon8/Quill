"""Edit mode endpoints (Milestone 3b): roles, profile isolation, POST only, CSRF, each action and its renumbering."""
from django.contrib.messages import get_messages
from django.test import Client, override_settings
from django.urls import reverse

from diary import services as svc
from diary.models import Item, Section, Subject, Subtopic, Topic
from diary.tests.helpers import join_main
from diary.tests.service_helpers import ServiceTestCase

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

    def test_readers_see_no_edit_controls_and_editors_see_them_only_in_edit_mode(self):
        url = reverse("read_subject", args=[self.subject.pk])
        for query in ("", "?edit=1"):
            resp = self.reader_client.get(url + query)
            self.assertEqual(resp.status_code, 200)
            self.assertNotContains(resp, "data-edit-bar")
            self.assertNotContains(resp, "Edit mode")
            self.assertNotContains(resp, "edit-mode.js")
        plain = self.client.get(url)
        self.assertContains(plain, "Edit mode")
        self.assertNotContains(plain, "data-edit-bar")
        editing = self.client.get(url + "?edit=1")
        self.assertContains(editing, "data-edit-bar")
        self.assertContains(editing, "data-drag-handle")
        self.assertContains(editing, "Done editing")
        self.assertContains(editing, "edit-mode.js")

    def test_subject_lists_show_controls_only_to_editors_in_edit_mode(self):
        self.assertNotContains(self.reader_client.get(reverse("subjects") + "?edit=1"), "data-edit-bar")
        self.assertNotContains(self.client.get(reverse("subjects")), "data-edit-bar")
        self.assertContains(self.client.get(reverse("subjects") + "?edit=1"), "data-edit-bar")
        self.make("subject", name="Elsewhere", show_on_landing=False)
        # Both lists are on the one page, each its own reorder run.
        resp = self.client.get(reverse("subjects") + "?edit=1")
        self.assertContains(resp, 'data-run="subject-show-1"')
        self.assertContains(resp, 'data-run="subject-show-0"')

    def test_next_address_must_stay_on_this_site(self):
        for bad in ("https://evil.example/", "//evil.example/x", "javascript:alert(1)"):
            resp = self.post("edit_rename", {"kind": "topic", "id": self.topic.pk, "name": "Formation", "next": bad})
            self.assertRedirects(resp, reverse("subjects"), fetch_redirect_response=False)


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
        self.assertEqual(new.citation, "(2020) 1 SCC 1")
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
        self.assertEqual(topic.position, 2)
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

    def test_a_citation_is_saved_for_an_item_and_a_nested_item(self):
        self.add("item", ("topic", self.topic.pk), text="one more", citation=" A v B ")
        self.add("nested", ("topic", self.topic.pk), text="n", citation="C v D")
        self.assertEqual(Item.objects.get(topic=self.topic, text="<p>one more</p>").citation, "A v B")
        self.assertEqual(Item.objects.get(topic=self.topic, text="<p>n</p>").citation, "C v D")

    def test_the_edit_page_has_one_text_box_and_a_disabled_citation_for_a_subject(self):
        resp = self.client.get(self.next)
        html = resp.content.decode()
        self.assertContains(resp, "data-add-form")
        self.assertContains(resp, "data-add-citation")
        self.assertNotContains(resp, "Name (headings and Sections)")
        self.assertNotContains(resp, "Text (Items)")
        # The form inside the Subject's edit bar starts on Topic, so its Citation box is rendered disabled.
        first = html[html.index("data-add-form"):]
        self.assertRegex(first[: first.index("</form>")], r'data-add-citation disabled')
        # A Topic's form starts on Item, so its Citation box is enabled.
        second = first[first.index("data-add-form", 10):]
        self.assertNotRegex(second[: second.index("</form>")], r'data-add-citation disabled')

    def test_the_edit_buttons_are_icons_with_labels_and_titles(self):
        resp = self.client.get(self.next)
        for label in ("Move up", "Move down", "Edit", "History", "Delete", "Move to", "Mark for review", "Rename", "Add"):
            self.assertContains(resp, f'aria-label="{label}" title="{label}"')
        self.assertContains(resp, "Drag to reorder")
        self.assertContains(resp, 'class="icon"')

    def test_choosing_nothing_to_add_is_refused(self):
        resp = self.post("edit_add", {"what": "", "parent_type": "topic", "parent_id": self.topic.pk})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(self.msgs(resp))


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
        self.assertRedirects(resp, reverse("subjects"), fetch_redirect_response=False)
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

    def test_up_and_down_for_headings_and_subjects(self):
        topic2 = self.make("topic", ("subject", self.subject.pk), name="Second")
        self.post("edit_move", {**self.rec(topic2), "direction": "up"})
        self.assertEqual(self.positions([topic2, self.topic]), [1, 2])
        other = self.make("subject", name="Tort")
        self.post("edit_move", {**self.rec(other), "direction": "up"})
        self.assertEqual((self.get(other).landing_position, self.get(self.subject).landing_position), (1, 2))

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
        self.assertEqual(self.get(tort).landing_position, 1)
        self.post("edit_landing", {**self.rec(self.subject), "show": "1"})
        back = self.get(self.subject)
        self.assertEqual((back.show_on_landing, back.landing_position), (True, 2))

    def test_stale_version_is_a_conflict(self):
        stale = self.rec(self.subject)
        svc.edit(self.profile, self.user, "subject", self.subject.pk, {"name": "Renamed"})
        resp = self.post("edit_landing", {**stale, "show": "0"})
        self.assertEqual(resp.status_code, 409)
        self.assertTrue(self.get(self.subject).show_on_landing)
