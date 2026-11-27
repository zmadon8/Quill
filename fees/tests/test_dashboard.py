"""Dashboard-service tests for the Fee Register (T3.7, R-RD-1).

Ports the dashboard-specific behaviour of ``dashboardService.ts`` to Django
``TestCase``:

* the KPI catalogue against hand-computed expected values (billed / received /
  memo / conference / draft counts this month, this FY and the rolling last-30
  days, outstanding, overdue, the draft memo count and total);
* THE SWITCH: with ``statistics_enabled`` False, ``get_dashboard_kpis`` runs
  inside ``with self.assertNumQueries(0):`` and returns the empty catalogue. The
  caller passes a pre-read ``settings`` dict so the switch short-circuits before
  any query (the documented contract on ``dashboard.get_dashboard_kpis``);
* appearances agreement: ``get_dashboard_summary(...).appearances_this_year``
  equals ``get_period_statistics(profile, 'financialYear', None, opts, now)`` for
  the current FY, and the month figure equals the statistics month period, for a
  fixed ``now`` (the dashboard sources appearances from the same engine);
* a ``memory``-tagged gate: ``get_dashboard_kpis`` over the planning dataset
  peaks under 3 MB.

Conventions mirror ``test_stats_cache.py`` / ``test_statistics.py``: a
``Profile(program=KEY_FEES)``, firms / groups / matters seeded with the raw ORM,
memos via ``memos.create_memo`` (so ``total_fees`` is stored) and payments via
``payments.add_payment_to_memo``. An early Initial FY is set with
``settings.update_settings`` in ``setUp`` so the historical FYs the tests seed
are not filtered by the statistics cutoff (gotcha 2: use the settings service,
never ``FeesSettings.objects.create`` after a mutator has touched the profile).

A fixed ``now`` of 20 Feb 2026 (inside FY 2025-26) keeps pro-rating and the
last-30-days window deterministic.
"""
import datetime
from decimal import ROUND_HALF_UP, Decimal
from unittest import mock

from django.test import TestCase, tag

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.models import Firm, Group, Matter
from fees.services import dashboard, payments, settings
from fees.services import memos as memos_service
from fees.services.statistics import get_period_statistics
from fees.services.statistics.periods import working_days_completed
from fees.tests.datasets import build_planning_dataset

# A fixed "now" in FY 2025-26; the last-30-days window is 22 Jan 2026 .. 20 Feb 2026 (30 days, today included).
NOW = datetime.date(2026, 2, 20)


def fees_profile(name="Ziyad-Dash"):
    return Profile.objects.create(program=KEY_FEES, name=name)


def early_initial_fy(profile):
    """Set an early Initial FY so historical FYs are not filtered (gotcha 2)."""
    settings.update_settings(profile, {"initial_financial_year": "2019-20"})


def make_firm(profile, name="Firm"):
    return Firm.objects.create(profile=profile, name=name)


def make_group(profile, firm, name="P"):
    return Group.objects.create(profile=profile, firm=firm, name=name)


def make_matter(profile, firm, group, name="M"):
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
# The KPI catalogue against hand-computed expected values.
# ---------------------------------------------------------------------------

class KpiCatalogueTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        early_initial_fy(self.profile)
        self.firm = make_firm(self.profile)
        self.group = make_group(self.profile, self.firm)
        self.matter = make_matter(self.profile, self.firm, self.group)

    def _seed(self):
        """Seeds a known fee dataset relative to NOW (20 Feb 2026, FY 2025-26).

        Memos:
          A  2026-02-10  misc 1000, 2 apps, 1 conf, 1 draft  (this month, FY, last30)
          B  2026-01-15  misc 2000, 1 app,  2 conf, 0 draft  (FY; last30 window
                                                              starts 22 Jan, so OUT of last30)
          C  2026-02-01  misc 3000, 3 apps, 0 conf, 2 drafts (this month, FY, last30)
          D  2025-05-10  misc 5000, 1 app,  0 conf           (older FY month)
          E  draft       misc  700, 0 apps                   (draft; current month)
        Payments (gross = amount + tds):
          A  2026-02-12  amount 500  tds 50   (this month, FY, last30)  gross 550
          B  2026-01-10  amount 800  tds 0    (FY; OUT of last30)       gross 800
          D  2025-06-01  amount 400  tds 0    (older FY)                gross 400
        """
        m = self.matter
        a = make_memo(self.profile, m, "2026-02-10", apps=2, misc=1000, confs=1, drafts=1)
        b = make_memo(self.profile, m, "2026-01-15", apps=1, misc=2000, confs=2)
        make_memo(self.profile, m, "2026-02-01", apps=3, misc=3000, drafts=2)
        d = make_memo(self.profile, m, "2025-05-10", apps=1, misc=5000)
        make_memo(self.profile, m, "", misc=700, is_draft=True)

        payments.add_payment_to_memo(
            self.profile, a.pk,
            dict(amount=500, auto_tds=False, tds_amount=50, date_of_payment="2026-02-12"),
        )
        payments.add_payment_to_memo(
            self.profile, b.pk,
            dict(amount=800, auto_tds=False, tds_amount=0, date_of_payment="2026-01-10"),
        )
        payments.add_payment_to_memo(
            self.profile, d.pk,
            dict(amount=400, auto_tds=False, tds_amount=0, date_of_payment="2025-06-01"),
        )

    def test_kpi_catalogue_matches_hand_computed_values(self):
        self._seed()
        kpis = dashboard.get_dashboard_kpis(self.profile, NOW)

        # Money values are returned as strings (JSON-safe); counts as ints.
        # Billed this month (Feb 2026): A 1000 + C 3000 = 4000.
        self.assertEqual(kpis["billed_this_month"], str(Decimal("4000.00")))
        # Billed this FY (2025-26): A 1000 + B 2000 + C 3000 + D 5000 = 11000.
        self.assertEqual(kpis["billed_this_year"], str(Decimal("11000.00")))
        # Billed last 30 (22 Jan .. 20 Feb): A 1000 + C 3000 = 4000 (B is 15 Jan, out).
        self.assertEqual(kpis["billed_last30"], str(Decimal("4000.00")))

        # Received (gross) this month (Feb 2026): A 550.
        self.assertEqual(kpis["received_this_month"], str(Decimal("550.00")))
        # Received this FY: A 550 + B 800 + D 400 = 1750.
        self.assertEqual(kpis["received_this_year"], str(Decimal("1750.00")))
        # Received last 30 (22 Jan .. 20 Feb): A 550 only (B paid 10 Jan, out).
        self.assertEqual(kpis["received_last30"], str(Decimal("550.00")))

        # Memo counts (non-draft): month A, C = 2; year A, B, C, D = 4; last30 A, C = 2.
        self.assertEqual(kpis["memos_this_month"], 2)
        self.assertEqual(kpis["memos_this_year"], 4)
        self.assertEqual(kpis["memos_last30"], 2)

        # Conference counts: month A(1)+C(0)=1; year A(1)+B(2)+C(0)+D(0)=3; last30 A(1)+C(0)=1.
        self.assertEqual(kpis["conferences_this_month"], 1)
        self.assertEqual(kpis["conferences_this_year"], 3)
        self.assertEqual(kpis["conferences_last30"], 1)

        # Appearances last30 (raw memo sum): A(2)+C(3)=5.
        self.assertEqual(kpis["appearances_last30"], 5)

        # Drafts (num_drafts field, non-draft memos): year A(1)+C(2)=3; last30 A(1)+C(2)=3.
        self.assertEqual(kpis["drafts_this_year"], 3)
        self.assertEqual(kpis["drafts_last30"], 3)

        # Draft memos (is_draft rows): one, total 700.
        self.assertEqual(kpis["draft_memos_count"], 1)
        self.assertEqual(kpis["draft_memos_total"], str(Decimal("700.00")))

        # Outstanding: every non-draft memo is unpaid by some amount.
        # A: 1000 - 550 = 450; B: 2000 - 800 = 1200; C: 3000 - 0 = 3000; D: 5000 - 400 = 4600.
        self.assertEqual(kpis["total_outstanding"], str(Decimal("9250.00")))
        self.assertEqual(kpis["memos_awaiting_payment"], 4)
        # No overdue days configured by default (overdue_days 0), so amount_overdue is 0.
        self.assertEqual(kpis["amount_overdue"], str(Decimal("0.00")))
        self.assertEqual(kpis["written_off_total"], str(Decimal("0.00")))

    def test_summary_matches_hand_computed_values(self):
        self._seed()
        summary = dashboard.get_dashboard_summary(self.profile, NOW)
        self.assertEqual(summary["billed_this_month"], Decimal("4000.00"))
        self.assertEqual(summary["billed_this_year"], Decimal("11000.00"))
        self.assertEqual(summary["received_this_month"], Decimal("550.00"))
        self.assertEqual(summary["received_this_year"], Decimal("1750.00"))
        self.assertEqual(summary["total_outstanding"], Decimal("9250.00"))
        self.assertEqual(summary["memos_awaiting_payment"], 4)
        self.assertEqual(summary["written_off_total"], Decimal("0.00"))


