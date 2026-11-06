"""Diary round (items 1.1 to 1.7): the Demote picker, Add form Cancel and Save, wrapping citation box, the colon before
citations on separate lines, Justify text, the Other flag and Notes under their heading. Behaviour only."""
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from diary.models import Item
from diary.tests.test_views_edit import EditViewTestCase

ROOT = Path(__file__).resolve().parents[2]


def source(path):
    return (ROOT / path).read_text(encoding="utf-8")


class DemotePickerTests(EditViewTestCase):
    """1.1: Demote uses the same step-by-step picker as Move to; the current place is blue (picker-current)."""

    def setUp(self):
        super().setUp()
        self.other_subject = self.make("subject", name="Tort")
        self.other_topic = self.make("topic", ("subject", self.other_subject.pk), name="Duty")

    def level(self, obj, **extra):
        return self.post("edit_level", {**self.rec(obj), "direction": "demote", **extra})

    def test_a_topic_demote_shows_the_tree_not_one_long_select(self):
        html = self.level(self.topic).content.decode()
        self.assertNotIn("<select", html)
        self.assertIn("data-picker-toggle", html)
        self.assertIn("data-picker-expand-all", html)
        self.assertIn(f'name="target" value="{self.other_topic.pk}"', html)
        self.assertNotIn(f'value="{self.topic.pk}" class="picker-choice', html)  # not under itself
        # A Subject is only a heading to walk through, so it cannot be picked for a Topic.
        self.assertIn("picker-no", html)

    def test_the_current_subject_is_blue_not_a_choice_of_its_own_colour(self):
        html = self.level(self.topic).content.decode()
        self.assertRegex(html, r'class="picker-no picker-current">Contract')
        self.assertEqual(html.count("picker-current"), 1)

    def test_move_to_marks_the_current_place_the_same_way(self):
        html = self.post("edit_move_to", self.rec(self.one)).content.decode()
        self.assertRegex(html, r'class="picker-choice picker-current">Contract')

    def test_a_subject_demote_lists_the_other_subjects_to_pick(self):
        html = self.level(self.other_subject).content.decode()
        self.assertIn(f'name="target" value="{self.subject.pk}"', html)
        self.assertNotIn(f'value="{self.other_subject.pk}" class="picker-choice', html)

    def test_picking_a_place_shows_what_changes_and_then_demotes(self):
        shown = self.level(self.topic, target=self.other_topic.pk)
        html = shown.content.decode()
        self.assertContains(shown, "Duty")
        self.assertIn(f'<input type="hidden" name="target" value="{self.other_topic.pk}">', html)
        self.assertIn('name="confirmed"', html)
        self.assertNotIn("data-picker-toggle", html)
        done = self.level(self.topic, target=self.other_topic.pk, confirmed="1")
        self.assertEqual(done.status_code, 302)

    def test_confirming_without_a_place_shows_the_picker_again_with_the_message(self):
        resp = self.level(self.topic, confirmed="1")
        self.assertContains(resp, "data-picker-toggle")
        self.assertContains(resp, "it goes under")

    def test_a_section_promote_has_no_picker(self):
        resp = self.post("edit_level", {**self.rec(self.sec), "direction": "promote"})
        self.assertNotContains(resp, "data-picker")

    def test_blue_is_defined_and_red_is_not_used_for_it(self):
        css = source("static/css/site.css")
        rule = re.search(r"\.picker-choice\.picker-current[^{]*\{([^}]*)\}", css).group(1)
        self.assertIn("#1f5fbf", rule)
        self.assertNotIn("oxblood", rule)


class AddFormTests(EditViewTestCase):
    """1.2: root cause was that the Add form's Cancel button had no handler (only Esc closed it) and a saved Item opened
    another blank form. Cancel now closes, Save saves and closes."""

    def test_the_add_form_cancel_button_is_handled_in_the_add_form_script(self):
        js = source("static/js/edit-mode.js")
        setup = js[js.index("function setupAdd"):js.index("function saved")]
        self.assertIn("[data-inline-cancel]", setup)
        self.assertIn("closeCurrent(false)", setup)

    def test_save_closes_and_does_not_open_another_blank_form(self):
        js = source("static/js/edit-mode.js")
        saved = js[js.index("function saved"):js.index('// ---- "Edit": the editing card')]
        self.assertNotIn("openAdd(", saved)
        self.assertIn("closeCurrent(true)", saved)

    def test_the_hint_no_longer_promises_a_next_form(self):
        html = source("templates/diary/_inline_add.html")
        self.assertNotIn("opens the next", html)
        self.assertIn("data-inline-cancel", html)


class CitationBoxTests(EditViewTestCase):
    """1.3: the citation box is a one-line textarea that wraps and grows (desktop); the server still stores one line."""

    def test_the_item_editor_citation_box_is_a_single_line_textarea(self):
        item = self.one
        self.make("case", ("item", item.pk), citation="A v B")
        html = self.client.get(reverse("edit_item", args=[item.pk])).content.decode()
        self.assertIn('<textarea name="case_citation" class="single-line"', html)
        self.assertIn("data-single-line", html)
        self.assertIn("js/single-line.js", html)

    def test_the_script_blocks_enter_and_turns_pasted_line_breaks_into_spaces(self):
        js = source("static/js/single-line.js")
        self.assertIn('e.key !== "Enter"', js)
        self.assertIn("preventDefault", js)
        self.assertIn('replace(/\\s*[\\r\\n]+\\s*/g, " ")', js)

    def test_a_line_break_that_gets_through_is_stored_as_a_space(self):
        from diary.models import Case

        self.client.post(reverse("edit_item", args=[self.one.pk]), {
            "text": "<p>one</p>", "version": self.get(self.one).version, "next": self.next,
            "case_id": [""], "case_version": [""], "case_citation": ["A v B\n(2020) 1 SCC 1"], "case_comment": [""]})
        self.assertEqual([c.citation for c in Case.objects.filter(item=self.one)], ["A v B (2020) 1 SCC 1"])


