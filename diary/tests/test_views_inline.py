"""The inline Edit mode endpoints (Round 7): the "+ Add" form and editing card fragments, and the fetch (JSON) answers of the
existing change endpoints. Roles, profile scoping, stale saves, the kinds offered per row, placement, no explanatory text."""
from django.urls import reverse

from diary.models import Case, Item, Subtopic, Topic
from diary.tests.test_views_edit import FETCH, EditViewTestCase
from diary.undo_session import SESSION_KEY


class InlineTestCase(EditViewTestCase):
    def fetch(self, name, data=None, client=None, args=None):
        data = dict(data or {})
        data.setdefault("next", self.next)
        return (client or self.client).post(reverse(name, args=args), data, **FETCH)

    def form(self, ref, client=None):
        return (client or self.client).get(reverse("edit_inline_add"), {"ref": ref, "next": self.next})

    def card(self, kind, obj, client=None):
        return (client or self.client).get(reverse("edit_inline_card"), {"kind": kind, "id": obj.pk, "next": self.next})

    def choices(self, ref):
        return [c["value"] for c in self.form(ref).json()["choices"]]

    def add(self, ref, choice, obj, **fields):
        data = {"ref": ref, "choice": choice, "after_version": self.get(obj).version, **fields}
        return self.fetch("edit_add", data)


class InlineAccessTests(InlineTestCase):
    def test_readers_get_403_on_the_fragments_and_the_fetch_changes(self):
        ref = "item:%d" % self.one.pk
        self.assertEqual(self.form(ref, client=self.reader_client).status_code, 403)
        self.assertEqual(self.card("item", self.one, client=self.reader_client).status_code, 403)
        reader = self.fetch("edit_add", {"ref": ref, "choice": "after:item", "text": "x"}, client=self.reader_client)
        self.assertEqual(reader.status_code, 403)
        for name, data in (("edit_delete", {"kind": "item", "id": self.two.pk}),
                           ("edit_move", {"kind": "item", "id": self.two.pk, "direction": "up"}),
                           ("edit_rename", {"kind": "topic", "id": self.topic.pk, "name": "x"})):
            self.assertEqual(self.fetch(name, data, client=self.reader_client).status_code, 403, name)
        self.assertEqual(self.fetch("edit_item", {"text": "x"}, client=self.reader_client, args=[self.two.pk]).status_code, 403)
        self.assertIsNone(self.get(self.two).deleted_at)
        self.assertEqual(Item.objects.filter(topic=self.topic).count(), 4)
        self.assertEqual(self.order(), ["one", "two", "S", "three", "four"])

    def test_the_fragments_only_answer_get(self):
        self.assertEqual(self.client.post(reverse("edit_inline_add"), {}).status_code, 405)
        self.assertEqual(self.client.post(reverse("edit_inline_card"), {}).status_code, 405)

    def test_another_profiles_records_are_404(self):
        subject = self.make("subject", profile=self.other_profile, name="Elsewhere")
        topic = self.make("topic", ("subject", subject.pk), profile=self.other_profile, name="T")
        foreign = self.make("item", ("topic", topic.pk), profile=self.other_profile, text="foreign")
        self.assertEqual(self.form("item:%d" % foreign.pk).status_code, 404)
        self.assertEqual(self.card("item", foreign).status_code, 404)
        self.assertEqual(self.fetch("edit_add", {"ref": "item:%d" % foreign.pk, "choice": "after:item", "text": "x"}).status_code, 404)
        self.assertEqual(self.fetch("edit_delete", {"kind": "item", "id": foreign.pk}).status_code, 404)
        self.assertEqual(Item.objects.filter(topic=topic).count(), 1)

    def test_bad_references_are_404(self):
        for bad in ("", "item", "item:x", "bogus:1", "item:999999", "note:1"):
            self.assertEqual(self.form(bad).status_code, 404, bad)
        self.assertEqual(self.client.get(reverse("edit_inline_card"), {"kind": "note", "id": self.one.pk}).status_code, 404)
        self.assertEqual(self.client.get(reverse("edit_inline_card"), {"kind": "item", "id": "x"}).status_code, 404)