# ---------------------------------------------------------------------------
# THE SWITCH: zero queries when statistics_enabled is off.
# ---------------------------------------------------------------------------

class SwitchOffZeroQueriesTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        early_initial_fy(self.profile)
        firm = make_firm(self.profile)
        group = make_group(self.profile, firm)
        matter = make_matter(self.profile, firm, group)
        make_memo(self.profile, matter, "2026-02-10", apps=2, misc=1000)

    def test_switch_off_is_zero_queries_and_empty_result(self):
        off = {"statistics_enabled": False}
        with self.assertNumQueries(0):
            result = dashboard.get_dashboard_kpis(self.profile, NOW, settings=off)
        self.assertEqual(result, dashboard.EMPTY_KPIS)
        # Every id present and zeroed (money as "0", counts as 0).
        self.assertEqual(set(result.keys()), set(dashboard.KPI_IDS))
        self.assertEqual(result["billed_this_year"], "0")
        self.assertEqual(result["memos_this_year"], 0)

    def test_switch_on_computes_the_catalogue(self):
        on = {"statistics_enabled": True, "overdue_days": 0}
        result = dashboard.get_dashboard_kpis(self.profile, NOW, settings=on)
        self.assertEqual(result["billed_this_month"], str(Decimal("1000.00")))


# ---------------------------------------------------------------------------
# Fees / Day and Appearances / Week (owner round 2026-12).
# ---------------------------------------------------------------------------

