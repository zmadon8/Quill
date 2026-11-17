"""Owner round (2026-12), D212: every number box accepts commas whether or not number-commas.js is on."""
from decimal import Decimal

from django import forms
from django.test import SimpleTestCase

from config.comma_numbers import CommaDecimalField, CommaIntegerField, plain_number
from fees import forms as fees_forms
from investments import forms as inv_forms
from mailer.forms import EmailBackupForm


class PlainNumberTests(SimpleTestCase):
    def test_commas_spaces_and_the_rupee_sign_go(self):
        self.assertEqual(plain_number("\u20b91,23,456.50"), "123456.50")
        self.assertEqual(plain_number("12 34 567"), "1234567")
        self.assertEqual(plain_number("1,234,567.5"), "1234567.5")
        self.assertEqual(plain_number("All"), "All")
        self.assertEqual(plain_number("-1,000"), "-1000")
        self.assertIsNone(plain_number(None))
        self.assertEqual(plain_number(5), 5)


class CommaFieldTests(SimpleTestCase):
    def test_decimal_field_takes_indian_and_western_grouping(self):
        field = CommaDecimalField(max_digits=12, decimal_places=2)
        self.assertEqual(field.clean("1,23,456.50"), Decimal("123456.50"))
        self.assertEqual(field.clean("1,234,567"), Decimal("1234567"))
        self.assertEqual(field.clean("\u20b9 5"), Decimal("5"))

    def test_integer_field_takes_commas(self):
        field = CommaIntegerField(min_value=1, max_value=5000)
        self.assertEqual(field.clean("1,234"), 1234)
        with self.assertRaises(forms.ValidationError):
            field.clean("5,001")  # the limits are still checked on the server
        with self.assertRaises(forms.ValidationError):
            field.clean("12a")

    def test_blank_is_still_blank(self):
        self.assertIsNone(CommaDecimalField(required=False).clean(""))
        self.assertIsNone(CommaIntegerField(required=False).clean(""))

    def test_the_widgets_are_text_boxes_with_an_inputmode(self):
        self.assertEqual(CommaDecimalField().widget.input_type, "text")
        self.assertEqual(CommaDecimalField().widget.attrs["inputmode"], "decimal")
        self.assertEqual(CommaIntegerField().widget.input_type, "text")
        self.assertEqual(CommaIntegerField().widget.attrs["inputmode"], "numeric")
        self.assertNotIn("step", CommaDecimalField(decimal_places=2).widget.attrs)


class InvestmentsFormFieldTests(SimpleTestCase):
    def test_no_plain_django_number_field_is_left_in_the_investments_forms(self):
        for name in dir(inv_forms):
            cls = getattr(inv_forms, name)
            if isinstance(cls, type) and issubclass(cls, forms.Form) and cls is not forms.Form:
                for field_name, field in cls.base_fields.items():
                    if isinstance(field, (forms.DecimalField, forms.IntegerField)):
                        self.assertIsInstance(field, (CommaDecimalField, CommaIntegerField), f"{name}.{field_name}")
                        self.assertEqual(field.widget.input_type, "text", f"{name}.{field_name}")
                        self.assertIn("inputmode", field.widget.attrs, f"{name}.{field_name}")

    def test_the_alert_levels_and_the_integer_boxes_accept_commas(self):
        self.assertEqual(inv_forms.GeneralSettingsForm.base_fields["long_term_days"].clean("1,095"), 1095)
        self.assertEqual(inv_forms.AlertSettingsForm.base_fields["rule_a_fall_pct"].clean("1,000"), Decimal("1000"))
        self.assertEqual(inv_forms.MoneyField().clean("\u20b91,23,456.5"), Decimal("123456.5"))


class MailerFormFieldTests(SimpleTestCase):
    def test_the_mailer_integer_boxes_are_comma_fields(self):
        form = EmailBackupForm()
        for name in ("max_attachment_mb", "data_day_of_month"):
            field = form.fields[name]
            self.assertIsInstance(field, CommaIntegerField, name)
            self.assertEqual(field.widget.input_type, "text")
        self.assertEqual(form.fields["max_attachment_mb"].clean("1,5"), 15)


class FeesParsingTests(SimpleTestCase):
    def test_the_parse_helpers_strip_commas(self):
        self.assertEqual(fees_forms.parse_int("1,000"), 1000)
        self.assertEqual(fees_forms.parse_decimal("1,23,456.50"), Decimal("123456.50"))
        self.assertEqual(fees_forms.parse_decimal("\u20b9 5,000"), Decimal("5000"))
        self.assertEqual(fees_forms.parse_int(""), 0)