class AddFormTests(InlineTestCase):
    def test_after_an_item_or_a_section_the_choices_are_item_section(self):
        self.assertEqual(self.choices("item:%d" % self.one.pk), ["after:item", "after:section", "inside:note"])
        self.assertEqual(self.choices("section:%d" % self.sec.pk), ["after:item", "after:section", "inside:note"])

    def test_after_a_topic_the_choices_are_item_inside_subtopic_topic(self):
        body = self.form("topic:%d" % self.topic.pk).json()
        self.assertEqual([(c["value"], c["label"]) for c in body["choices"]],
                         [("inside:item", "Item inside"), ("inside:subtopic", "Sub-topic"), ("inside:note", "Note"),
                          ("after:topic", "Topic")])

    def test_after_a_subtopic_the_choices_are_item_inside_and_subtopic(self):
        sub = self.make("subtopic", ("topic", self.topic.pk), name="General")
        body = self.form("subtopic:%d" % sub.pk).json()
        self.assertEqual([(c["value"], c["label"]) for c in body["choices"]],
                         [("inside:item", "Item inside"), ("inside:note", "Note"), ("after:subtopic", "Sub-topic")])

    def test_every_subject_offers_item_topic_and_note(self):
        # D81: Subjects under Other Subjects are treated like any other, and a Sub-topic always sits in a Topic.
        self.assertEqual(self.choices("subject:%d" % self.subject.pk), ["inside:item", "inside:topic", "inside:note"])
        other = self.make("subject", name="Other Acts", show_on_landing=False)
        self.make("topic", ("subject", other.pk), name="Existing")
        self.assertEqual(self.choices("subject:%d" % other.pk), ["inside:item", "inside:topic", "inside:note"])
        empty = self.make("subject", name="Empty")
        self.assertEqual(self.choices("subject:%d" % empty.pk), ["inside:item", "inside:topic", "inside:note"])

    def test_the_form_has_segmented_choices_citations_and_the_no_javascript_link(self):
        body = self.form("item:%d" % self.one.pk).json()
        html = body["html"]
        self.assertIn('name="choice"', html)
        self.assertIn('name="case_citation"', html)
        self.assertIn('name="case_comment"', html)
        self.assertIn("+ another citation", html)
        self.assertIn('name="after_version" value="%d"' % self.get(self.one).version, html)


