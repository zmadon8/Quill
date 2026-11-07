"""The financial years offered in the year drop-downs (owner round: a drop-down, not a place to type).

Two pure reads, each one query. ``financial_year_options`` is for the filters on Memos, Drafts, Feebook and
Statistics: the years the profile has memos in, plus the current year, newest first, never earlier than the
area's start year, plus the year already chosen so a saved link still shows its own value.
``start_year_options`` is for the Settings start-year boxes: every year from the earliest year with data (or
ten years back when there is no data) to the current year, plus the values now saved.
"""
from __future__ import annotations

import re

from fees.models import Memo
from fees.services.financial_year import current_financial_year

__all__ = ["financial_year_options", "start_year_options", "is_financial_year_label"]

_FY_RE = re.compile(r"^(\d{4})-(\d{2})$")

#: How far back the Settings start-year boxes reach when the profile has no memos yet.
YEARS_BACK = 10


def is_financial_year_label(value):
    """Whether ``value`` is a ``YYYY-YY`` label whose second part follows the first."""
    match = _FY_RE.match(str(value or ""))
    return bool(match) and (int(match.group(1)) + 1) % 100 == int(match.group(2))


def _label(start_year):
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def _data_years(profile):
    """The financial years with at least one memo in ``profile``, as start years."""
    labels = Memo.objects.filter(profile=profile).order_by().values_list("financial_year", flat=True).distinct()
    return {int(label[:4]) for label in labels if is_financial_year_label(label)}


def financial_year_options(profile, start_year=None, selected=None, now=None, only_years=None):
    """The ``YYYY-YY`` labels for a filter drop-down, newest first.

    The years with data and the current year, dropped when earlier than ``start_year``; ``selected`` (a label or
    several) is always kept (when well-formed) so a bookmarked link does not lose its choice.

    ``only_years`` (labels, from ``filter_options``) replaces the years read from the profile's memos and drops the
    always-offered current year, so the drop-down lists only years that have rows under the other filters.
    """
    if only_years is None:
        years = _data_years(profile)
        years.add(int(current_financial_year(now)[:4]))
    else:
        years = {int(label[:4]) for label in only_years if is_financial_year_label(label)}
    if is_financial_year_label(start_year):
        floor = int(start_year[:4])
        years = {y for y in years if y >= floor}
    for value in [selected] if isinstance(selected, str) else (selected or ()):
        if is_financial_year_label(value):
            years.add(int(value[:4]))
    return [_label(y) for y in sorted(years, reverse=True)]


def start_year_options(profile, selected=(), now=None):
    """The labels for the Settings start-year drop-downs, newest first.

    Every year from the earliest year with data (ten years back when there is none) to the current year;
    the values in ``selected`` are added when they fall outside that range.
    """
    current = int(current_financial_year(now)[:4])
    data = _data_years(profile)
    years = set(range(min(data) if data else current - YEARS_BACK, current + 1))
    for value in selected:
        if is_financial_year_label(value):
            years.add(int(value[:4]))
    return [_label(y) for y in sorted(years, reverse=True)]
