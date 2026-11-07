"""Statistics-service tests for the Fee Register (T3.8, design section 11).

Ports the three TypeScript statistics test files to Django ``TestCase``:

* ``statisticsService.test.ts``: the legacy ``get_statistics`` breakdown (by
  firm, FY descending), the Initial-FY / ``min_financial_year`` cutoff,
  ``mattersNew`` semantics, and receipt-basis attribution across
  ``get_period_statistics`` / ``get_year_end_summary`` / ``get_statistics`` /
  ``get_pivot``.
* ``statisticsPeriods.test.ts``: quarter roll-up equals the FY total,
  recovered vs received, fees-per-day, a monthly override replacing the computed
  value and rolling into the quarter / year then reverting when blanked,
  include-drafts counting in the current month, the year-end appearances
  agreeing with the table, the annual per-firm / per-matter breakdown with
  receipts by payment date, the multi-firm pivot filter, and the per-week
  measure from the period engine (5 * 5 / 20 = 1.25) raising when firm-filtered
  or given non-time rows.
* ``statisticsService.property.test.ts``: ported as a seeded ``random.Random``
  loop of 200 cases (not Hypothesis), each asserting ``get_statistics`` totals
  equal the sum of the individual memo values.

Plus query-count discipline (``assertNumQueries`` on the period engine and the
pivot) and ``memory``-tagged gates (statistics under 5 MB, pivot under 8 MB on
the planning dataset).

Conventions mirror ``test_outstanding.py`` / ``test_stats_cache.py``: a
``Profile(program=KEY_FEES)``, firms / groups / matters seeded with the raw ORM,
memos via ``memos.create_memo`` (so ``total_fees`` is stored) and payments via
``payments.add_payment_to_memo``. An early Initial FY is set with
``settings.update_settings`` in ``setUp`` so the historical FYs the tests seed
are not filtered by the cutoff (gotcha 2: use the settings service, never
``FeesSettings.objects.create`` after a mutator has touched the profile).

The TS source calls the sub-firm division "partner"; the model is ``Group``, so
the pivot ``partner`` dimension reads the group.
"""
import datetime
import random
from decimal import Decimal

from django.test import TestCase, tag

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.errors import FeesError
from fees.models import Firm, Group, Matter
from fees.services import payments, settings
from fees.services import memos as memos_service
from fees.services.statistics import (
    get_annual_breakdown,
    get_period_statistics,
    get_pivot,
    get_statistics,
    get_year_end_summary,
    list_adjustments,
    save_adjustment,
)
from fees.tests.datasets import build_planning_dataset
from fees.tests.memory import assert_peak_under

# A fixed "now" in the middle of 2025-26 keeps pro-rating out of past months.
NOW = datetime.date(2026, 2, 20)  # 20 Feb 2026


def fees_profile(name="Ziyad-Stats"):
    return Profile.objects.create(program=KEY_FEES, name=name)


def early_initial_fy(profile):
    """Set an early Initial FY so historical FYs are not filtered (gotcha 2)."""
    settings.update_settings(
        profile, {"initial_financial_year": "2019-20", "feebook_start_year": "2019-20"}
    )


def make_firm(profile, name):
    return Firm.objects.create(profile=profile, name=name)


def make_group(profile, firm, name):
    return Group.objects.create(profile=profile, firm=firm, name=name)


def make_matter(profile, firm, group, name):
    return Matter.objects.create(profile=profile, firm=firm, group=group, name=name)


def make_memo(profile, matter, date, apps=0, fee=0, misc=0, confs=0, fee_conf=0,
              drafts=0, is_draft=False):
    """Creates a memo through the service so ``total_fees`` is stored."""
    return memos_service.create_memo(
        profile,
        dict(
            date=date,
            matter_id=matter.pk,
            addressee_line1="A",
            num_appearances=apps,
            fees_per_appearance=fee,
            num_conferences=confs,
            fees_per_conference=fee_conf,
            fees_misc_drafting=misc,
            num_drafts=drafts,
        ),
        is_draft,
    )


# ---------------------------------------------------------------------------
# statisticsService.test.ts
# ---------------------------------------------------------------------------

class LegacyStatisticsTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        early_initial_fy(self.profile)

    def test_aggregates_appearances_billed_received_by_firm(self):
        firm = make_firm(self.profile, "Firm")
        group = make_group(self.profile, firm, "P")
        matter = make_matter(self.profile, firm, group, "M")
        memo = make_memo(self.profile, matter, "2026-07-15", apps=3, fee=1000, misc=500)
        payments.add_payment_to_memo(
            self.profile, memo.pk, dict(amount=2000, date_of_payment="2026-08-01")
        )

        stats = get_statistics(self.profile, "firm")
        self.assertEqual(len(stats["rows"]), 1)
        self.assertEqual(stats["rows"][0]["num_appearances"], 3)
        self.assertEqual(stats["rows"][0]["amount_billed"], Decimal("3500"))
        self.assertEqual(stats["rows"][0]["amount_received"], Decimal("2000"))
        self.assertEqual(stats["totals"]["amount_billed"], Decimal("3500"))

    def test_orders_financial_year_breakdown_descending(self):
        firm = make_firm(self.profile, "Firm")
        group = make_group(self.profile, firm, "P")
        matter = make_matter(self.profile, firm, group, "M")
        make_memo(self.profile, matter, "2025-07-15", apps=1, fee=100)
        make_memo(self.profile, matter, "2026-07-15", apps=1, fee=100)
        stats = get_statistics(self.profile, "financialYear")
        self.assertEqual(
            [r["key"] for r in stats["rows"]], ["2026-27", "2025-26"]
        )

    def test_year_wise_honours_min_financial_year_cutoff(self):
        firm = make_firm(self.profile, "Firm")
        group = make_group(self.profile, firm, "P")
        matter = make_matter(self.profile, firm, group, "M")
        make_memo(self.profile, matter, "2024-07-15", apps=1, fee=100)
        make_memo(self.profile, matter, "2025-07-15", apps=1, fee=100)
        make_memo(self.profile, matter, "2026-07-15", apps=1, fee=100)

        all_p = get_period_statistics(self.profile, "financialYear", None, {})
        self.assertEqual(
            [p["key"] for p in all_p["periods"]], ["2026-27", "2025-26", "2024-25"]
        )
        capped = get_period_statistics(
            self.profile, "financialYear", None, {"min_financial_year": "2026-27"}
        )
        self.assertEqual([p["key"] for p in capped["periods"]], ["2026-27"])

    def test_matters_new_counts_only_in_first_ever_fy(self):
        firm = make_firm(self.profile, "Firm")
        group = make_group(self.profile, firm, "P")
        ma = make_matter(self.profile, firm, group, "MA")
        make_memo(self.profile, ma, "2025-07-15", apps=1, fee=100)
        make_memo(self.profile, ma, "2026-07-15", apps=1, fee=100)
        mb = make_matter(self.profile, firm, group, "MB")
        make_memo(self.profile, mb, "2026-08-01", apps=1, fee=100)

        pivot = get_pivot(
            self.profile,
            {"measure": "mattersNew", "row_dim": "financialYear", "col_dim": "none"},
        )
        by_fy = {r["key"]: r["total"] for r in pivot["rows"]}
        self.assertEqual(by_fy["2025-26"], 1)
        self.assertEqual(by_fy["2026-27"], 1)
        self.assertEqual(pivot["grand_total"], 2)

        distinct = get_pivot(
            self.profile,
            {"measure": "matters", "row_dim": "financialYear", "col_dim": "none"},
        )
        d_by_fy = {r["key"]: r["total"] for r in distinct["rows"]}
        self.assertEqual(d_by_fy["2025-26"], 1)
        self.assertEqual(d_by_fy["2026-27"], 2)

    def test_matters_new_ignores_memos_outside_range_when_deciding_first(self):
        firm = make_firm(self.profile, "Firm")
        group = make_group(self.profile, firm, "P")
        matter = make_matter(self.profile, firm, group, "M")
        make_memo(self.profile, matter, "2024-07-15", apps=1, fee=100)
        make_memo(self.profile, matter, "2026-07-15", apps=1, fee=100)
        pivot = get_pivot(
            self.profile,
            {
                "measure": "mattersNew",
                "row_dim": "financialYear",
                "col_dim": "none",
                "from_fy": "2025-26",
            },
        )
        self.assertEqual(pivot["grand_total"], 0)


