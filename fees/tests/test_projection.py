"""Projected Totals (owner round 2026-11): the arithmetic, the Dashboard boxes and bars, and the Statistics > Standard charts.

Projected for the year = so far / working days completed so far x working days entered for the whole financial year; a month
with none entered counts 0; nothing is projected before a working day is completed.
"""
import datetime
from decimal import Decimal

from django.test import SimpleTestCase
from django.urls import reverse

from fees.services import dashboard, dashboard_panels
from fees.services.financial_year import current_financial_year
from fees.services.statistics import save_adjustment
from fees.services.statistics.periods import FY_MONTH_ORDER, month_working_days, working_days_completed
from fees.services.statistics.projection import project_months, project_total
from fees.models import Matter, PeriodAdjustment
from fees.tests.test_dashboard import make_memo
from fees.tests.test_ui_pages import UiPageBase

# The worked example of the design (19 Nov 2026, FY 2026-27).
WD = [20, 18, 10, 22, 21, 21, 20, 20, 16, 21, 20, 21]
DONE = [20, 18, 10, 22, 21, 21, 20, 13, 0, 0, 0, 0]
BILLED = [320000, 260000, 110000, 400000, 380000, 360000, 350000, 210000, 0, 0, 0, 0]


class ArithmeticTests(SimpleTestCase):
    def test_the_worked_example(self):
        plan = project_months(BILLED, list(zip(WD, DONE)))
        self.assertEqual((plan["done"], plan["total"]), (145, 230))
        self.assertEqual(plan["so_far"], Decimal("2390000.00"))
        self.assertEqual(plan["projected"], Decimal("3791034.48"))  # 23,90,000 / 145 x 230
        nov, dec = plan["months"][7], plan["months"][8]
        self.assertEqual(round(nov["extra"]), 115379)  # the 7 working days still to come in November
        self.assertEqual(round(dec["extra"]), 263724)  # December's 16 working days
        self.assertTrue(all(m["extra"] == 0 for m in plan["months"][:7]))  # months already over

    def test_the_months_add_up_to_the_projected_year(self):
        plan = project_months(BILLED, list(zip(WD, DONE)))
        whole = sum((m["actual"] + m["extra"] for m in plan["months"]), Decimal("0"))
        self.assertEqual(round(whole, 2), plan["projected"])

    def test_counts_are_whole_numbers(self):
        plan = project_months([24, 19, 6, 31, 29, 27, 26, 15, 0, 0, 0, 0], list(zip(WD, DONE)), money=False)
        self.assertEqual((plan["so_far"], plan["projected"]), (177, 281))  # 177 / 145 x 230 = 280.8

    def test_a_month_without_working_days_counts_nothing(self):
        wd = [20] * 8 + [0] * 4
        plan = project_months(BILLED, list(zip(wd, DONE[:7] + [13, 0, 0, 0, 0])))
        self.assertTrue(all(m["extra"] == 0 for m in plan["months"][8:]))

    def test_nothing_before_a_working_day_is_completed(self):
        self.assertIsNone(project_months(BILLED, [(20, 0)] * 12))
        self.assertIsNone(project_total(100, 0, 230))
        self.assertEqual(project_total(100, 10, 230), Decimal("2300.00"))
        self.assertEqual(project_total(7, 10, 230, money=False), 161)


class WorkingDaysTests(UiPageBase):
    def test_month_working_days_and_the_year_total(self):
        for month in FY_MONTH_ORDER:
            save_adjustment(self.profile, {"financial_year": "2026-27", "month": month, "working_days": WD[FY_MONTH_ORDER.index(month)]})
        today = datetime.date(2026, 11, 19)
        self.assertEqual(month_working_days(self.profile, "2026-27", today), list(zip(WD, DONE)))
        days = working_days_completed(self.profile, today)
        self.assertEqual((days["year"], days["year_total"]), (145, 230))


def bill_today(profile):
    """A memo dated today, so the current financial year has something billed (and appearances) whatever the date."""
    matter = Matter.objects.filter(profile=profile).order_by("pk").first()
    make_memo(profile, matter, datetime.date.today().isoformat(), apps=3, fee=1000, misc=5000)