class RateKpiTests(TestCase):
    """Fees / Day = billed / working days completed. Appearances / Week = appearances / working days completed * 5.

    NOW is 20 Feb 2026. Every month of FY 2025-26 from April to February has 20 working days entered (March has none).
    Working days completed: this month 20 * 20 / 28 = 14.3 -> 14; this year 10 full months (Apr to Jan) = 200, plus 14 = 214;
    the last 30 days (22 Jan to 20 Feb) are 10 of January's 31 days and 20 of February's 28: 20 * 10 / 31 + 20 * 20 / 28 = 20.7 -> 21.
    """

    def setUp(self):
        self.profile = fees_profile("Rate-Dash")
        early_initial_fy(self.profile)
        self.firm = make_firm(self.profile)
        self.group = make_group(self.profile, self.firm)
        self.matter = make_matter(self.profile, self.firm, self.group)

    _seed = KpiCatalogueTests._seed

    RATES = ("fees_per_day_last30", "fees_per_day_this_month", "fees_per_day_this_year",
             "appearances_per_week_last30", "appearances_per_week_this_month", "appearances_per_week_this_year")

    def _enter_working_days(self, per_month=20):
        from fees.services.statistics import save_adjustment
        for month in (4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2):
            save_adjustment(self.profile, {"financial_year": "2025-26", "month": month, "working_days": per_month})

    def test_working_days_completed(self):
        self._enter_working_days()
        self.assertEqual(working_days_completed(self.profile, NOW), {"month": 14, "year": 214, "last30": 21, "year_total": 220})

    def test_fees_a_day(self):
        self._seed()
        self._enter_working_days()
        kpis = dashboard.get_dashboard_kpis(self.profile, NOW, settings=_config(",".join(self.RATES[:3])))
        self.assertEqual(kpis["fees_per_day_last30"], "190.48")        # 4000 / 21
        self.assertEqual(kpis["fees_per_day_this_month"], "285.71")    # 4000 / 14
        self.assertEqual(kpis["fees_per_day_this_year"], "51.40")      # 11000 / 214
        self.assertEqual(dashboard.kpi_kind("fees_per_day_last30"), "money")

    def test_appearances_a_week_is_the_daily_figure_times_five(self):
        self._seed()
        self._enter_working_days()
        both = _config("appearances_last30,appearances_this_month,appearances_this_year," + ",".join(self.RATES[3:]))
        kpis = dashboard.get_dashboard_kpis(self.profile, NOW, settings=both)
        self.assertEqual(kpis["appearances_per_week_last30"], "1.2")   # 5 appearances: 5 * 5 / 21 = 1.19
        for rate, base, days in (("appearances_per_week_this_month", "appearances_this_month", 14),
                                 ("appearances_per_week_this_year", "appearances_this_year", 214)):
            want = (Decimal(kpis[base]) * 5 / days).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            self.assertEqual(kpis[rate], str(want), rate)
        self.assertEqual(dashboard.kpi_kind("appearances_per_week_last30"), "rate")

    def test_a_rate_alone_runs_the_group_of_its_base_and_nothing_else(self):
        self._seed()
        self._enter_working_days()
        with mock.patch.object(dashboard, "get_dashboard_summary", side_effect=AssertionError("summary")), \
                mock.patch.object(dashboard, "stats_appearances", side_effect=AssertionError("appearances")):
            kpis = dashboard.get_dashboard_kpis(self.profile, NOW, settings=_config("fees_per_day_last30"))
        self.assertEqual(kpis, {"fees_per_day_last30": "190.48"})

    def test_the_month_so_far_counts_the_working_days_gone(self):
        self._seed()
        self._enter_working_days()
        tenth = datetime.date(2026, 2, 10)
        kpis = dashboard.get_dashboard_kpis(self.profile, tenth, settings=_config("fees_per_day_this_month"))
        self.assertEqual(kpis["fees_per_day_this_month"], "571.43")   # 4000 billed / (20 * 10 / 28 = 7.1 -> 7 working days)

    def test_no_working_days_entered_is_zero(self):
        self._seed()
        kpis = dashboard.get_dashboard_kpis(self.profile, NOW, settings=_config(",".join(self.RATES)))
        self.assertEqual(kpis["fees_per_day_this_month"], "0.00")
        self.assertEqual(kpis["appearances_per_week_this_year"], "0.0")

    def test_nothing_billed_is_zero_and_switched_off_is_zero(self):
        self._enter_working_days()
        empty = dashboard.get_dashboard_kpis(self.profile, NOW, settings=_config(",".join(self.RATES)))
        self.assertEqual(empty["fees_per_day_this_year"], "0.00")
        self.assertEqual(empty["appearances_per_week_this_year"], "0.0")
        off = dashboard.get_dashboard_kpis(self.profile, NOW, settings={"statistics_enabled": False})
        self.assertEqual((off["fees_per_day_last30"], off["appearances_per_week_last30"]), ("0", "0.0"))


# ---------------------------------------------------------------------------
# Appearances agree with the statistics engine.
# ---------------------------------------------------------------------------

class AppearancesAgreementTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        early_initial_fy(self.profile)
        self.firm = make_firm(self.profile)
        self.group = make_group(self.profile, self.firm)
        self.matter = make_matter(self.profile, self.firm, self.group)

    def test_summary_appearances_equal_the_statistics_engine(self):
        m = self.matter
        make_memo(self.profile, m, "2025-04-10", apps=2, fee=100)
        make_memo(self.profile, m, "2026-02-05", apps=3, fee=100)
        make_memo(self.profile, m, "2025-07-10", apps=5, fee=100)

        opts = {"exclude_future_months": True, "pro_rate_current_month": True}
        years = get_period_statistics(self.profile, "financialYear", None, opts, NOW)
        fy_period = next(p for p in years["periods"] if p["key"] == "2025-26")

        summary = dashboard.get_dashboard_summary(self.profile, NOW)
        self.assertEqual(summary["appearances_this_year"], fy_period["num_appearances"])

        # The month figure the helper returns equals the statistics month period.
        months = get_period_statistics(self.profile, "month", "2025-26", opts, NOW)
        feb = next(p for p in months["periods"] if p["month"] == 2)
        helper = dashboard.stats_appearances(self.profile, NOW)
        self.assertEqual(helper["month"], feb["num_appearances"])
        self.assertEqual(helper["year"], fy_period["num_appearances"])

    def test_appearances_include_manual_extras_from_statistics(self):
        from fees.services.statistics import save_adjustment

        m = self.matter
        make_memo(self.profile, m, "2025-04-10", apps=3, fee=100)
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
        summary = dashboard.get_dashboard_summary(self.profile, NOW)
        # 3 real + 4 extra = 7, proving the dashboard reads the statistics engine.
        self.assertEqual(summary["appearances_this_year"], 7)


# ---------------------------------------------------------------------------
# Only the selected KPI groups are computed (items 2.4 and 2.12).
# ---------------------------------------------------------------------------

def _config(selection=""):
    return {
        "statistics_enabled": True,
        "overdue_days": 0,
        "dashboard_kpis": selection,
    }


class SelectedKpiGroupsTests(TestCase):
    def setUp(self):
        self.profile = fees_profile("Sel-Dash")
        early_initial_fy(self.profile)
        firm = make_firm(self.profile)
        group = make_group(self.profile, firm)
        matter = make_matter(self.profile, firm, group)
        make_memo(self.profile, matter, "2026-02-10", apps=2, misc=1000)

    def test_selected_ids_drop_unknown_and_default_to_everything(self):
        self.assertEqual(dashboard.selected_kpi_ids({}), list(dashboard.DEFAULT_KPI_IDS))
        self.assertEqual(dashboard.selected_kpi_ids({"dashboard_kpis": "nope, memos_last30"}), ["memos_last30"])
        self.assertEqual(dashboard.selected_kpi_ids({"dashboard_kpis": "nope"}), list(dashboard.DEFAULT_KPI_IDS))
        # The rates are offered on request; a Dashboard nobody changed does not gain them.
        self.assertEqual(set(dashboard.KPI_IDS) - set(dashboard.DEFAULT_KPI_IDS), set(dashboard.OPTIONAL_KPIS))

    def test_every_kpi_id_belongs_to_a_group(self):
        self.assertEqual(set(dashboard.KPI_GROUPS), set(dashboard.KPI_IDS))

    def test_only_the_received_group_runs_for_received_last30(self):
        with mock.patch.object(dashboard, "_compute_activity", side_effect=AssertionError("activity")), \
                mock.patch.object(dashboard, "get_dashboard_summary", side_effect=AssertionError("summary")), \
                mock.patch.object(dashboard, "stats_appearances", side_effect=AssertionError("appearances")):
            result = dashboard.get_dashboard_kpis(self.profile, NOW, settings=_config("received_last30"))
        self.assertEqual(list(result), ["received_last30"])
        self.assertEqual(result["received_last30"], "0.00")

    def test_activity_only_selection_skips_summary_and_statistics(self):
        with mock.patch.object(dashboard, "get_dashboard_summary", side_effect=AssertionError("summary")), \
                mock.patch.object(dashboard, "stats_appearances", side_effect=AssertionError("appearances")):
            result = dashboard.get_dashboard_kpis(self.profile, NOW, settings=_config("memos_this_month"))
        self.assertEqual(result, {"memos_this_month": 1})

    def test_summary_only_selection_does_not_call_the_statistics_engine(self):
        with mock.patch.object(dashboard, "stats_appearances", side_effect=AssertionError("appearances")), \
                mock.patch.object(dashboard, "_compute_activity", side_effect=AssertionError("activity")):
            result = dashboard.get_dashboard_kpis(self.profile, NOW, settings=_config("billed_this_month"))
        self.assertEqual(result, {"billed_this_month": "1000.00"})

    def test_appearances_selection_uses_the_statistics_engine_only(self):
        with mock.patch.object(dashboard, "get_dashboard_summary", side_effect=AssertionError("summary")), \
                mock.patch.object(dashboard, "_compute_activity", side_effect=AssertionError("activity")):
            result = dashboard.get_dashboard_kpis(self.profile, NOW, settings=_config("appearances_this_year"))
        self.assertEqual(list(result), ["appearances_this_year"])

    def test_default_selection_returns_the_whole_catalogue(self):
        result = dashboard.get_dashboard_kpis(self.profile, NOW, settings=_config(""))
        self.assertEqual(set(result), set(dashboard.DEFAULT_KPI_IDS))

    def test_a_changed_selection_is_not_served_from_the_other_selection_cache(self):
        first = dashboard.get_dashboard_kpis(self.profile, NOW, settings=_config("memos_this_month"))
        second = dashboard.get_dashboard_kpis(self.profile, NOW, settings=_config("billed_this_month"))
        self.assertEqual(list(first), ["memos_this_month"])
        self.assertEqual(list(second), ["billed_this_month"])
        again = dashboard.get_dashboard_kpis(self.profile, NOW, settings=_config("memos_this_month"))
        self.assertEqual(again, first)

    def test_the_cache_key_includes_the_order(self):
        a = dashboard.get_dashboard_kpis(self.profile, NOW, settings=_config("memos_this_month,billed_this_month"))
        b = dashboard.get_dashboard_kpis(self.profile, NOW, settings=_config("billed_this_month,memos_this_month"))
        self.assertEqual(list(a), ["memos_this_month", "billed_this_month"])
        self.assertEqual(list(b), ["billed_this_month", "memos_this_month"])


