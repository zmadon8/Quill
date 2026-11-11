"""Fee Register round: write-off and Delete under More, Unaccounted link, Overdue off hides every overdue control,
and the clickable Outstanding ageing cards."""
import datetime
import re

from django.urls import reverse

from fees.models import FeesSettings, Memo
from fees.services import outstanding
from fees.tests.test_ui_pages import UiPageBase


class MemoMoreMenuTests(UiPageBase):
    def test_write_off_and_delete_are_only_inside_more(self):
        memo = self.seed["memo_a"]
        text = self.html(self.page("fees_memo_detail", {"memo_id": memo.pk}, user=self.editor))
        menu = text.split('<details class="more-menu">', 1)[1].split("</details>", 1)[0]
        for control in (reverse("fees_memo_write_off", args=[memo.pk]), reverse("fees_memo_delete", args=[memo.pk]),
                        "Write Off As A Bad Debt", "Delete Memo"):
            self.assertIn(control, menu)
            self.assertEqual(text.count(control), 1, control)

    def test_reader_sees_neither(self):
        memo = self.seed["memo_a"]
        text = self.html(self.page("fees_memo_detail", {"memo_id": memo.pk}))
        self.assertNotIn("Delete Memo", text)
        self.assertNotIn("Write Off As A Bad Debt", text)


class FeebookUnaccountedLinkTests(UiPageBase):
    def test_editor_unaccounted_label_links_to_payment_edit(self):
        url = reverse("fees_payment_edit", args=[self.seed["unaccounted"]["id"]])
        text = self.html(self.page("fees_feebook", user=self.editor, query="?unaccounted=1"))
        self.assertRegex(text, r'<a href="%s"[^>]*>Unaccounted</a>' % re.escape(url))

    def test_reader_gets_plain_text(self):
        text = self.html(self.page("fees_feebook", query="?unaccounted=1"))
        self.assertIn("<td>Unaccounted</td>", text)


class OverdueOffTests(UiPageBase):
    def set_days(self, days):
        FeesSettings.objects.update_or_create(profile=self.profile, defaults={"overdue_days": days})

    def test_no_overdue_controls_when_off(self):
        self.set_days(0)
        for name, query in (("fees_outstanding", "?overdue=1"), ("fees_outstanding_detail", "?overdue=1"),
                            ("fees_memos", ""), ("fees_dashboard", "")):
            text = self.html(self.page(name, query=query))
            self.assertNotIn("View Overdue Memos Only", text, name)
            self.assertNotIn("sq-overdue", text, name)
            self.assertNotIn("Amount Overdue", text, name)
            self.assertNotIn("overdue=1", text, name)

    def test_controls_present_when_on(self):
        self.set_days(30)
        for name in ("fees_outstanding", "fees_outstanding_detail"):
            self.assertIn("View Overdue Memos Only", self.html(self.page(name)))
        self.assertIn("sq-overdue", self.html(self.page("fees_memos")))

    def test_overdue_param_ignored_when_off(self):
        from fees.pages import outstanding_filters

        self.assertNotIn("overdue_only", outstanding_filters({"overdue": "1"}, overdue_enabled=False))
        self.assertTrue(outstanding_filters({"overdue": "1"})["overdue_only"])


class AgeingCardTests(UiPageBase):
    def make_ages(self):
        today = datetime.date.today()
        for memo, days in ((self.seed["memo_a"], 5), (self.seed["memo_b"], 45)):
            Memo.objects.filter(pk=memo.pk).update(date=today - datetime.timedelta(days=days))

    def test_filter_parsing(self):
        from fees.pages import outstanding_filters

        for key in ("0-30", "31-60", "61-90", "90+"):
            self.assertEqual(outstanding_filters({"age": key})["age"], key)
        self.assertEqual(outstanding_filters({"age": "90 "})["age"], "90+")
        self.assertNotIn("age", outstanding_filters({"age": "zzz"}))

    def test_service_filters_to_each_range_and_matches_card(self):
        self.make_ages()
        rows = outstanding.list_outstanding_by_firm(self.profile, {})
        for index, bucket in enumerate(outstanding.ageing_totals(rows)):
            groups = outstanding.list_outstanding(self.profile, {"age": bucket["key"]})
            count = sum(len(g["entries"]) for g in groups)
            self.assertEqual(count, bucket["memo_count"], bucket["key"])
            self.assertEqual(outstanding.outstanding_grand_total(groups), bucket["amount"], bucket["key"])
            by_firm = outstanding.list_outstanding_by_firm(self.profile, {"age": bucket["key"]})
            self.assertEqual(sum(r["memo_count"] for r in by_firm), bucket["memo_count"])
        young = outstanding.list_outstanding(self.profile, {"age": "0-30"})
        self.assertEqual([e["memo_id"] for g in young for e in g["entries"]], [self.seed["memo_a"].pk])

    def test_cards_are_links_to_the_filtered_detail(self):
        text = self.html(self.page("fees_outstanding", query="?written_off=1"))
        detail = re.escape(reverse("fees_outstanding_detail"))
        for key in ("0-30", "31-60", "61-90", "90%2B"):
            self.assertRegex(text, r'<a class="ageing-card[^"]*" href="%s\?[^"]*age=%s' % (detail, re.escape(key)))
        self.assertRegex(text, r'href="%s\?[^"]*written_off=1' % detail)

    def test_detail_shows_only_the_range_with_a_clear_link(self):
        self.make_ages()
        text = self.html(self.page("fees_outstanding_detail", query="?age=0-30&view=flat"))
        memo_a, memo_b = self.seed["memo_a"], self.seed["memo_b"]
        self.assertIn(reverse("fees_memo_detail", args=[memo_a.pk]), text)
        self.assertNotIn(reverse("fees_memo_detail", args=[memo_b.pk]), text)
        self.assertIn("Show all ages", text)
        self.assertIn('name="age" value="0-30"', text)
        export = re.search(r'href="%s\?([^"]*)"' % re.escape(reverse("fees_outstanding_export")), text)
        self.assertIn("age=0-30", export.group(1))
        plain = self.html(self.page("fees_outstanding_detail"))
        self.assertNotIn("Show all ages", plain)
