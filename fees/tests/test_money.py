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