class AddTests(InlineTestCase):
    def test_item_after_a_row_comes_back_as_row_html_in_the_right_place(self):
        resp = self.add("item:%d" % self.two.pk, "after:item", self.two, text="typed", text_format="html")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        new = Item.objects.get(topic=self.topic, text_plain="typed")
        self.assertEqual((body["ok"], body["id"], body["kind"]), (True, new.pk, "item"))
        self.assertEqual(body["element"], "n-item-%d" % new.pk)
        self.assertEqual(body["after_anchor"], "n-item-%d" % self.two.pk)
        self.assertIn("typed", body["html"])
        self.assertEqual(body["labels"]["n-item-%d" % new.pk], "(3)")
        self.assertEqual(body["labels"]["n-item-%d" % self.three.pk], "(1)")  # after Section S the numbers start again
        self.assertEqual(self.order(), ["one", "two", "typed", "S", "three", "four"])
        self.assertTrue(body["undo"]["text"].startswith("Added"))

    def test_nested_item_is_not_a_choice_and_a_section_goes_after_an_item(self):
        resp = self.add("item:%d" % self.one.pk, "after:nested", self.one, text="a nested", citation="N v M")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Item.objects.filter(text_plain="a nested").exists())
        body = self.add("item:%d" % self.one.pk, "after:section", self.one, text="Early").json()
        self.assertEqual(self.order()[:2], ["one", "Early"])
        self.assertTrue(body["element"].startswith("row-n-section-"))
        self.assertEqual(body["after_anchor"], "n-item-%d" % self.one.pk)

    def test_item_inside_a_topic_goes_first(self):
        self.add("topic:%d" % self.topic.pk, "inside:item", self.topic, text="top")
        self.assertEqual(self.order()[:2], ["top", "one"])

    def test_several_citations_with_comments_become_cases_in_order(self):
        body = self.add("item:%d" % self.one.pk, "after:item", self.one, text="with cases",
                        case_citation=["A v B [(2020) 1 SCC 1]", "", "C v D"], case_comment=["@ para 22", "", ""]).json()
        item = Item.objects.get(topic=self.topic, text_plain="with cases")
        cases = list(Case.objects.filter(item=item).order_by("position").values_list("citation", "comment_plain", "position"))
        self.assertEqual([(c[0], c[1]) for c in cases], [("A v B [(2020) 1 SCC 1]", "@ para 22"), ("C v D", "")])
        self.assertEqual([c[2] for c in cases], [1, 2])
        self.assertIn("A v B", body["html"])

    def test_citation_only_is_enough_and_nothing_is_added_when_empty(self):
        self.assertEqual(self.add("item:%d" % self.one.pk, "after:item", self.one, text=" ", case_citation=["X v Y"]).status_code, 200)
        before = Item.objects.filter(topic=self.topic).count()
        resp = self.add("item:%d" % self.one.pk, "after:item", self.one, text=" ", case_citation=[""], case_comment=[""])
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(resp.json()["errors"])
        self.assertEqual(Item.objects.filter(topic=self.topic).count(), before)

    def test_headings_go_to_their_alphabetical_place(self):
        later = self.make("topic", ("subject", self.subject.pk), name="Zeta")
        body = self.add("topic:%d" % self.topic.pk, "after:topic", self.topic, text="Alpha").json()
        self.assertTrue(body["reload"])
        names = [t.name for t in Topic.objects.filter(subject=self.subject, deleted_at__isnull=True).order_by("name")]
        self.assertEqual(names, ["Alpha", "Formation", "Zeta"])
        self.assertEqual(self.get(later).version, 1)
        body = self.add("topic:%d" % self.topic.pk, "inside:subtopic", self.topic, text="General").json()
        sub = Subtopic.objects.get(name="General")
        self.assertEqual(sub.topic_id, self.topic.pk)
        self.assertTrue(body["reload"])

    def test_subtopic_after_a_subtopic_has_the_same_parent(self):
        sub = self.make("subtopic", ("topic", self.topic.pk), name="General")
        self.add("subtopic:%d" % sub.pk, "after:subtopic", sub, text="Another")
        self.assertEqual(Subtopic.objects.get(name="Another").topic_id, self.topic.pk)

    def test_a_choice_the_row_does_not_offer_is_refused(self):
        for ref, choice in (("item:%d" % self.one.pk, "after:topic"), ("topic:%d" % self.topic.pk, "after:section"),
                            ("item:%d" % self.one.pk, "inside:item"), ("item:%d" % self.one.pk, "bogus")):
            resp = self.fetch("edit_add", {"ref": ref, "choice": choice, "text": "x"})
            self.assertEqual(resp.status_code, 400, (ref, choice))
        self.assertEqual(self.order(), ["one", "two", "S", "three", "four"])

    def test_a_stale_row_gives_a_json_conflict_with_the_address_of_the_conflict_screen(self):
        stale = self.get(self.one).version
        from diary import services as svc

        svc.edit(self.profile, self.user2, "item", self.one.pk, {"text": "changed elsewhere"})
        resp = self.fetch("edit_add", {"ref": "item:%d" % self.one.pk, "choice": "after:item", "after_version": stale, "text": "n"})
        self.assertEqual(resp.status_code, 409)
        body = resp.json()
        self.assertEqual((body["ok"], body["conflict"], body["conflict_url"]), (False, True, reverse("edit_add")))
        self.assertFalse(Item.objects.filter(text_plain="n").exists())
        # The same form sent without fetch gets the existing conflict screen.
        page = self.client.post(reverse("edit_add"), {"ref": "item:%d" % self.one.pk, "choice": "after:item",
                                                      "after_version": stale, "text": "n", "next": self.next})
        self.assertEqual(page.status_code, 409)