class DashboardTests(UiPageBase):
    def _enter(self, fy, per_month=20):
        for month in FY_MONTH_ORDER:
            save_adjustment(self.profile, {"financial_year": fy, "month": month, "working_days": per_month})

    def test_the_this_year_boxes_are_projected(self):
        self._enter("2026-27")
        today = datetime.date(2026, 11, 19)
        days = working_days_completed(self.profile, today)  # 7 full months + 20 x 19 / 30 = 13: 153 of 240
        self.assertEqual((days["year"], days["year_total"]), (153, 240))
        kpis = {"billed_this_year": "15300.00", "appearances_this_year": 30, "billed_this_month": "100.00"}
        projected = dashboard.projected_kpis(self.profile, kpis, today)
        self.assertEqual(projected, {"billed_this_year": Decimal("24000.00"), "appearances_this_year": 47})

    def test_no_projection_without_working_days(self):
        PeriodAdjustment.objects.filter(profile=self.profile).delete()
        self.assertEqual(dashboard.projected_kpis(self.profile, {"billed_this_year": "100.00"}, datetime.date(2026, 11, 19)), {})

    def test_the_billed_bars_carry_the_projected_part(self):
        fy = current_financial_year()
        self._enter(fy)
        bill_today(self.profile)
        panels = dashboard_panels.get_panels(self.profile)
        self.assertIsNotNone(panels["projected"])
        months = panels["months"]
        current = next(i for i, m in enumerate(months) if m["is_current"])
        self.assertTrue(all(m["extra"] == 0 for m in months[:current]))
        self.assertTrue(all(m["extra"] > 0 for m in months[current + 1:]))  # every future month has 20 working days
        self.assertEqual(round(sum((m["amount"] + m["extra"] for m in months), Decimal("0")), 0), round(panels["projected"], 0))
        self.assertTrue(all(0 <= m["height"] + m["extra_height"] <= 100 for m in months))
        text = self.html(self.page("fees_dashboard"))
        self.assertIn('class="bar-extra"', text)
        self.assertIn("Projected for " + fy, text)

    def test_the_dashboard_box_shows_the_projection(self):
        self._enter(current_financial_year())
        from fees.services import settings as settings_service
        settings_service.update_settings(self.profile, {"dashboard_kpis": "billed_this_year,billed_this_month"})
        text = self.html(self.page("fees_dashboard"))
        self.assertEqual(text.count('class="kpi-projected"'), 1)


class StandardChartTests(UiPageBase):
    def setUp(self):
        super().setUp()
        self.fy = current_financial_year()

    def _enter(self):
        for month in FY_MONTH_ORDER:
            save_adjustment(self.profile, {"financial_year": self.fy, "month": month, "working_days": 20})
        bill_today(self.profile)

    def test_by_month_draws_the_running_total(self):
        self._enter()
        text = self.assert_page(self.page("fees_statistics", query=f"?granularity=month&fy={self.fy}"), "month chart")
        self.assert_no_unlabelled_controls(text, "month chart")
        self.assertIn('class="projection-chart ch hv"', text)
        self.assertIn('class="pc-actual-line"', text)
        self.assertIn('class="pc-projected-line"', text)
        self.assertIn("Projected for " + self.fy, text)

    def test_by_financial_year_draws_the_stacked_column(self):
        self._enter()
        text = self.assert_page(self.page("fees_statistics", query="?granularity=financialYear&chart=num_appearances"), "year chart")
        self.assertIn('class="pc-projected-bar"', text)
        self.assertIn('<option value="num_appearances" selected>', text)

    def test_quarters_and_no_working_days_show_a_note(self):
        text = self.html(self.page("fees_statistics", query=f"?granularity=quarter&fy={self.fy}"))
        self.assertNotIn('class="projection-chart', text)
        self.assertIn("to see the projected totals", text)
        PeriodAdjustment.objects.filter(profile=self.profile).delete()
        text = self.html(self.page("fees_statistics", query=f"?granularity=month&fy={self.fy}"))
        self.assertIn("nothing can be projected", text)

    def test_the_explain_page_explains_the_projection(self):
        text = self.assert_page(self.page("fees_statistics_explain"), "explain")
        self.assertIn('id="projected"', text)


