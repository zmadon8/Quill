"""Round 12 item 1: the Add page offers the inline form's types, and the Flag is on both add paths (round 16, D88:
For review was merged into the Flags; Sections take a Flag too)."""
from django.test import Client, override_settings
from django.urls import reverse

from diary import inline
from diary.models import Item, Section
from diary.tests.test_csrf_edit_mode import PHONE, fields_of
from diary.tests.test_views_inline import InlineTestCase
from diary.undo_session import SESSION_KEY


@override_settings(SECURE_SSL_REDIRECT=False)
class AddChoicesParityTests(InlineTestCase):
    def test_the_add_page_lists_exactly_the_inline_choices_for_every_kind_of_row(self):
        rows = (("item", self.one), ("section", self.sec), ("topic", self.topic), ("subject", self.subject))
        for kind, obj in rows:
            wanted = inline.add_choices(self.profile, kind, obj)
            page = self.client.get(reverse("edit_add"), {"parent": f"{kind}:{obj.pk}", "next": self.next})
            self.assertEqual(page.status_code, 200, kind)
            offered = [(o["value"], o["label"]) for o in page.context["options"]]
            self.assertEqual(offered, wanted, kind)
            self.assertEqual(offered, [(c["value"], c["label"]) for c in self.form(f"{kind}:{obj.pk}").json()["choices"]])

    def test_after_and_parent_addresses_give_the_same_page(self):
        a = self.client.get(reverse("edit_add"), {"after": f"item:{self.one.pk}", "next": self.next})
        b = self.client.get(reverse("edit_add"), {"parent": f"item:{self.one.pk}", "next": self.next})
        self.assertEqual(a.context["options"], b.context["options"])

    def test_the_page_has_the_flag_drop_down_like_the_inline_form(self):
        page = self.client.get(reverse("edit_add"), {"after": f"item:{self.one.pk}", "next": self.next}).content.decode()
        inline_html = self.form(f"item:{self.one.pk}").json()["html"]
        for markup in (page, inline_html):
            for needle in ('<select name="flag"', 'value="pending"', 'value="overruled"', 'name="flag_text"', "data-add-flag"):
                self.assertIn(needle, markup)
            for gone in ('name="needs_review"', 'name="review_note"', "For review"):
                self.assertNotIn(gone, markup)


@override_settings(SECURE_SSL_REDIRECT=False)
class AddMarkingTests(InlineTestCase):
    def add_item(self, **fields):
        return self.add(f"item:{self.one.pk}", "after:item", self.one, text="<p>marked</p>", text_format="html", **fields)

    def test_an_inline_item_is_saved_with_its_flag_in_one_undo_step(self):
        resp = self.add_item(flag="pending", flag_text=" Needs a look ", needs_review="1", review_note=" ignored ")
        self.assertEqual(resp.status_code, 200)
        item = Item.objects.get(topic=self.topic, text_plain="marked")
        self.assertEqual((item.flag, item.flag_text, item.needs_review, item.review_note), ("pending", "Needs a look", False, ""))
        group = resp.json()["undo"]["group"]
        self.assertEqual(self.client.session[SESSION_KEY][-1]["group"], group)
        self.assertEqual(self.fetch("edit_undo", {"group": group}).status_code, 200)
        self.assertFalse(Item.objects.filter(topic=self.topic, text_plain="marked", deleted_at__isnull=True).exists())

    def test_the_default_is_no_flag(self):
        self.add_item()
        item = Item.objects.get(topic=self.topic, text_plain="marked")
        self.assertEqual((item.flag, item.flag_text, item.needs_review), ("none", "", False))

    def test_validation_is_the_editors(self):
        for fields in ({"flag": "bogus"}, {"flag": "other", "flag_text": "x" * 2001}):
            resp = self.add_item(**fields)
            self.assertNotEqual(resp.status_code, 200, fields)
        self.assertFalse(Item.objects.filter(topic=self.topic, text_plain="marked").exists())

    def test_a_section_takes_a_flag_too(self):
        resp = self.add(f"item:{self.one.pk}", "after:section", self.one, text="Marked section",
                        flag="doubted", flag_text="n")
        self.assertEqual(resp.status_code, 200)
        section = Section.objects.get(name="Marked section")
        self.assertEqual((section.flag, section.flag_text, section.needs_review), ("doubted", "n", False))
        resp = self.add(f"item:{self.one.pk}", "after:section", self.one, text="Plain section", flag="none", flag_text="x")
        self.assertEqual((Section.objects.get(name="Plain section").flag, Section.objects.get(name="Plain section").flag_text),
                         ("none", ""))

    def test_a_note_ignores_the_flag(self):
        resp = self.add(f"item:{self.one.pk}", "inside:note", self.one, text="<p>a note</p>", text_format="html",
                        flag="doubted", flag_text="x")
        self.assertEqual(resp.status_code, 200)


@override_settings(SECURE_SSL_REDIRECT=False)
class PhoneAddPageMarkingTests(InlineTestCase):
    def test_the_page_saves_the_flag_with_the_real_csrf_check(self):
        strict = Client(enforce_csrf_checks=True, HTTP_USER_AGENT=PHONE)
        strict.force_login(self.user)
        markup = strict.get(reverse("edit_add"), {"after": f"item:{self.one.pk}", "next": self.next}).content.decode()
        data = {**fields_of(markup), "choice": "after:item", "text": "from the page", "flag": "doubted",
                "flag_text": "later"}
        self.assertEqual(strict.post(reverse("edit_add"), {k: v for k, v in data.items() if k != "csrfmiddlewaretoken"}).status_code, 403)
        self.assertEqual(strict.post(reverse("edit_add"), data).status_code, 302)
        item = Item.objects.get(topic=self.topic, text__contains="from the page")
        self.assertEqual((item.flag, item.flag_text), ("doubted", "later"))
