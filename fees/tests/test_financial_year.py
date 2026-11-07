"""Financial-year tests for the Fee Register (T2.1, requirements R-FY-1, brief 5.1).

Ports the ``deriveFinancialYear`` cases from ``memoNumberService.test.ts`` and the
``recentFinancialYears`` behaviour from ``financialYear.ts``, plus the R-FY-1
examples, the quarter mapping and string-sort correctness. Pure functions, so a
``SimpleTestCase`` (no database) is used.
"""
import datetime

from django.test import SimpleTestCase

from fees.services.financial_year import (
    current_financial_year,
    derive_financial_year,
    quarter_of_month,
    recent_financial_years,
)


class DeriveFinancialYearTests(SimpleTestCase):
    def test_april_is_start_of_fy(self):
        self.assertEqual(derive_financial_year("2027-04-01"), "2027-28")

    def test_mid_year_july(self):
        self.assertEqual(derive_financial_year("2026-07-15"), "2026-27")

    def test_december(self):
        self.assertEqual(derive_financial_year("2026-12-31"), "2026-27")

    def test_january_maps_to_prior_year_fy(self):
        self.assertEqual(derive_financial_year("2027-01-01"), "2026-27")

    def test_february(self):
        self.assertEqual(derive_financial_year("2027-02-01"), "2026-27")

    def test_last_day_of_fy(self):
        self.assertEqual(derive_financial_year("2027-03-31"), "2026-27")

    def test_next_calendar_year_april(self):
        self.assertEqual(derive_financial_year("2028-04-01"), "2028-29")

    def test_decade_boundary(self):
        self.assertEqual(derive_financial_year("2029-04-15"), "2029-30")

    def test_century_boundary(self):
        self.assertEqual(derive_financial_year("1999-04-01"), "1999-00")

    def test_r_fy_1_examples(self):
        self.assertEqual(derive_financial_year("2026-07-15"), "2026-27")
        self.assertEqual(derive_financial_year("2027-02-01"), "2026-27")
        self.assertEqual(derive_financial_year("2027-04-01"), "2027-28")
        self.assertEqual(derive_financial_year("2099-04-01"), "2099-00")

    def test_accepts_date_objects(self):
        self.assertEqual(derive_financial_year(datetime.date(2026, 7, 15)), "2026-27")
        self.assertEqual(derive_financial_year(datetime.datetime(2027, 2, 1, 10, 0)), "2026-27")

    def test_labels_sort_as_strings(self):
        labels = [derive_financial_year(f"{y}-07-01") for y in (2024, 2026, 2025, 2030, 2027)]
        self.assertEqual(sorted(labels), ["2024-25", "2025-26", "2026-27", "2027-28", "2030-31"])


class CurrentFinancialYearTests(SimpleTestCase):
    def test_injected_now(self):
        self.assertEqual(current_financial_year(datetime.date(2027, 7, 1)), "2027-28")
        self.assertEqual(current_financial_year(datetime.date(2027, 2, 1)), "2026-27")

    def test_default_now_returns_a_label(self):
        label = current_financial_year()
        self.assertRegex(label, r"^\d{4}-\d{2}$")


class RecentFinancialYearsTests(SimpleTestCase):
    def test_descending_newest_first(self):
        years = recent_financial_years(8, now=datetime.date(2027, 7, 1))
        self.assertEqual(years[0], "2027-28")
        self.assertEqual(
            years,
            [
                "2027-28",
                "2026-27",
                "2025-26",
                "2024-25",
                "2023-24",
                "2022-23",
                "2021-22",
                "2020-21",
            ],
        )

    def test_min_financial_year_trims_older(self):
        years = recent_financial_years(8, "2026-27", now=datetime.date(2027, 7, 1))
        self.assertEqual(years, ["2027-28", "2026-27"])

    def test_count_controls_length(self):
        self.assertEqual(len(recent_financial_years(3, now=datetime.date(2027, 7, 1))), 3)


class QuarterOfMonthTests(SimpleTestCase):
    def test_quarter_mapping(self):
        for month in (4, 5, 6):
            self.assertEqual(quarter_of_month(month), 1)
        for month in (7, 8, 9):
            self.assertEqual(quarter_of_month(month), 2)
        for month in (10, 11, 12):
            self.assertEqual(quarter_of_month(month), 3)
        for month in (1, 2, 3):
            self.assertEqual(quarter_of_month(month), 4)

    def test_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            quarter_of_month(0)
        with self.assertRaises(ValueError):
            quarter_of_month(13)