class ReceiptBasisTests(TestCase):
    """Received is attributed by the payment date (receipt basis)."""

    def setUp(self):
        self.profile = fees_profile()
        early_initial_fy(self.profile)
        # A memo billed in FY 2025-26, paid in FY 2026-27.
        firm = make_firm(self.profile, "Firm")
        group = make_group(self.profile, firm, "P")
        matter = make_matter(self.profile, firm, group, "M")
        memo = make_memo(self.profile, matter, "2026-01-10", misc=5000)  # FY 2025-26
        payments.add_payment_to_memo(
            self.profile,
            memo.pk,
            dict(
                amount=4500,
                auto_tds=False,
                tds_amount=500,
                date_of_payment="2026-08-25",  # FY 2026-27
            ),
        )

    def test_period_statistics_received_in_payment_year(self):
        by_fy = get_period_statistics(self.profile, "financialYear", None, {})
        p2025 = next(p for p in by_fy["periods"] if p["key"] == "2025-26")
        p2026 = next(p for p in by_fy["periods"] if p["key"] == "2026-27")
        self.assertEqual(p2025["amount_billed"], Decimal("5000"))
        self.assertEqual(p2025["amount_received"], Decimal("0"))
        self.assertEqual(p2026["amount_received"], Decimal("4500"))
        self.assertEqual(p2026["amount_received_plus_tds"], Decimal("5000"))
        self.assertEqual(p2026["amount_billed"], Decimal("0"))

    def test_year_end_summary_received_and_tds_in_payment_year(self):
        bill_year = get_year_end_summary(self.profile, "2025-26")
        self.assertEqual(bill_year["total_billed"], Decimal("5000"))
        self.assertEqual(bill_year["total_received"], Decimal("0"))
        self.assertEqual(bill_year["total_tds"], Decimal("0"))

        pay_year = get_year_end_summary(self.profile, "2026-27")
        self.assertEqual(pay_year["total_billed"], Decimal("0"))
        self.assertEqual(pay_year["total_received"], Decimal("4500"))
        self.assertEqual(pay_year["total_tds"], Decimal("500"))

    def test_get_statistics_fy_breakdown_received_by_payment_year(self):
        stats = get_statistics(self.profile, "financialYear")
        rows = {r["key"]: r for r in stats["rows"]}
        self.assertEqual(rows["2025-26"]["amount_billed"], Decimal("5000"))
        self.assertEqual(rows["2025-26"]["amount_received"], Decimal("0"))
        self.assertEqual(rows["2026-27"]["amount_received"], Decimal("4500"))
        self.assertEqual(stats["totals"]["amount_received"], Decimal("4500"))

    def test_get_pivot_received_by_fy_uses_payment_year(self):
        pivot = get_pivot(
            self.profile,
            {"measure": "received", "row_dim": "financialYear", "col_dim": "none"},
        )
        by_fy = {r["key"]: r["total"] for r in pivot["rows"]}
        self.assertEqual(by_fy["2026-27"], Decimal("4500"))
        self.assertEqual(by_fy.get("2025-26", Decimal("0")), Decimal("0"))
        self.assertEqual(pivot["grand_total"], Decimal("4500"))

        gross = get_pivot(
            self.profile,
            {
                "measure": "receivedPlusTds",
                "row_dim": "financialYear",
                "col_dim": "none",
            },
        )
        g_by_fy = {r["key"]: r["total"] for r in gross["rows"]}
        self.assertEqual(g_by_fy["2026-27"], Decimal("5000"))


# ---------------------------------------------------------------------------
# statisticsPeriods.test.ts
# ---------------------------------------------------------------------------

class PeriodsWorld:
    """Two firms, two groups, two matters and a memo-maker (mirrors the TS ``world``)."""

    def __init__(self, profile):
        self.profile = profile
        self.f = make_firm(profile, "Firm A")
        self.f2 = make_firm(profile, "Firm B")
        self.p = make_group(profile, self.f, "P")
        self.p2 = make_group(profile, self.f2, "P2")
        self.m = make_matter(profile, self.f, self.p, "M1")
        self.m2 = make_matter(profile, self.f2, self.p2, "M2")

    def mk(self, matter, date, apps, fee):
        return make_memo(self.profile, matter, date, apps=apps, fee=fee)


class QuarterStatisticsTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        early_initial_fy(self.profile)
        self.w = PeriodsWorld(self.profile)

    def test_sums_months_into_fy_quarters_and_matches_year_total(self):
        w = self.w
        w.mk(w.m, "2025-04-10", 2, 1000)  # Q1
        w.mk(w.m, "2025-06-10", 1, 1000)  # Q1
        w.mk(w.m, "2025-08-10", 4, 1000)  # Q2
        w.mk(w.m, "2026-01-10", 3, 1000)  # Q4
        q = get_period_statistics(self.profile, "quarter", "2025-26", {}, NOW)
        self.assertEqual(
            [p["key"] for p in q["periods"]],
            ["2025-26-Q1", "2025-26-Q2", "2025-26-Q3", "2025-26-Q4"],
        )
        self.assertEqual(
            [p["num_appearances"] for p in q["periods"]], [3, 4, 0, 3]
        )
        self.assertEqual(q["periods"][0]["amount_billed"], Decimal("3000"))

        y = next(
            p
            for p in get_period_statistics(
                self.profile, "financialYear", None, {}, NOW
            )["periods"]
            if p["key"] == "2025-26"
        )
        self.assertEqual(y["num_appearances"], 10)
        self.assertEqual(y["amount_billed"], Decimal("10000"))


class RecoveredFeesAndOverrideTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        early_initial_fy(self.profile)
        self.w = PeriodsWorld(self.profile)

    def test_recovered_counts_gross_paid_on_memos_issued_in_period(self):
        w = self.w
        a = w.mk(w.m, "2025-04-10", 1, 1000)
        payments.add_payment_to_memo(
            self.profile, a.pk, dict(amount=400, date_of_payment="2025-07-01")
        )
        apr = next(
            p
            for p in get_period_statistics(
                self.profile, "month", "2025-26", {}, NOW
            )["periods"]
            if p["month"] == 4
        )
        self.assertEqual(apr["amount_recovered"], Decimal("400"))
        self.assertEqual(apr["percent_recovered"], Decimal("40"))
        jul = next(
            p
            for p in get_period_statistics(
                self.profile, "month", "2025-26", {}, NOW
            )["periods"]
            if p["month"] == 7
        )
        self.assertEqual(jul["amount_received"], Decimal("400"))
        self.assertEqual(jul["amount_recovered"], Decimal("0"))

    def test_fees_per_day_is_billed_over_days_completed(self):
        w = self.w
        w.mk(w.m, "2025-04-10", 1, 1000)
        save_adjustment(
            self.profile,
            {
                "financial_year": "2025-26",
                "month": 4,
                "working_days": 20,
                "extra_appearances": 0,
                "extra_conferences": 0,
                "extra_drafts": 0,
            },
        )
        apr = next(
            p
            for p in get_period_statistics(
                self.profile, "month", "2025-26", {}, NOW
            )["periods"]
            if p["month"] == 4
        )
        self.assertEqual(apr["fees_per_day"], Decimal("50"))

    def test_monthly_override_replaces_computed_rolls_up_then_reverts(self):
        w = self.w
        w.mk(w.m, "2025-04-10", 2, 1000)
        save_adjustment(
            self.profile,
            {
                "financial_year": "2025-26",
                "month": 4,
                "working_days": 0,
                "extra_appearances": 0,
                "extra_conferences": 0,
                "extra_drafts": 0,
                "override_appearances": 9,
                "override_billed": 5000,
            },
        )
        apr = next(
            p
            for p in get_period_statistics(
                self.profile, "month", "2025-26", {}, NOW
            )["periods"]
            if p["month"] == 4
        )
        self.assertEqual(apr["num_appearances"], 9)
        self.assertEqual(apr["amount_billed"], Decimal("5000"))
        self.assertIn("num_appearances", apr["overridden"])
        self.assertIn("amount_billed", apr["overridden"])

        q1 = get_period_statistics(self.profile, "quarter", "2025-26", {}, NOW)[
            "periods"
        ][0]
        self.assertEqual(q1["num_appearances"], 9)
        y = next(
            p
            for p in get_period_statistics(
                self.profile, "financialYear", None, {}, NOW
            )["periods"]
            if p["key"] == "2025-26"
        )
        self.assertEqual(y["amount_billed"], Decimal("5000"))

        # Blank override (null) goes back to the computed figure.
        save_adjustment(
            self.profile,
            {
                "financial_year": "2025-26",
                "month": 4,
                "working_days": 0,
                "extra_appearances": 0,
                "extra_conferences": 0,
                "extra_drafts": 0,
            },
        )
        self.assertIsNone(
            list_adjustments(self.profile, "2025-26")[0]["override_appearances"]
        )
        reverted = next(
            p
            for p in get_period_statistics(
                self.profile, "month", "2025-26", {}, NOW
            )["periods"]
            if p["month"] == 4
        )
        self.assertEqual(reverted["num_appearances"], 2)


class IncludeDraftTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        early_initial_fy(self.profile)
        self.w = PeriodsWorld(self.profile)

    def test_counts_a_draft_in_current_month_only_when_asked(self):
        # A draft (no date) counts as issued in the current month (Feb 2026).
        make_memo(
            self.profile, self.w.m, "", apps=2, fee=500, is_draft=True
        )

        def feb(opts):
            return next(
                p
                for p in get_period_statistics(
                    self.profile, "month", "2025-26", opts, NOW
                )["periods"]
                if p["month"] == 2
            )

        self.assertEqual(feb({})["amount_billed"], Decimal("0"))
        self.assertEqual(feb({"include_drafts": True})["amount_billed"], Decimal("1000"))
        self.assertEqual(feb({"include_drafts": True})["num_appearances"], 2)


class YearEndAndAnnualTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        early_initial_fy(self.profile)
        self.w = PeriodsWorld(self.profile)

    def test_year_end_appearances_agree_with_the_table(self):
        w = self.w
        w.mk(w.m, "2025-04-10", 3, 100)
        save_adjustment(
            self.profile,
            {
                "financial_year": "2025-26",
                "month": 5,
                "working_days": 0,
                "extra_appearances": 4,
                "extra_conferences": 0,
                "extra_drafts": 0,
            },
        )
        ye = get_year_end_summary(self.profile, "2025-26")
        self.assertEqual(ye["num_appearances"], 7)

    def test_breaks_year_down_per_firm_and_matter_with_receipts(self):
        w = self.w
        a = w.mk(w.m, "2025-04-10", 1, 1000)
        w.mk(w.m2, "2025-05-10", 2, 500)
        payments.add_payment_to_memo(
            self.profile,
            a.pk,
            dict(
                amount=600, auto_tds=False, tds_amount=60, date_of_payment="2025-09-01"
            ),
        )
        by_firm = get_annual_breakdown(self.profile, "2025-26", "firm")
        self.assertEqual([r["name"] for r in by_firm], ["Firm A", "Firm B"])
        self.assertEqual(by_firm[0]["memos"], 1)
        self.assertEqual(by_firm[0]["billed"], Decimal("1000"))
        self.assertEqual(by_firm[0]["received"], Decimal("600"))
        self.assertEqual(by_firm[0]["tds"], Decimal("60"))
        self.assertEqual(by_firm[1]["memos"], 1)
        self.assertEqual(by_firm[1]["appearances"], 2)
        self.assertEqual(by_firm[1]["billed"], Decimal("1000"))
        self.assertEqual(by_firm[1]["received"], Decimal("0"))

        by_matter = get_annual_breakdown(self.profile, "2025-26", "matter")
        self.assertEqual([r["firm_name"] for r in by_matter], ["Firm A", "Firm B"])


class PivotExtraTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        early_initial_fy(self.profile)
        self.w = PeriodsWorld(self.profile)

    def test_filters_by_several_firms(self):
        w = self.w
        w.mk(w.m, "2025-04-10", 1, 1000)
        w.mk(w.m2, "2025-04-11", 1, 300)
        both = get_pivot(
            self.profile,
            {
                "measure": "billed",
                "row_dim": "financialYear",
                "col_dim": "none",
                "firm_ids": [w.f.pk, w.f2.pk],
            },
        )
        self.assertEqual(both["grand_total"], Decimal("1300"))
        one = get_pivot(
            self.profile,
            {
                "measure": "billed",
                "row_dim": "financialYear",
                "col_dim": "none",
                "firm_ids": [w.f2.pk],
            },
        )
        self.assertEqual(one["grand_total"], Decimal("300"))
        all_p = get_pivot(
            self.profile,
            {"measure": "billed", "row_dim": "financialYear", "col_dim": "none"},
        )
        self.assertEqual(all_p["grand_total"], Decimal("1300"))

    def test_per_week_measures_from_the_period_engine_need_time_rows(self):
        w = self.w
        w.mk(w.m, "2025-04-10", 5, 100)
        save_adjustment(
            self.profile,
            {
                "financial_year": "2025-26",
                "month": 4,
                "working_days": 20,
                "extra_appearances": 0,
                "extra_conferences": 0,
                "extra_drafts": 0,
            },
        )
        r = get_pivot(
            self.profile,
            {
                "measure": "appearancesPerWeek",
                "row_dim": "month",
                "col_dim": "none",
                "from_fy": "2025-26",
                "to_fy": "2025-26",
            },
        )
        apr = next(x for x in r["rows"] if x["label"].startswith("Apr"))
        self.assertEqual(apr["total"], Decimal("1.25"))  # 5 * 5 / 20

        with self.assertRaises(FeesError):
            get_pivot(
                self.profile,
                {
                    "measure": "appearancesPerWeek",
                    "row_dim": "firm",
                    "col_dim": "none",
                },
            )


