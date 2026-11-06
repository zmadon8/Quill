"""Money and date formatting tests for the Fee Register (T2.1, design section 3).

The ``format_currency`` and ``format_money`` golden cases are ported from the
original ``formatMoney.test.ts`` and stored in ``fees/tests/fixtures/money_cases.json``
(design 3: "the Python test runs it against money.py"). ``round2`` and
``format_date`` are checked directly. These are pure functions, so a
``SimpleTestCase`` (no database) is enough and faster.
"""
import datetime
import json
from decimal import Decimal
from pathlib import Path

from django.test import SimpleTestCase

from fees.services.money import (
    format_currency,
    format_date,
    format_money,
    round2,
)

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "money_cases.json"


def _load_cases():
    with _FIXTURE.open(encoding="utf-8") as fh:
        return json.load(fh)


class Round2Tests(SimpleTestCase):
    def test_rounds_half_away_from_zero(self):
        self.assertEqual(round2("1.005"), Decimal("1.01"))
        self.assertEqual(round2("2.675"), Decimal("2.68"))
        self.assertEqual(round2(100.6), Decimal("100.60"))

    def test_accepts_int_str_decimal_float(self):
        self.assertEqual(round2(5), Decimal("5.00"))
        self.assertEqual(round2("5"), Decimal("5.00"))
        self.assertEqual(round2(Decimal("5")), Decimal("5.00"))
        # Float goes through str() so 0.1 stays 0.10, not its binary expansion.
        self.assertEqual(round2(0.1), Decimal("0.10"))

    def test_always_two_places(self):
        self.assertEqual(str(round2(3)), "3.00")


class FormatCurrencyFixtureTests(SimpleTestCase):
    def test_golden_cases(self):
        for case in _load_cases()["format_currency"]:
            with self.subTest(value=case["value"]):
                self.assertEqual(format_currency(case["value"]), case["expected"])


class FormatMoneyFixtureTests(SimpleTestCase):
    def test_golden_cases(self):
        for case in _load_cases()["format_money"]:
            kwargs = {}
            if "unit" in case:
                kwargs["unit"] = case["unit"]
            for key in ("suffix_thousands", "suffix_lac", "suffix_crore"):
                if key in case:
                    kwargs[key] = case[key]
            with self.subTest(value=case["value"], unit=case.get("unit")):
                self.assertEqual(format_money(case["value"], **kwargs), case["expected"])

    def test_default_unit_is_full(self):
        self.assertEqual(format_money(312451), "3,12,451")

    def test_none_is_zero(self):
        self.assertEqual(format_money(None), "0")
        self.assertEqual(format_money(None, unit="truncated"), "0")


class FormatDateTests(SimpleTestCase):
    def test_from_iso_string(self):
        self.assertEqual(format_date("2026-07-15"), "15.07.2026")
        self.assertEqual(format_date("2026-07-15T09:30:00"), "15.07.2026")

    def test_from_date_and_datetime(self):
        self.assertEqual(format_date(datetime.date(2026, 7, 5)), "05.07.2026")
        self.assertEqual(format_date(datetime.datetime(2026, 12, 31, 23, 59)), "31.12.2026")


class WholeNumberDisplayTests(SimpleTestCase):
    """Item 2.11: whole numbers show without ``.00`` (rounding is unchanged); exports are not touched."""

    def test_full_mode_never_shows_decimals(self):
        for value in (Decimal("5000.00"), Decimal("1234567.00"), 5000, "5000.00"):
            with self.subTest(value=value):
                self.assertNotIn(".", format_money(value, unit="full"))
        self.assertEqual(format_money(Decimal("5000.00")), "5,000")

    def test_full_mode_keeps_the_existing_rounding(self):
        self.assertEqual(format_money(Decimal("100.50")), "101")
        self.assertEqual(format_money(Decimal("100.49")), "100")
        self.assertEqual(format_money(Decimal("-0.40")), "0")

    def test_template_filter_uses_full_mode_by_default(self):
        from fees.templatetags.fees_money import fees_money

        self.assertEqual(fees_money(Decimal("45000.00")), "45,000")
        self.assertEqual(fees_money(Decimal("45000.00"), "full"), "45,000")
        self.assertEqual(fees_money(None), "")

    def test_input_filter_drops_a_zero_fraction_only(self):
        from fees.templatetags.fees_money import fees_plain

        self.assertEqual(fees_plain(Decimal("7000.00")), "7000")
        self.assertEqual(fees_plain(Decimal("12.50")), "12.50")
        self.assertEqual(fees_plain(Decimal("0.00")), "0")
        self.assertEqual(fees_plain(None), "")

    def test_form_values_drop_a_zero_fraction_only(self):
        from fees import forms

        self.assertEqual(forms._text(Decimal("5000.00")), "5000")
        self.assertEqual(forms._text(Decimal("12.50")), "12.50")
        self.assertEqual(forms._text("abc"), "abc")
        self.assertEqual(forms._text(None), "")
        self.assertEqual(forms._text(3), "3")
        form = forms.blank_memo_form({"default_fees_per_appearance": Decimal("1500.00")})
        self.assertEqual(form["fees_per_appearance"], "1500")

    def test_payment_form_values_drop_the_fraction(self):
        from fees import forms

        form = forms.payment_form_from_dto({"amount": Decimal("900.00"), "tds_amount": Decimal("100.00"), "tds_rate": Decimal("10.00")})
        self.assertEqual((form["amount"], form["tds_amount"], form["tds_rate"]), ("900", "100", "10"))

    def test_the_python_helpers_stay_the_rounding_source_of_truth(self):
        self.assertEqual(round2("1.005"), Decimal("1.01"))
