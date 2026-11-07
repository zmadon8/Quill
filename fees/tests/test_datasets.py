"""Tests for the seeded planning-dataset generator and the memory helper (T1.11, R-NFR-7).

Two kinds of test:

* a fast one that builds a small dataset (200 memos) and asserts the summary counts and that the
  children are FK-valid and scoped to the profile, so CI verifies the generator on every run without
  spending the full-size build time;
* a ``memory``-tagged one that builds the full planning dataset (6,000 memos, 8,000 payments, 9,000
  allocations) and asserts the counts. CI runs memory-tagged tests, so this is the "dataset builds in
  under 30 s" gate; it is kept minimal (build plus count asserts, no heavy operation).

The shared ``assert_peak_under`` helper is exercised here too so a regression in the helper is caught.
"""
from django.test import TestCase, tag

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.models import (
    Allocation,
    Firm,
    Group,
    Matter,
    Memo,
    Payment,
    PeriodAdjustment,
)
from fees.tests.datasets import build_planning_dataset, twelve_years_of_adjustments
from fees.tests.memory import assert_peak_under


def a_fees_profile(name="Dataset"):
    return Profile.objects.create(program=KEY_FEES, name=name)


class SmallDatasetTests(TestCase):
    """A small, deterministic build checks the shape of the dataset cheaply on every CI run."""

    def test_summary_counts_match_the_rows_created(self):
        profile = a_fees_profile()
        summary = build_planning_dataset(
            profile, memos=200, payments=150, allocations=180, seed=1
        )
        self.assertEqual(summary["memos"], 200)
        self.assertEqual(summary["payments"], 150)
        self.assertEqual(summary["allocations"], 180)
        self.assertEqual(Memo.objects.filter(profile=profile).count(), 200)
        self.assertEqual(Payment.objects.filter(profile=profile).count(), 150)
        self.assertEqual(Allocation.objects.filter(profile=profile).count(), 180)
        self.assertEqual(Firm.objects.filter(profile=profile).count(), summary["firms"])
        self.assertEqual(Group.objects.filter(profile=profile).count(), summary["groups"])
        self.assertEqual(Matter.objects.filter(profile=profile).count(), summary["matters"])

    def test_children_are_fk_valid_and_scoped_to_the_profile(self):
        profile = a_fees_profile()
        build_planning_dataset(profile, memos=200, payments=150, allocations=180, seed=1)
        memo_ids = set(Memo.objects.filter(profile=profile).values_list("pk", flat=True))
        payment_ids = set(Payment.objects.filter(profile=profile).values_list("pk", flat=True))
        for alloc in Allocation.objects.filter(profile=profile):
            self.assertIn(alloc.memo_id, memo_ids)
            self.assertIn(alloc.payment_id, payment_ids)
            self.assertEqual(alloc.profile_id, profile.pk)
        # Every memo points at a matter/firm/group that exists in this profile.
        firm_ids = set(Firm.objects.filter(profile=profile).values_list("pk", flat=True))
        for memo in Memo.objects.filter(profile=profile):
            self.assertIn(memo.firm_id, firm_ids)
            self.assertEqual(memo.matter.firm_id, memo.firm_id)

    def test_memos_spread_across_several_financial_years(self):
        profile = a_fees_profile()
        build_planning_dataset(profile, memos=300, payments=100, allocations=100, seed=2)
        years = set(Memo.objects.filter(profile=profile).values_list("financial_year", flat=True))
        self.assertGreater(len(years), 1)
        # The financial year is consistent with the memo date (date falls inside the FY).
        for memo in Memo.objects.filter(profile=profile)[:50]:
            start = int(memo.financial_year.split("-")[0])
            self.assertTrue(
                (memo.date.year == start and memo.date.month >= 4)
                or (memo.date.year == start + 1 and memo.date.month <= 3)
            )

    def test_memo_numbers_are_unique_within_the_profile(self):
        profile = a_fees_profile()
        build_planning_dataset(profile, memos=200, payments=10, allocations=10, seed=3)
        numbers = list(Memo.objects.filter(profile=profile).values_list("memo_number", flat=True))
        self.assertEqual(len(numbers), len(set(numbers)))

    def test_deterministic_for_a_fixed_seed(self):
        first = a_fees_profile("A")
        second = a_fees_profile("B")
        build_planning_dataset(first, memos=100, payments=80, allocations=90, seed=7)
        build_planning_dataset(second, memos=100, payments=80, allocations=90, seed=7)
        totals_a = list(
            Memo.objects.filter(profile=first).order_by("seq").values_list("total_fees", flat=True)
        )
        totals_b = list(
            Memo.objects.filter(profile=second).order_by("seq").values_list("total_fees", flat=True)
        )
        self.assertEqual(totals_a, totals_b)

    def test_twelve_years_of_adjustments_are_month_1_to_12(self):
        profile = a_fees_profile()
        count = twelve_years_of_adjustments(profile)
        self.assertEqual(count, 12 * 12)
        self.assertEqual(PeriodAdjustment.objects.filter(profile=profile).count(), 12 * 12)
        months = set(PeriodAdjustment.objects.values_list("month", flat=True))
        self.assertEqual(months, set(range(1, 13)))


class MemoryHelperTests(TestCase):
    """The shared ``assert_peak_under`` passes well under its cap and yields the measured peak."""

    def test_small_allocation_passes_and_reports_the_peak(self):
        with assert_peak_under(self, 50) as peak_box:
            _blob = [0] * 1000
        self.assertGreaterEqual(peak_box[0], 0)


@tag("memory")
class PlanningDatasetBuildGateTests(TestCase):
    """The full planning dataset builds with ``bulk_create`` (the under 30 s CI gate, R-NFR-7)."""

    def test_full_planning_dataset_builds_and_counts_match(self):
        profile = a_fees_profile("Full")
        summary = build_planning_dataset(profile)
        self.assertEqual(summary["memos"], 6000)
        self.assertEqual(summary["payments"], 8000)
        self.assertEqual(summary["allocations"], 9000)
        self.assertEqual(summary["adjustments"], 12 * 12)
        self.assertEqual(Memo.objects.filter(profile=profile).count(), 6000)
        self.assertEqual(Payment.objects.filter(profile=profile).count(), 8000)
        self.assertEqual(Allocation.objects.filter(profile=profile).count(), 9000)
        self.assertEqual(PeriodAdjustment.objects.filter(profile=profile).count(), 12 * 12)
