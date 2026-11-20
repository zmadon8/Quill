# Projected Totals (design mockups; built in fees/services/statistics/projection.py and fees/projection_charts.py)

Mockups of how the current financial year's projected totals would show beside the actual figures. `build.py` makes the HTML
from one worked example (today 19 Nov 2026, FY 2026-27, 230 working days entered for the year, 145 completed); the PNGs are
screenshots of that HTML.

Formula, for each total (Billed, Received, Received + TDS, Appearances, Conferences, Drafts, Memos):

    projected for the year = so far / working days completed so far x working days in the whole financial year

1. `1-cumulative-line`: running total, actual (solid) then projected (dashed) to 31 March.
2. `2-monthly-stacked`: one column a month; the current month is actual + the rest of the month stacked, future months projected only.
3. `3-years-stacked`: one column a financial year; the current year is actual + the projected rest of the year.
4. `4-boxes-and-table`: Dashboard boxes and the Standard table with the projected figures.