# ---------------------------------------------------------------------------
# Query-count discipline (assertNumQueries bounds, design line 75)
# ---------------------------------------------------------------------------

class QueryCountTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        early_initial_fy(self.profile)
        self.w = PeriodsWorld(self.profile)
        # Seed several memos and payments across FYs so the count is exercised
        # against real data, not an empty profile.
        for i, date in enumerate(
            ["2024-05-10", "2025-04-10", "2025-08-10", "2026-01-10", "2026-02-02"]
        ):
            memo = self.w.mk(self.w.m, date, i + 1, 100)
            payments.add_payment_to_memo(
                self.profile, memo.pk, dict(amount=50, date_of_payment=date)
            )

    def test_period_statistics_is_a_constant_small_number_of_queries(self):
        # settings read + three group-bys (memos, receipts, recovered) + the
        # adjustments read = five queries, independent of dataset size.
        with self.assertNumQueries(5):
            get_period_statistics(self.profile, "financialYear", None, {}, NOW)

    def test_period_statistics_month_also_five_queries(self):
        with self.assertNumQueries(5):
            get_period_statistics(self.profile, "month", "2025-26", {}, NOW)

    def test_pivot_billed_is_two_queries(self):
        # settings read + the single memo driving query.
        with self.assertNumQueries(2):
            get_pivot(
                self.profile,
                {"measure": "billed", "row_dim": "financialYear", "col_dim": "none"},
            )

    def test_pivot_matters_new_is_three_queries(self):
        # settings read + first-memo-by-matter read + the memo driving query.
        with self.assertNumQueries(3):
            get_pivot(
                self.profile,
                {
                    "measure": "mattersNew",
                    "row_dim": "financialYear",
                    "col_dim": "none",
                },
            )


# ---------------------------------------------------------------------------
# Property test (seeded loop of 200 cases, ported from the fast-check property)
# ---------------------------------------------------------------------------

class PropertyTests(TestCase):
    def test_aggregates_equal_the_sum_of_individual_memo_values(self):
        rng = random.Random(2108)
        for _case in range(200):
            profile = fees_profile(name=f"prop-{_case}")
            settings.update_settings(
                profile, {"initial_financial_year": "2019-20"}
            )
            firm = make_firm(profile, "Firm")
            group = make_group(profile, firm, "P")
            matter = make_matter(profile, firm, group, "M")

            expect_apps = 0
            expect_billed = Decimal("0")
            count = rng.randint(0, 8)
            for _i in range(count):
                n_app = rng.randint(0, 50)
                f_app = rng.randint(0, 10000)
                misc = rng.randint(0, 10000)
                make_memo(profile, matter, "2026-07-15", apps=n_app, fee=f_app, misc=misc)
                expect_apps += n_app
                expect_billed = (
                    expect_billed
                    + Decimal(n_app * f_app)
                    + Decimal(misc)
                )

            stats = get_statistics(profile, "firm")
            totals = stats["totals"]
            self.assertEqual(totals["num_appearances"], expect_apps)
            self.assertLess(
                abs(totals["amount_billed"] - expect_billed), Decimal("0.01")
            )
            self.assertEqual(totals["amount_received"], Decimal("0"))


# ---------------------------------------------------------------------------
# Memory gates (tagged `memory`): statistics < 5 MB, pivot < 8 MB.
# ---------------------------------------------------------------------------

@tag("memory")
class StatisticsMemoryTests(TestCase):
    def test_period_statistics_peaks_under_5_mb_on_planning_dataset(self):
        profile = fees_profile("mem-stats")
        build_planning_dataset(profile)
        with assert_peak_under(self, 5):
            get_period_statistics(profile, "financialYear", None, {})

    def test_pivot_peaks_under_8_mb_on_planning_dataset(self):
        profile = fees_profile("mem-pivot")
        build_planning_dataset(profile)
        with assert_peak_under(self, 8):
            get_pivot(
                profile,
                {"measure": "billed", "row_dim": "month", "col_dim": "financialYear"},
            )