class CardTests(InlineTestCase):
    def test_item_card_has_text_citations_flag_and_the_more_menu(self):
        self.make("case", ("item", self.one.pk), citation="A v B", comment="@ para 22")
        body = self.card("item", self.one).json()
        html = body["html"]
        self.assertEqual(body["version"], self.get(self.one).version)
        for needle in ('name="text"', 'name="case_citation"', 'value="A v B"', "@ para 22", 'name="case_id"',
                       '<select name="flag"', 'value="pending"', 'name="flag_text"',
                       "+ another citation", "Move to", "Move up", "Move down", "History",
                       "Delete", "goes to Trash"):
            self.assertIn(needle, html, needle)
        self.assertNotIn("Change to", html)
        self.assertNotIn("Nested", html)
        self.assertNotIn('name="needs_review"', html)
        self.assertIn('action="%s"' % reverse("edit_item", args=[self.one.pk]), html)
        for text in ("None", "Overruled", "Doubted", "Other"):
            self.assertIn(text, html)

    def test_show_citations_control_is_hidden_until_there_are_two_citations(self):
        self.make("case", ("item", self.one.pk), citation="A v B")
        self.assertIn("data-layout-control hidden", self.card("item", self.one).json()["html"])
        self.make("case", ("item", self.one.pk), citation="C v D")
        html = self.card("item", self.one).json()["html"]
        self.assertNotIn("data-layout-control hidden", html)
        self.assertIn('name="citation_layout" value="inline" checked', html)
        self.assertIn('name="citation_layout" value="lines"', html)
        self.assertIn("On separate lines", html)

    def test_saving_the_card_sets_the_citation_layout(self):
        first = self.make("case", ("item", self.one.pk), citation="A v B")
        second = self.make("case", ("item", self.one.pk), citation="C v D")
        data = {"version": self.get(self.one).version, "text": "<p>one</p>", "flag": "none", "citation_layout": "lines",
                "case_id": [first.pk, second.pk], "case_version": [self.get(first).version, self.get(second).version],
                "case_citation": ["A v B", "C v D"], "case_comment": ["", ""]}
        body = self.fetch("edit_item", data, args=[self.one.pk]).json()
        self.assertTrue(body["ok"])
        self.assertEqual(self.get(self.one).citation_layout, "lines")
        self.assertIn("case-lines", body["html"])

    def test_heading_card_is_the_name_and_more_only_with_no_explanatory_text(self):
        for kind, obj in (("topic", self.topic), ("subject", self.subject)):
            html = self.card(kind, obj).json()["html"]
            self.assertIn('name="name"', html)
            self.assertIn('value="%s"' % obj.name, html)
            self.assertIn("History", html)
            self.assertIn("Delete", html)
            for absent in ("sorted", "A\u2013Z", "A-Z", "alphabet", "automatically", 'name="text"', "Move up", "Move down",
                           'name="flag"', "For review", "Change to"):
                self.assertNotIn(absent, html, (kind, absent))
        self.assertIn("Move to", self.card("topic", self.topic).json()["html"])
        self.assertNotIn("Move to", self.card("subject", self.subject).json()["html"])

    def test_subject_card_can_change_the_landing_page_place(self):
        html = self.card("subject", self.subject).json()["html"]
        self.assertIn('data-more-action="landing"', html)
        self.assertIn("Put under Other Subjects", html)

    def test_cards_have_the_phone_top_bar_and_a_blank_citation_template(self):
        html = self.card("item", self.one).json()["html"]
        self.assertIn('class="editcard"', html)
        self.assertIn("card-top", html)
        self.assertIn("data-case-template", html)
        self.assertIn("data-case-grip", html)
        self.assertIn("goes to Trash", html)

    def test_section_card_has_name_flag_and_move_up_down(self):
        html = self.card("section", self.sec).json()["html"]
        for needle in ('name="name"', '<select name="flag"', 'name="flag_text"', 'name="flag_form"', "Move up", "Move down", "Move to"):
            self.assertIn(needle, html, needle)
        self.assertNotIn("Change to", html)


