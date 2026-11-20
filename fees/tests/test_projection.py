"""Projected Totals (owner round 2026-11): the arithmetic, the Dashboard boxes and bars, and the Statistics > Standard charts.

Projected for the year = so far / working days completed so far x working days entered for the whole financial year; a month
with none entered counts 0; nothing is projected before a working day is completed.
"""
import datetime
from decimal import Decimal

from django.test import SimpleTestCase

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
        self.assertIn('class="projection-chart"', text)
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
        self.assertNotIn('class="projection-chart"', text)
        self.assertIn("to see the projected totals", text)
        PeriodAdjustment.objects.filter(profile=self.profile).delete()
        text = self.html(self.page("fees_statistics", query=f"?granularity=month&fy={self.fy}"))
        self.assertIn("nothing can be projected", text)

    def test_the_explain_page_explains_the_projection(self):
        text = self.assert_page(self.page("fees_statistics_explain"), "explain")
        self.assertIn('id="projected"', text)
