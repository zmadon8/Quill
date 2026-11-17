"""Owner round (2026-12), D212: the Fee Register takes numbers typed with commas, and its number boxes are text boxes with an inputmode."""
import re
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees import forms
from fees.errors import FeesError
from fees.services.settings import get_settings, update_settings


class CommaSettingsTests(TestCase):
    def setUp(self):
        self.profile = Profile.objects.create(program=KEY_FEES, name="Commas-Fees")

    def test_overdue_days_and_rates_with_commas(self):
        result = update_settings(self.profile, {"overdue_days": "1,095", "default_tds_rate": "1,0", "default_fees_per_appearance": "1,25,000.50"})
        self.assertEqual(result["overdue_days"], 1095)
        self.assertEqual(result["default_tds_rate"], Decimal("10"))
        self.assertEqual(get_settings(self.profile)["default_fees_per_appearance"], Decimal("125000.50"))

    def test_a_bad_value_is_still_refused(self):
        with self.assertRaises(FeesError):
            update_settings(self.profile, {"overdue_days": "1,0,x"})
        with self.assertRaises(FeesError):
            update_settings(self.profile, {"overdue_days": "9,999"})  # over 3650

    def test_items_per_page_keeps_the_word_all(self):
        from fees.services.settings import _validate_candidate

        self.assertEqual(_validate_candidate("items_per_page", "All"), 0)
        self.assertEqual(_validate_candidate("items_per_page", "1,000"), 1000)

    def test_the_settings_form_post_passes_commas_through(self):
        data = forms.settings_data_from_post({"overdue_days": "1,095"})
        self.assertEqual(update_settings(self.profile, data)["overdue_days"], 1095)


class CommaMemoFieldTests(SimpleTestCase):
    def test_memo_counts_and_amounts_with_commas(self):
        self.assertEqual(forms.parse_int("1,200", "Num appearances"), 1200)
        self.assertEqual(forms.parse_decimal("1,23,456.50", "Fees"), Decimal("123456.50"))
        self.assertEqual(forms.parse_decimal("\u20b9 75,000", "Fees"), Decimal("75000"))
        with self.assertRaises(FeesError):
            forms.parse_int("12,x", "Num appearances")

    def test_memo_counts_are_read_with_commas(self):
        post = {"num_appearances": "1,000", "num_conferences": "2", "fees_per_appearance": "5,000", "date": "2026-07-15"}
        data = forms.memo_data_from_post(post)
        self.assertEqual(data["num_appearances"], 1000)
        self.assertEqual(data["fees_per_appearance"], Decimal("5000"))


class NumberBoxTemplateTests(SimpleTestCase):
    def read(self, name):
        from pathlib import Path

        from django.conf import settings

        return (Path(settings.BASE_DIR) / "templates" / name).read_text(encoding="utf-8")

    def test_no_fees_template_uses_type_number(self):
        for name in ("fees/memo_form.html", "fees/settings.html", "fees/payment_form.html", "fees/_alloc_row.html", "fees/_adjustment_grid.html"):
            self.assertNotIn('type="number"', self.read(name), name)

    def test_the_memo_count_boxes_are_numeric_text_boxes(self):
        html = self.read("fees/memo_form.html")
        for name in ("num_appearances", "num_conferences", "num_drafts"):
            self.assertRegex(html, r'<input type="text" inputmode="numeric" name="%s"' % name)

    def test_overdue_days_is_a_numeric_text_box(self):
        self.assertRegex(self.read("fees/settings.html"), r'<input type="text" inputmode="numeric" name="overdue_days"')

    def test_every_number_box_in_the_fees_templates_has_an_inputmode(self):
        for name in ("fees/settings.html", "fees/memo_form.html", "fees/payment_form.html"):
            for tag in re.findall(r"<input[^>]*>", self.read(name)):
                if re.search(r'name="(default_fees_|default_tds|fees_|custom_fees|custom_total|amount|tds_|num_|overdue_days)', tag):
                    self.assertIn("inputmode=", tag, tag)
