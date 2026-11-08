"""Fees-in-words tests for the Fee Register (T2.1, requirements R-EX-2, brief 7.2).

Ports every golden case from ``feesInWords.test.ts`` and the property assertions
from ``feesInWords.property.test.ts``. Hypothesis is not approved (U8), so the
property tests become seeded randomised loops using stdlib ``random.Random(seed)``
with 200 cases each, mirroring the TS ``numRuns: 200``. Pure function, so a
``SimpleTestCase`` (no database) is used.
"""
import random
from decimal import Decimal

from django.test import SimpleTestCase

from fees.services.fees_in_words import fees_in_words


class FeesInWordsGoldenTests(SimpleTestCase):
    CASES = [
        (0, "Rupees Zero Only"),
        (1000, "Rupees One Thousand Only"),
        (100000, "Rupees One Lakh Only"),
        (1000000, "Rupees Ten Lakhs Only"),
        (10000000, "Rupees One Crore Only"),
        (120000, "Rupees One Lakh Twenty Thousand Only"),
        (10000000.50, "Rupees One Crore and Fifty Paise Only"),
        (60000, "Rupees Sixty Thousand Only"),
        (54000, "Rupees Fifty Four Thousand Only"),
        # R-EX-2 additional golden values.
        (200000, "Rupees Two Lakhs Only"),
    ]

    def test_golden_values(self):
        for amount, expected in self.CASES:
            with self.subTest(amount=amount):
                self.assertEqual(fees_in_words(amount), expected)

    def test_zero_with_paise(self):
        self.assertEqual(fees_in_words(Decimal("0.50")), "Rupees Zero and Fifty Paise Only")

    def test_tens_units_joined_with_space(self):
        self.assertEqual(fees_in_words(21), "Rupees Twenty One Only")

    def test_no_and_before_hundreds(self):
        self.assertEqual(fees_in_words(150), "Rupees One Hundred Fifty Only")

    def test_negative_raises_value_error(self):
        with self.assertRaises(ValueError):
            fees_in_words(-1)
        with self.assertRaises(ValueError):
            fees_in_words(Decimal("-0.01"))


class FeesInWordsPropertyTests(SimpleTestCase):
    """Seeded ports of feesInWords.property.test.ts (deterministic, 200 cases each)."""

    SEED = 20261105
    RUNS = 200

    def test_property_14_integers_start_rupees_end_only(self):
        rng = random.Random(self.SEED)
        for _ in range(self.RUNS):
            amount = rng.randint(0, 9_999_999_999)
            result = fees_in_words(amount)
            self.assertTrue(result.startswith("Rupees"), amount)
            self.assertTrue(result.endswith("Only"), amount)

    def test_property_14b_decimals_start_rupees_end_only(self):
        rng = random.Random(self.SEED + 1)
        for _ in range(self.RUNS):
            rupees = rng.randint(0, 999_999_999)
            paise = rng.randint(0, 99)
            amount = Decimal(rupees) + Decimal(paise) / Decimal(100)
            result = fees_in_words(amount)
            self.assertTrue(result.startswith("Rupees"), amount)
            self.assertTrue(result.endswith("Only"), amount)

    def test_property_non_negative_never_raises(self):
        rng = random.Random(self.SEED + 2)
        for _ in range(self.RUNS):
            amount = Decimal(rng.randint(0, 999_999_999)) + Decimal(rng.randint(0, 99)) / Decimal(100)
            # Must not raise for any non-negative amount.
            fees_in_words(amount)

    def test_property_negative_always_raises(self):
        rng = random.Random(self.SEED + 3)
        for _ in range(self.RUNS):
            amount = -(Decimal(rng.randint(1, 999_999_999)) + Decimal(rng.randint(0, 99)) / Decimal(100))
            with self.assertRaises(ValueError):
                fees_in_words(amount)