class SaveTests(InlineTestCase):
    def save_data(self, obj, **fields):
        data = {"version": self.get(obj).version, "text": "<p>edited</p>", "flag": "none", "flag_text": "",
                "case_id": [""], "case_version": [""], "case_citation": ["A v B"], "case_comment": ["@ para 1"]}
        data.update(fields)
        return data

    def test_item_save_gives_the_new_row(self):
        resp = self.fetch("edit_item", self.save_data(self.one, flag="doubted", flag_text="check"),
                          args=[self.one.pk])
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["element"], "n-item-%d" % self.one.pk)
        self.assertIn("edited", body["html"])
        self.assertIn("A v B", body["html"])
        self.assertIn("check", body["html"])
        item = self.get(self.one)
        self.assertEqual((item.flag, item.flag_text), ("doubted", "check"))
        self.assertEqual(list(Case.objects.filter(item=item).values_list("citation", flat=True)), ["A v B"])
        self.assertTrue(body["undo"]["group"])

    def test_item_save_cases_can_be_removed_and_reordered(self):
        a = self.make("case", ("item", self.one.pk), citation="first")
        b = self.make("case", ("item", self.one.pk), citation="second")
        data = self.save_data(self.one, case_id=[b.pk, a.pk], case_version=[b.version, a.version],
                              case_citation=["second", "first"], case_comment=["", ""])
        self.assertEqual(self.fetch("edit_item", data, args=[self.one.pk]).status_code, 200)
        self.assertEqual(list(Case.objects.filter(item=self.one).order_by("position").values_list("citation", flat=True)),
                         ["second", "first"])
        data = self.save_data(self.one, case_id=[a.pk], case_version=[self.get(a).version],
                              case_citation=["first"], case_comment=[""], case_gone=["%d:%d" % (b.pk, self.get(b).version)])
        self.assertEqual(self.fetch("edit_item", data, args=[self.one.pk]).status_code, 200)
        live = Case.objects.filter(item=self.one, deleted_at__isnull=True)
        self.assertEqual(list(live.values_list("citation", flat=True)), ["first"])
        self.assertIsNotNone(self.get(b).deleted_at)  # the removed citation is in the Trash, not gone

    def test_a_stale_item_save_is_a_json_conflict_and_the_same_form_reaches_the_conflict_screen(self):
        from diary import services as svc

        data = self.save_data(self.one)
        svc.edit(self.profile, self.user2, "item", self.one.pk, {"text": "<p>theirs</p>"})
        resp = self.fetch("edit_item", data, args=[self.one.pk])
        self.assertEqual(resp.status_code, 409)
        body = resp.json()
        self.assertEqual((body["ok"], body["conflict"], body["conflict_url"]),
                         (False, True, reverse("edit_item", args=[self.one.pk])))
        self.assertEqual(self.get(self.one).text_plain, "theirs")
        page = self.client.post(body["conflict_url"], {**data, "next": self.next})
        self.assertEqual(page.status_code, 409)
        self.assertEqual(self.get(self.one).text_plain, "theirs")

    def test_a_refused_item_save_is_json_400(self):
        resp = self.fetch("edit_item", self.save_data(self.one, flag_text="x" * 2001, flag="other"), args=[self.one.pk])
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()["ok"])

    def test_rename_a_heading_asks_for_a_reload(self):
        resp = self.fetch("edit_rename", {"kind": "topic", "id": self.topic.pk, "version": self.get(self.topic).version,
                                          "name": "Contracts"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["reload"])
        self.assertEqual(self.get(self.topic).name, "Contracts")

    def test_stale_rename_is_a_json_conflict(self):
        stale = self.get(self.topic).version
        from diary import services as svc

        svc.edit(self.profile, self.user2, "topic", self.topic.pk, {"name": "Theirs"})
        resp = self.fetch("edit_rename", {"kind": "topic", "id": self.topic.pk, "version": stale, "name": "Mine"})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["conflict_url"], reverse("edit_rename"))
        self.assertEqual(self.get(self.topic).name, "Theirs")

    def test_section_card_saves_name_and_flag_together(self):
        resp = self.fetch("edit_rename", {"kind": "section", "id": self.sec.pk, "version": self.get(self.sec).version,
                                          "name": "Renamed", "flag_form": "1", "flag": "pending", "flag_text": "why"})
        body = resp.json()
        self.assertEqual(body["element"], "row-n-section-%d" % self.sec.pk)
        self.assertIn("[Pending: why]", body["html"])
        section = self.get(self.sec)
        self.assertEqual((section.name, section.flag, section.flag_text), ("Renamed", "pending", "why"))
        self.fetch("edit_rename", {"kind": "section", "id": self.sec.pk, "version": section.version, "name": "Renamed",
                                   "flag_form": "1", "flag": "none", "flag_text": "ignored"})
        section = self.get(self.sec)
        self.assertEqual((section.flag, section.flag_text), ("none", ""))


