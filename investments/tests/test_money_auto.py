"""Golden-table tests for investments.money_auto, and the same table run against the JavaScript mirror."""
import json
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path

from django.test import SimpleTestCase

from investments.money_auto import format_amount, format_rupees, group_indian, group_western

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden" / "money_auto.json"
JS_CHECK = HERE / "money_auto_js_check.js"


def _cases():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]


class GoldenTableTests(SimpleTestCase):
    def test_every_case(self):
        for case in _cases():
            with self.subTest(case=case):
                got = format_amount(
                    case["v"], currency=case.get("cur", "INR"), mode=case["mode"], signed=case.get("signed", False)
                )
                self.assertEqual(got, case["out"])

    def test_accepts_decimal_int_float(self):
        self.assertEqual(format_rupees(Decimal("85400")), "₹85.40 k")
        self.assertEqual(format_rupees(85400), "₹85.40 k")
        self.assertEqual(format_rupees(85400.0), "₹85.40 k")

    def test_grouping(self):
        self.assertEqual(group_indian("1234567"), "12,34,567")
        self.assertEqual(group_indian("999"), "999")
        self.assertEqual(group_indian("1000"), "1,000")
        self.assertEqual(group_western("1234567"), "1,234,567")

    def test_rounding_is_on_exact_amount_not_on_rounded_figures(self):
        # 99.999 lac must roll over into crores; a naive round-then-pick-unit would print 100.00 lac.
        self.assertEqual(format_rupees("9999900"), "₹1.00 cr")


class JavaScriptMirrorTests(SimpleTestCase):
    def test_javascript_matches_golden_table(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed; CI runs this check")
        result = subprocess.run([node, str(JS_CHECK), str(GOLDEN)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