class ColonTests(EditViewTestCase):
    """1.4: with several citations on separate lines the text ends with ":" (not doubled)."""

    def setUp(self):
        super().setUp()
        for item in (self.one, self.two):
            self.make("case", ("item", item.pk), citation="A v B")
            self.make("case", ("item", item.pk), citation="C v D")
            Item.objects.filter(pk=item.pk).update(citation_layout="lines")

    def page(self):
        return self.client.get(reverse("read_subject", args=[self.subject.pk])).content.decode()

    def test_a_colon_follows_the_text_on_separate_lines(self):
        html = self.page()
        self.assertIn('<span class="item-colon">:</span>', html)

    def test_no_second_colon_when_the_text_already_ends_with_one(self):
        Item.objects.filter(pk=self.one.pk).update(text="<p>one:</p>", text_plain="one:")
        html = self.page()
        self.assertEqual(html.count('class="item-colon"'), 1)  # only "two"

    def test_inline_layout_has_no_colon(self):
        Item.objects.filter(pk__in=[self.one.pk, self.two.pk]).update(citation_layout="inline")
        self.assertNotIn("item-colon", self.page())


class FlagTests(EditViewTestCase):
    """1.6: Other and Pending share the yellow box."""

    def test_both_use_the_same_rule_in_screen_and_offline_css(self):
        for path in ("static/css/site.css", "diary/wordexport/offline_assets/offline.css"):
            css = source(path)
            self.assertRegex(css, r"\.flag-text\.flag-pending, \.flag-text\.flag-other \{[^}]*amber-bg")

    def test_an_other_flag_is_drawn_with_its_own_class(self):
        from diary.models import FLAG_OTHER

        Item.objects.filter(pk=self.one.pk).update(flag=FLAG_OTHER, flag_text="see file")
        html = self.client.get(reverse("read_subject", args=[self.subject.pk])).content.decode()
        self.assertIn('flag-text flag-other', html)


class NotesUnderHeadingTests(EditViewTestCase):
    """1.7: a Topic's Notes come straight after its heading, indented, before its Items (also in Edit mode)."""

    def setUp(self):
        super().setUp()
        self.note = self.make("note", ("topic", self.topic.pk), text="<p>Topic note</p>")

    def order(self, suffix=""):
        html = self.client.get(reverse("read_subject", args=[self.subject.pk]) + suffix).content.decode()
        return html, [html.index(s) for s in ("Formation", "Topic note", ">one<")]

    def test_the_note_is_between_the_heading_and_the_first_item(self):
        html, (heading, note, first) = self.order()
        self.assertLess(heading, note)
        self.assertLess(note, first)
        self.assertIn("note heading-note", html)

    def test_the_same_in_edit_mode(self):
        html, (heading, note, first) = self.order("?edit=1")
        self.assertLess(heading, note)
        self.assertLess(note, first)

    def test_a_subtopic_note_follows_its_own_heading(self):
        sub = self.make("subtopic", ("topic", self.topic.pk), name="Offer")
        self.make("item", ("subtopic", sub.pk), text="sub item")
        self.make("note", ("subtopic", sub.pk), text="<p>Sub note</p>")
        html = self.client.get(reverse("read_subject", args=[self.subject.pk])).content.decode()
        self.assertLess(html.index("Offer"), html.index("Sub note"))
        self.assertLess(html.index("Sub note"), html.index("sub item"))

    def test_the_indent_is_in_the_css(self):
        self.assertRegex(source("static/css/site.css"), r"\.note\.heading-note \{ margin-left: 1\.25rem; \}")


@override_settings(SECURE_SSL_REDIRECT=False)
class JustifyTextTests(EditViewTestCase):
    """1.5: My settings > Display > Justify text (per user, off by default, screen only)."""

    def test_off_by_default_and_no_class(self):
        self.assertFalse(get_user_model().objects.get(pk=self.user.pk).justify_text)
        html = self.client.get(reverse("read_subject", args=[self.subject.pk])).content.decode()
        self.assertNotIn("justify-text", html.split("<body")[0])

    def test_the_checkbox_saves_and_puts_the_class_on_the_page(self):
        self.assertContains(self.client.get(reverse("my_settings") + "?tab=display"), 'name="justify_text"')
        self.client.post(reverse("my_settings"), {"tab": "display", "landing_program": "", "justify_text": "on"})
        self.assertTrue(get_user_model().objects.get(pk=self.user.pk).justify_text)
        html = self.client.get(reverse("read_subject", args=[self.subject.pk])).content.decode()
        self.assertIn('<html lang="en" class="justify-text">', html)

    def test_it_is_per_user(self):
        get_user_model().objects.filter(pk=self.user.pk).update(justify_text=True)
        self.reader_client.get(reverse("read_subject", args=[self.subject.pk]))
        html = self.reader_client.get(reverse("read_subject", args=[self.subject.pk])).content.decode()
        self.assertNotIn("justify-text", html.split("<body")[0])

    def test_unticking_turns_it_off(self):
        get_user_model().objects.filter(pk=self.user.pk).update(justify_text=True)
        self.client.post(reverse("my_settings"), {"tab": "display", "landing_program": ""})
        self.assertFalse(get_user_model().objects.get(pk=self.user.pk).justify_text)

    def test_the_rule_is_screen_only(self):
        css = source("static/css/site.css")
        block = css[css.index("/* Justify text"):]
        self.assertIn("@media screen", block)
        self.assertIn("text-align: justify", block)
