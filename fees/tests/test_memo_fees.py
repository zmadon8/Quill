"""Memo fee rule and derived-value tests (T2.2, R-MEMO-1, R-MEMO-7, brief 5.2 to 5.5).

Ports the fee/override/status/overdue cases from ``memoService.test.ts`` and the
fee invariants from ``memoService.property.test.ts`` (as a seeded ``random.Random``
loop), adds the D3 cases (R-MEMO-1) and a grep-style guard that no other ``fees``
module computes line fees itself. Pure functions, so ``SimpleTestCase`` (no DB).
"""
import datetime
import importlib
import pkgutil
import random
import re
from decimal import Decimal

from django.test import SimpleTestCase

from fees.services.memo_fees import (
    compute_fees_appearances,
    compute_fees_conferences,
    compute_less_tds,
    compute_is_overdue,
    compute_total_fees,
    effective_total_fees,
    net_of_tds,
    resolve_memo_fees,
    status_and_due,
)


def _row(**over):
    """A memo-fee row as a plain dict (the attribute/dict-flexible reader handles both)."""
    base = {
        "num_appearances": 2,
        "fees_per_appearance": Decimal("5000"),
        "num_conferences": 1,
        "fees_per_conference": Decimal("3000"),
        "fees_misc_drafting": Decimal("1000"),
        "custom_fees_appearances": None,
        "custom_fees_conferences": None,
        "custom_fees_misc": None,
        "custom_total_fees": None,
    }
    base.update(over)
    return base


