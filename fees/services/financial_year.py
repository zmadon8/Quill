"""Financial-year helpers for the Fee Register (requirements R-FY-1, brief 5.1).

Pure Python: standard-library ``datetime`` only, no Django imports.

The financial year runs 1 April to 31 March. A label is ``YYYY-YY`` where the
first four digits are the start calendar year and the last two are the end
year's last two digits (``2099-04-01`` gives ``"2099-00"``). Labels sort
correctly as plain strings because the leading year is a fixed-width prefix.

Public functions:

* ``derive_financial_year(d)`` from a date or ISO ``YYYY-MM-DD`` string.
* ``current_financial_year(now=None)`` the FY containing ``now`` (today by default).
* ``recent_financial_years(count=8, min_financial_year=None, now=None)`` a
  descending list for FY dropdowns.
* ``quarter_of_month(month)`` maps a 1-12 month to Q1-Q4 (Q1 Apr-Jun, Q2
  Jul-Sep, Q3 Oct-Dec, Q4 Jan-Mar).
"""
from __future__ import annotations

import datetime

__all__ = [
    "derive_financial_year",
    "current_financial_year",
    "recent_financial_years",
    "quarter_of_month",
]


def _year_month(d) -> tuple[int, int]:
    """Returns ``(year, month)`` from a date/datetime or ISO ``YYYY-MM-DD`` string."""
    if isinstance(d, datetime.datetime):
        d = d.date()
    if isinstance(d, datetime.date):
        return d.year, d.month
    text = str(d)
    parts = text.split("-")
    return int(parts[0]), int(parts[1])


def _label(start_year: int) -> str:
    """Builds the ``YYYY-YY`` label for the FY starting in ``start_year``."""
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def derive_financial_year(d) -> str:
    """Derives the ``YYYY-YY`` financial year containing date ``d``.

    Month 4 to 12 gives ``Y-(Y+1)``; months 1 to 3 give ``(Y-1)-Y``.
    """
    year, month = _year_month(d)
    start_year = year if month >= 4 else year - 1
    return _label(start_year)


def current_financial_year(now=None) -> str:
    """Returns the financial year containing ``now`` (today in local time by default)."""
    if now is None:
        now = datetime.date.today()
    return derive_financial_year(now)


def recent_financial_years(count: int = 8, min_financial_year=None, now=None) -> list[str]:
    """A descending list of recent financial years, newest first.

    When ``min_financial_year`` is given, labels earlier than it are dropped so a
    dropdown never offers data before the configured Initial FY.
    """
    start_year = int(current_financial_year(now)[:4])
    years = [_label(start_year - i) for i in range(count)]
    if not min_financial_year:
        return years
    min_start = int(str(min_financial_year)[:4])
    return [y for y in years if int(y[:4]) >= min_start]


def quarter_of_month(month: int) -> int:
    """Maps a 1-12 calendar month to its financial-year quarter (1 to 4).

    Q1 Apr-Jun, Q2 Jul-Sep, Q3 Oct-Dec, Q4 Jan-Mar.
    """
    if not 1 <= month <= 12:
        raise ValueError(f"quarter_of_month: month must be 1-12, got {month}")
    if 4 <= month <= 6:
        return 1
    if 7 <= month <= 9:
        return 2
    if 10 <= month <= 12:
        return 3
    return 4