class StandardTableTests(UiPageBase):
    """Owner round 2026-11: no special look for figures entered by hand; Working Days rows; Explain and Edit Statistics buttons."""

    def test_entered_figures_look_like_the_others(self):
        save_adjustment(self.profile, {"financial_year": "2026-27", "month": 4, "working_days": 20, "override_billed": Decimal("5000")})
        text = self.html(self.page("fees_statistics", query="?granularity=month&fy=2026-27"))
        self.assertNotIn(" hand", text.split('data-table-id="statistics"')[1].split("</table>")[0])
        self.assertNotIn("Entered by hand in Settings", text)

    def test_working_days_rows_and_metric_choices(self):
        save_adjustment(self.profile, {"financial_year": "2026-27", "month": 4, "working_days": 20})
        text = self.html(self.page("fees_statistics", query="?granularity=month&fy=2026-27"))
        self.assertIn('<th scope="row">Working Days</th>', text)
        self.assertIn('<th scope="row">Working Days Completed</th>', text)
        self.assertIn('name="metric" value="working_days_entered"', text)
        self.assertIn('name="metric" value="days_completed"', text)

    def test_a_year_lists_the_entered_working_days_of_its_months(self):
        from fees.services.statistics import get_period_statistics
        for month in (4, 5):
            save_adjustment(self.profile, {"financial_year": "2026-27", "month": month, "working_days": 20})
        quarters = get_period_statistics(self.profile, "quarter", "2026-27", {}, datetime.date(2026, 4, 15))
        q1 = quarters["periods"][0]
        self.assertEqual(q1["working_days_entered"], 40)
        self.assertEqual(q1["days_completed"], 10)  # 20 x 15 / 30 in April, nothing yet of May

    def test_explain_and_edit_buttons(self):
        editor = self.html(self.page("fees_statistics", query="?granularity=month&fy=2026-27", user=self.editor))
        self.assertIn(">Explain Statistics</a>", editor)
        self.assertIn(reverse("fees_settings") + "?tab=years&amp;fy=2026-27#settings-years", editor)
        self.assertIn(">Edit Statistics</a>", editor)
        reader = self.html(self.page("fees_statistics", query="?granularity=month&fy=2026-27"))
        self.assertNotIn(">Edit Statistics</a>", reader)

    def test_the_projection_chart_has_hover_figures(self):
        fy = current_financial_year()
        for month in FY_MONTH_ORDER:
            save_adjustment(self.profile, {"financial_year": fy, "month": month, "working_days": 20})
        bill_today(self.profile)
        text = self.html(self.page("fees_statistics", query=f"?granularity=month&fy={fy}"))
        self.assertIn('class="projection-chart ch hv"', text)
        self.assertIn("data-hover=", text)
        self.assertIn("Actual, the month", text)
        self.assertIn("Projected, the month", text)
        self.assertIn('class="hv-tip"', text)
        self.assertIn("js/investments/chart-hover.js", text)
        years = self.html(self.page("fees_statistics", query="?granularity=financialYear"))
        self.assertIn('class="projection-chart ch hv"', years)


class EditStatisticsGridTests(UiPageBase):
    """One Save for every year and month of Settings > Years and Statistics > Edit Statistics."""

    def post_grid(self, data):
        self.login(self.editor)
        return self.client.post(reverse("fees_settings_statistics_grid"),
                                {"return_to": "settings", "grid": "1", "fy": "2026-27", **data})

    def test_one_save_changes_months_of_several_years(self):
        response = self.post_grid({"working_days__2026-27__6": "21", "working_days__2025-26__1": "19",
                                   "override_billed__2025-26__1": "7000", "extra_drafts__2026-27__6": "2"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("fees_settings") + "?tab=years&fy=2026-27#settings-years")
        june = PeriodAdjustment.objects.get(profile=self.profile, financial_year="2026-27", month=6)
        jan = PeriodAdjustment.objects.get(profile=self.profile, financial_year="2025-26", month=1)
        self.assertEqual((june.working_days, june.extra_drafts), (21, 2))
        self.assertEqual((jan.working_days, jan.ov_billed), (19, Decimal("7000")))
        self.assertIn("2 months changed", self.html(self.client.get(response["Location"])))

    def test_unchanged_and_empty_months_are_not_saved(self):
        before = PeriodAdjustment.objects.filter(profile=self.profile).count()
        april = PeriodAdjustment.objects.get(profile=self.profile, financial_year="2026-27", month=4)
        response = self.post_grid({"working_days__2026-27__7": "0", "working_days__2026-27__4": str(april.working_days),
                                   "extra_appearances__2026-27__4": str(april.extra_appearances),
                                   "extra_conferences__2026-27__4": str(april.extra_conferences),
                                   "extra_drafts__2026-27__4": str(april.extra_drafts),
                                   **{f"override_{k}__2026-27__4": "" if getattr(april, "ov_" + k) is None else str(getattr(april, "ov_" + k))
                                      for k in ("appearances", "conferences", "drafts", "billed", "received", "received_plus_tds")}})
        self.assertEqual(PeriodAdjustment.objects.filter(profile=self.profile).count(), before)
        self.assertIn("No changes to save.", self.html(self.client.get(response["Location"])))

    def test_a_mistake_anywhere_saves_nothing(self):
        response = self.post_grid({"working_days__2026-27__6": "21", "working_days__2026-27__7": "x"})
        self.assertFalse(PeriodAdjustment.objects.filter(profile=self.profile, financial_year="2026-27", month=6).exists())
        self.assertIn("July 2026-27: Working days must be a whole number.", self.html(self.client.get(response["Location"])))