class MoreMenuTests(InlineTestCase):
    def test_delete_goes_to_trash_with_an_undo_step_and_new_numbers(self):
        resp = self.fetch("edit_delete", {"kind": "item", "id": self.one.pk, "version": self.get(self.one).version})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["deleted"])
        self.assertEqual(body["element"], "n-item-%d" % self.one.pk)
        self.assertEqual(body["labels"]["n-item-%d" % self.two.pk], "(1)")
        self.assertIsNotNone(self.get(self.one).deleted_at)
        self.assertTrue(body["undo"]["text"].startswith("Deleted"))
        self.assertEqual(self.client.session[SESSION_KEY][-1]["group"], body["undo"]["group"])
        undone = self.fetch("edit_undo", {"group": body["undo"]["group"]})
        self.assertEqual(undone.status_code, 200)
        self.assertTrue(undone.json()["undone"])
        self.assertIsNone(self.get(self.one).deleted_at)

    def test_deleting_a_section_names_its_wrapper_and_a_heading_asks_for_a_reload(self):
        body = self.fetch("edit_delete", {"kind": "section", "id": self.sec.pk, "version": self.get(self.sec).version}).json()
        self.assertEqual(body["element"], "row-n-section-%d" % self.sec.pk)
        body = self.fetch("edit_delete", {"kind": "topic", "id": self.topic.pk, "version": self.get(self.topic).version}).json()
        self.assertTrue(body["reload"])
        self.assertIsNotNone(self.get(self.topic).deleted_at)

    def test_a_stale_delete_is_a_json_conflict(self):
        stale = self.get(self.one).version
        from diary import services as svc

        svc.edit(self.profile, self.user2, "item", self.one.pk, {"text": "<p>theirs</p>"})
        resp = self.fetch("edit_delete", {"kind": "item", "id": self.one.pk, "version": stale})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["conflict_url"], reverse("edit_delete"))
        self.assertIsNone(self.get(self.one).deleted_at)

    def test_move_up_and_down(self):
        body = self.fetch("edit_move", {"kind": "item", "id": self.two.pk, "version": self.get(self.two).version,
                                        "direction": "up"}).json()
        self.assertTrue(body["ok"])
        self.assertEqual(self.order(), ["two", "one", "S", "three", "four"])
        self.fetch("edit_move", {"kind": "item", "id": self.two.pk, "version": self.get(self.two).version, "direction": "down"})
        self.assertEqual(self.order(), ["one", "two", "S", "three", "four"])

    def test_drag_drop_move_asks_for_a_reload(self):
        body = self.fetch("edit_move", {"kind": "item", "id": self.four.pk, "version": self.get(self.four).version,
                                        "index": "0", "confirmed": "1"}).json()
        self.assertEqual(self.order()[0], "four")
        self.assertTrue(body["reload"])

    def test_the_non_javascript_actions_still_work(self):
        resp = self.post("edit_delete", {"kind": "item", "id": self.one.pk, "version": self.get(self.one).version})
        self.assertEqual(resp.status_code, 200)  # the confirmation page, nothing deleted yet
        self.assertIsNone(self.get(self.one).deleted_at)
        resp = self.post("edit_move", {"kind": "item", "id": self.two.pk, "direction": "up"})
        self.assertEqual(resp.status_code, 302)


class ReadingTests(InlineTestCase):
    def test_a_lines_item_shows_each_citation_on_its_own_line_in_the_reading_row(self):
        item = self.make("item", ("topic", self.topic.pk), text="lines parent")
        self.make("case", ("item", item.pk), citation="A v B", comment="<p>first point</p>")
        self.make("case", ("item", item.pk), citation="C v D")
        Item.objects.filter(pk=item.pk).update(citation_layout="lines")
        html = self.client.get(reverse("read_subject", args=[self.subject.pk]) + "?edit=1").content.decode()
        start = html.index('id="n-item-%d"' % item.pk)
        chunk = html[start:start + 1500]
        self.assertIn('class="case-lines"', chunk)
        self.assertLess(chunk.index("first point"), chunk.index("A v B"))
        self.assertIn("(a)", chunk)
        self.assertIn("(b)", chunk)
