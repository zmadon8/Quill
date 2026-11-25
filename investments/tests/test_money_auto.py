"""Golden-table tests for investments.money_auto, and the same table run against the JavaScript mirror."""
import json
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path

from django.test import SimpleTestCase

from investments.money_auto import format_amount, format_rupees, format_units, format_indian, group_indian, group_western

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden" / "money_auto.json"
JS_CHECK = HERE / "money_auto_js_check.js"


def _cases():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]


class GoldenTableTests(SimpleTestCase):
    def test_every_case(self):
        for case in _cases():
            with self.subTest(case=case):
                if case.get("kind") == "units":
                    got = format_units(case["v"], mode=case["mode"])
                else:
                    got = format_amount(
                        case["v"], currency=case.get("cur", "INR"), mode=case["mode"], signed=case.get("signed", False)
                    )
                self.assertEqual(got, case["out"])

    def test_accepts_decimal_int_float(self):
        self.assertEqual(format_rupees(Decimal("85400")), "₹85.4k")
        self.assertEqual(format_rupees(85400), "₹85.4k")
        self.assertEqual(format_rupees(85400.0), "₹85.4k")

    def test_grouping(self):
        self.assertEqual(group_indian("1234567"), "12,34,567")
        self.assertEqual(group_indian("999"), "999")
        self.assertEqual(group_indian("1000"), "1,000")
        self.assertEqual(group_western("1234567"), "1,234,567")
        self.assertEqual(group_western("999"), "999")
        self.assertEqual(format_amount("1234567.89", currency="USD", mode="full"), "$1,234,567.89")
        self.assertEqual(format_amount("1234567", currency="EUR", mode="full"), "\u20ac1,234,567")
        self.assertEqual(format_amount("1234567", currency="USD"), "$1.23 m")
        self.assertEqual(format_amount("45600", currency="USD"), "$45.60 k")
        self.assertEqual(format_amount("1234567", currency="INR", mode="full"), "\u20b912,34,567")
        self.assertEqual(format_indian("1234567.5"), "12,34,567.50")
        self.assertEqual(format_indian(-1234567, 0), "-12,34,567")
        self.assertEqual(format_indian(0), "0.00")

    def test_rounding_is_on_exact_amount_not_on_rounded_figures(self):
        # Short rupees follow the Fee Register exactly: the unit is chosen on the exact amount (99,99,900 is below a crore, so lacs).
        self.assertEqual(format_rupees("9999900"), "₹100 lac")
        self.assertEqual(format_rupees("12345.675"), "₹12.35k")

    def test_short_rupees_are_the_fee_registers_short_figures(self):
        from fees.services.money import format_money

        for v in ("0", "7.5", "950", "85400", "99999.5", "2412600", "9999499", "24126000", "1234567890", "-60300"):
            with self.subTest(v=v):
                self.assertEqual(format_rupees(v).replace("−", "-").replace("₹", ""), format_money(v, unit="truncated"))


class UnitsFormatTests(SimpleTestCase):
    def test_short_units_use_k_lac_cr_and_full_stays_exact(self):
        self.assertEqual(format_units("1560", mode="auto"), "1.56 k")
        self.assertEqual(format_units("1560", mode="full"), "1,560")
        self.assertEqual(format_units(Decimal("1560000"), mode="auto"), "15.6 lac")
        self.assertEqual(format_units(12000000, mode="auto"), "1.2 cr")
        self.assertEqual(format_units("999.5", mode="auto"), "999.5")

    def test_units_filter_carries_both_texts_for_the_toggle(self):
        from investments.templatetags.investments_money import units

        html = str(units(Decimal("1560.0000")))
        self.assertIn('data-auto="1.56 k"', html)
        self.assertIn('data-full="1,560"', html)
        self.assertIn('class="m"', html)
        self.assertEqual(units(None), "")


class AtMostTwoDecimalsTests(SimpleTestCase):
    """Owner round 2026-12: every Investments table shows at most two decimals, with no trailing zeros, and the exact figure on hover."""

    def test_price_has_at_most_two_decimals_and_the_exact_figure_as_its_tooltip(self):
        from investments.templatetags.investments_money import price

        self.assertEqual(str(price(Decimal("1234.5678"))), '<span class="m" title="1,234.5678">1,234.57</span>')
        self.assertEqual(str(price(Decimal("250.5000"))), '<span class="m" title="250.5">250.5</span>')
        self.assertEqual(str(price(Decimal("100"))), '<span class="m" title="100">100</span>')
        self.assertEqual(str(price(Decimal("-0.004"))), '<span class="m" title="0.004">0</span>')
        self.assertEqual(price(None), "")

    def test_percentages_drop_trailing_zeros_and_keep_the_exact_figure_on_hover(self):
        from investments.templatetags.investments_money import pct, pct_signed, pct_text

        self.assertEqual(str(pct(0.123)), '<span title="12.3%">12.3%</span>')
        self.assertEqual(str(pct(0.1234567)), '<span title="12.34567%">12.35%</span>')
        self.assertEqual(str(pct_signed(0.05)), '<span class="g" title="+5%">+5%</span>')
        self.assertEqual(str(pct_signed(-0.0125)), '<span class="l" title="\u22121.25%">\u22121.25%</span>')
        self.assertEqual(pct_text(0.5), "50%")

    def test_units_show_the_stored_decimals_on_hover(self):
        from investments.templatetags.investments_money import units

        html = str(units(Decimal("12.3456")))
        self.assertIn('data-full="12.35"', html)
        self.assertIn('title="12.3456"', html)

    def test_foreign_amounts_drop_trailing_zeros(self):
        self.assertEqual(format_amount("1234.5", currency="USD", mode="full"), "$1,234.5")
        self.assertEqual(format_amount("1500", currency="USD", mode="auto"), "$1.5 k")


class JavaScriptMirrorTests(SimpleTestCase):
    def test_javascript_matches_golden_table(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed; CI runs this check")
        result = subprocess.run([node, str(JS_CHECK), str(GOLDEN)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