class SimpleNamespace:
    """A tiny attribute-carrying object, to prove the reader works on non-dicts too."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


class LineAndTotalComputationTests(SimpleTestCase):
    def test_line_and_total_helpers(self):
        self.assertEqual(compute_fees_appearances(2, 5000), Decimal("10000.00"))
        self.assertEqual(compute_fees_conferences(1, 3000), Decimal("3000.00"))
        self.assertEqual(
            compute_total_fees(Decimal("10000"), Decimal("3000"), Decimal("1000")),
            Decimal("14000.00"),
        )

    def test_helpers_round_to_two_places(self):
        self.assertEqual(compute_fees_appearances(3, Decimal("0.3333")), Decimal("1.00"))
        self.assertEqual(compute_less_tds(Decimal("14000"), 10), Decimal("1400.00"))
        self.assertEqual(compute_less_tds(Decimal("12345"), Decimal("7.5")), Decimal("925.88"))


class ResolveMemoFeesTests(SimpleTestCase):
    def test_no_customs_uses_counts_and_rates(self):
        fees = resolve_memo_fees(_row())
        self.assertEqual(fees.fees_appearances, Decimal("10000.00"))
        self.assertEqual(fees.fees_conferences, Decimal("3000.00"))
        self.assertEqual(fees.fees_misc, Decimal("1000.00"))
        self.assertEqual(fees.total_fees, Decimal("14000.00"))

    def test_reader_works_on_attribute_objects(self):
        fees = resolve_memo_fees(SimpleNamespace(**_row()))
        self.assertEqual(fees.total_fees, Decimal("14000.00"))

    def test_misc_is_a_flat_amount(self):
        fees = resolve_memo_fees(_row(fees_misc_drafting=Decimal("2500")))
        self.assertEqual(fees.fees_misc, Decimal("2500.00"))
        self.assertEqual(fees.total_fees, Decimal("15500.00"))

    def test_positive_custom_total_overrides_the_sum(self):
        # Ports "honours custom amounts over auto-calculation".
        fees = resolve_memo_fees(_row(custom_total_fees=Decimal("99999")))
        self.assertEqual(fees.total_fees, Decimal("99999.00"))

    def test_effective_total_fees_convenience(self):
        self.assertEqual(effective_total_fees(_row()), Decimal("14000.00"))
        self.assertEqual(
            effective_total_fees(_row(custom_total_fees=Decimal("42"))),
            Decimal("42.00"),
        )

    # --- D3 (R-MEMO-1, brief 15 Q1): total custom 0 or None means NO override ---

    def test_d3_custom_total_zero_means_no_override(self):
        # Form posts 0 with custom amounts "on"; saved total equals the summed total, NOT 0.
        fees = resolve_memo_fees(_row(custom_total_fees=Decimal("0")))
        self.assertEqual(fees.total_fees, Decimal("14000.00"))

    def test_d3_custom_total_none_means_no_override(self):
        fees = resolve_memo_fees(_row(custom_total_fees=None))
        self.assertEqual(fees.total_fees, Decimal("14000.00"))

    def test_d3_custom_total_zero_int_and_float(self):
        self.assertEqual(effective_total_fees(_row(custom_total_fees=0)), Decimal("14000.00"))
        self.assertEqual(effective_total_fees(_row(custom_total_fees=0.0)), Decimal("14000.00"))

    def test_d3_line_customs_on_but_total_left_at_zero_sums(self):
        # Custom line amounts "on", total left at 0: returns the summed total, not 0.
        fees = resolve_memo_fees(
            _row(
                custom_fees_appearances=Decimal("7000"),
                custom_fees_conferences=Decimal("2000"),
                custom_fees_misc=Decimal("500"),
                custom_total_fees=Decimal("0"),
            )
        )
        self.assertEqual(fees.total_fees, Decimal("9500.00"))

    # --- Line customs follow the TS ``??``: 0 IS a real override, None falls back ---

    def test_line_custom_zero_is_a_real_override(self):
        fees = resolve_memo_fees(_row(custom_fees_appearances=Decimal("0")))
        self.assertEqual(fees.fees_appearances, Decimal("0.00"))
        # The sum reflects the 0 line: 0 + 3000 + 1000.
        self.assertEqual(fees.total_fees, Decimal("4000.00"))

    def test_line_custom_none_falls_back_to_count_times_rate(self):
        fees = resolve_memo_fees(_row(custom_fees_appearances=None))
        self.assertEqual(fees.fees_appearances, Decimal("10000.00"))

    def test_line_custom_misc_zero_is_an_override(self):
        fees = resolve_memo_fees(_row(custom_fees_misc=Decimal("0")))
        self.assertEqual(fees.fees_misc, Decimal("0.00"))
        self.assertEqual(fees.total_fees, Decimal("13000.00"))

    def test_positive_line_customs_override_each_line(self):
        fees = resolve_memo_fees(
            _row(
                custom_fees_appearances=Decimal("1234"),
                custom_fees_conferences=Decimal("567"),
                custom_fees_misc=Decimal("89"),
            )
        )
        self.assertEqual(fees.fees_appearances, Decimal("1234.00"))
        self.assertEqual(fees.fees_conferences, Decimal("567.00"))
        self.assertEqual(fees.fees_misc, Decimal("89.00"))
        self.assertEqual(fees.total_fees, Decimal("1890.00"))


class NetOfTdsTests(SimpleTestCase):
    def test_golden_ten_percent(self):
        # total 10000 at 10% -> 10000 - 1000 = 9000.
        self.assertEqual(net_of_tds(Decimal("10000"), 10), Decimal("9000.00"))

    def test_matches_memoservice_default_rate_case(self):
        # 14000 - (14000 * 10%) = 12600 (ported from memoService.test.ts).
        self.assertEqual(net_of_tds(Decimal("14000"), 10), Decimal("12600.00"))

    def test_zero_rate_is_the_total(self):
        self.assertEqual(net_of_tds(Decimal("5000"), 0), Decimal("5000.00"))


class StatusAndDueTests(SimpleTestCase):
    def test_unpaid_when_paid_below_total(self):
        due = status_and_due(Decimal("14000"), Decimal("4000"))
        self.assertEqual(due.amount_due, Decimal("10000.00"))
        self.assertEqual(due.status, "Unpaid")

    def test_paid_when_paid_equals_total(self):
        due = status_and_due(Decimal("14000"), Decimal("14000"))
        self.assertEqual(due.amount_due, Decimal("0.00"))
        self.assertEqual(due.status, "Paid")

    def test_zero_total_is_paid(self):
        due = status_and_due(Decimal("0"), Decimal("0"))
        self.assertEqual(due.status, "Paid")
        self.assertEqual(due.amount_due, Decimal("0.00"))

    def test_overpaid_gives_negative_due_and_paid_status(self):
        due = status_and_due(Decimal("14000"), Decimal("15000"))
        self.assertEqual(due.amount_due, Decimal("-1000.00"))
        self.assertEqual(due.status, "Paid")


class ComputeIsOverdueTests(SimpleTestCase):
    def setUp(self):
        self.now = datetime.date(2026, 12, 31)

    def test_overdue_days_zero_disables(self):
        self.assertFalse(
            compute_is_overdue("2026-01-01", "Unpaid", False, 0, now=self.now)
        )

    def test_paid_is_never_overdue(self):
        self.assertFalse(
            compute_is_overdue("2026-01-01", "Paid", False, 30, now=self.now)
        )

    def test_written_off_is_never_overdue(self):
        self.assertFalse(
            compute_is_overdue("2026-01-01", "Unpaid", True, 30, now=self.now)
        )

    def test_invalid_date_is_not_overdue(self):
        self.assertFalse(
            compute_is_overdue("not-a-date", "Unpaid", False, 30, now=self.now)
        )
        self.assertFalse(
            compute_is_overdue(None, "Unpaid", False, 30, now=self.now)
        )

    def test_exactly_overdue_days_is_not_overdue(self):
        # 30 days old with a 30-day threshold: strictly greater, so NOT overdue.
        memo_date = self.now - datetime.timedelta(days=30)
        self.assertFalse(
            compute_is_overdue(memo_date, "Unpaid", False, 30, now=self.now)
        )

    def test_one_day_past_the_threshold_is_overdue(self):
        memo_date = self.now - datetime.timedelta(days=31)
        self.assertTrue(
            compute_is_overdue(memo_date, "Unpaid", False, 30, now=self.now)
        )

    def test_accepts_iso_string_dates(self):
        self.assertTrue(
            compute_is_overdue("2026-01-01", "Unpaid", False, 30, now=self.now)
        )


class FeePropertyTests(SimpleTestCase):
    """Ports memoService.property.test.ts fee invariants as a seeded random loop."""

    def _round2(self, value):
        return Decimal(value).quantize(Decimal("0.01"))

    def test_property_fee_invariants(self):
        rng = random.Random(20260702)
        for _ in range(200):
            num_app = rng.randint(0, 9999)
            num_conf = rng.randint(0, 9999)
            rate_app = self._round2(rng.uniform(0, 1_000_000))
            rate_conf = self._round2(rng.uniform(0, 1_000_000))
            misc = self._round2(rng.uniform(0, 1_000_000))

            row = _row(
                num_appearances=num_app,
                fees_per_appearance=rate_app,
                num_conferences=num_conf,
                fees_per_conference=rate_conf,
                fees_misc_drafting=misc,
            )
            fees = resolve_memo_fees(row)

            # Property 12 & 13: line items = count * rate, total = sum of three.
            self.assertEqual(
                fees.fees_appearances, self._round2(num_app * rate_app)
            )
            self.assertEqual(
                fees.fees_conferences, self._round2(num_conf * rate_conf)
            )
            self.assertEqual(
                fees.total_fees,
                self._round2(
                    fees.fees_appearances + fees.fees_conferences + fees.fees_misc
                ),
            )

            # round2 keeps 2 dp, and non-negative inputs give non-negative fees.
            self.assertEqual(fees.total_fees.as_tuple().exponent, -2)
            self.assertGreaterEqual(fees.total_fees, Decimal("0"))

            # A positive total override always wins; 0/None never overrides (D3).
            override = self._round2(rng.uniform(1, 1_000_000))
            overridden = resolve_memo_fees(
                {**row, "custom_total_fees": override}
            )
            self.assertEqual(overridden.total_fees, self._round2(override))
            self.assertEqual(
                resolve_memo_fees({**row, "custom_total_fees": Decimal("0")}).total_fees,
                fees.total_fees,
            )

    def test_property_less_tds(self):
        rng = random.Random(15)
        for _ in range(200):
            total = self._round2(rng.uniform(0, 1_000_000))
            rate = self._round2(rng.uniform(0, 100))
            self.assertEqual(
                compute_less_tds(total, rate),
                self._round2(total * rate / Decimal(100)),
            )


class SingleImplementationGuardTests(SimpleTestCase):
    """R-MEMO-1: no fees module other than memo_fees may compute a line fee itself."""

    # Match ``num_appearances * fees_per_appearance`` and the conference twin,
    # allowing whitespace around the operator (``a*b``, ``a * b``).
    PATTERNS = [
        re.compile(r"num_appearances\s*\*\s*fees_per_appearance"),
        re.compile(r"num_conferences\s*\*\s*fees_per_conference"),
    ]

    def _fees_modules(self):
        package = importlib.import_module("fees")
        names = ["fees"]
        for info in pkgutil.walk_packages(package.__path__, prefix="fees."):
            names.append(info.name)
        return names

    def _source_of(self, module_name):
        module = importlib.import_module(module_name)
        loader = getattr(getattr(module, "__spec__", None), "loader", None)
        if loader is None or not hasattr(loader, "get_source"):
            return ""
        try:
            return loader.get_source(module_name) or ""
        except (OSError, ImportError):
            return ""

    def test_no_other_module_computes_line_fees(self):
        offenders = []
        for name in self._fees_modules():
            if ".migrations" in name or name.endswith(".migrations"):
                continue
            if ".tests" in name or name.endswith(".tests"):
                continue
            if name == "fees.services.memo_fees":
                continue
            source = self._source_of(name)
            for pattern in self.PATTERNS:
                if pattern.search(source):
                    offenders.append(name)
                    break
        self.assertEqual(
            offenders,
            [],
            f"modules computing line fees directly instead of calling resolve_memo_fees: {offenders}",
        )

    def test_guard_would_catch_a_violation(self):
        # Sanity: the pattern matches the forbidden expression it is meant to guard.
        self.assertTrue(
            self.PATTERNS[0].search("total = num_appearances * fees_per_appearance")
        )