class KpiOrderingTests(TestCase):
    def test_every_kpi_id_sits_in_exactly_one_display_group_and_has_a_label(self):
        grouped = [kpi for _title, ids in dashboard.KPI_DISPLAY_GROUPS for kpi in ids]
        self.assertEqual(sorted(grouped), sorted(dashboard.KPI_IDS))
        self.assertEqual(len(grouped), len(set(grouped)))
        self.assertEqual(set(dashboard.KPI_LABELS), set(dashboard.KPI_IDS))
        self.assertEqual(
            [title for title, _ids in dashboard.KPI_DISPLAY_GROUPS],
            ["Billing", "Receipts", "Memos", "Appearances & work", "Outstanding"],
        )

    def test_saved_order_is_kept_and_duplicates_dropped(self):
        config = {"dashboard_kpis": "memos_last30,billed_this_year,memos_last30"}
        self.assertEqual(dashboard.selected_kpi_ids(config), ["memos_last30", "billed_this_year"])

    def test_order_kpis(self):
        self.assertEqual(
            dashboard.order_kpis(["a_bogus", "billed_this_year", "memos_last30"], ["memos_last30", "billed_this_year"]),
            ["memos_last30", "billed_this_year"],
        )
        self.assertEqual(
            dashboard.order_kpis(["billed_this_year", "memos_last30", "amount_overdue"], ["memos_last30", "billed_this_year"]),
            ["memos_last30", "billed_this_year", "amount_overdue"],
        )
        self.assertEqual(
            dashboard.order_kpis(["billed_this_year", "memos_last30"], ["billed_this_year", "memos_last30"], "memos_last30:up"),
            ["memos_last30", "billed_this_year"],
        )
        self.assertEqual(
            dashboard.order_kpis(["billed_this_year", "memos_last30"], ["billed_this_year", "memos_last30"], "billed_this_year:up"),
            ["billed_this_year", "memos_last30"],
        )


# ---------------------------------------------------------------------------
# Memory gate (tagged `memory`): the dashboard KPIs under 3 MB.
# ---------------------------------------------------------------------------

@tag("memory")
class DashboardMemoryTests(TestCase):
    def test_dashboard_kpis_peak_under_3_mb_on_planning_dataset(self):
        from fees.tests.memory import assert_peak_under

        profile = fees_profile("mem-dash")
        build_planning_dataset(profile)
        on = {
                "statistics_enabled": True,
            "overdue_days": 0,
            "initial_financial_year": "2015-16",
        }
        with assert_peak_under(self, 3):
            dashboard.get_dashboard_kpis(profile, settings=on)
