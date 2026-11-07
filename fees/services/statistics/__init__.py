"""Statistics package for the Fee Register (T3.8, design section 11).

Ports ``statisticsService.ts`` line by line into a profile-scoped Django
package. The module is split so each concern is small and testable:

* ``periods``: ``get_period_statistics`` plus the 12-month accumulators and the
  quarter / financial-year roll-ups (the period engine the dashboard depends on).
* ``year_end``: ``get_year_end_summary``.
* ``annual``: ``get_annual_breakdown`` (per firm / per matter).
* ``pivot``: ``get_pivot`` / ``get_per_week_pivot`` and the axis helpers.
* ``saved_views``: ``list_saved_views`` / ``save_saved_view`` / ``delete_saved_view``.
* ``adjustments``: ``list_adjustments`` / ``save_adjustment``.
* ``legacy``: ``get_statistics`` (the legacy FY / firm / partner / matter
  breakdown used by the comparison table and the property test).

Every function takes ``profile`` (``accounts.Profile``) first and is scoped to
it. Read services are pure; the only mutators are ``save_adjustment``,
``save_saved_view`` and ``delete_saved_view``, each of which runs in one
``transaction.atomic()`` and calls ``memos.touch(profile)`` exactly once.

Money always goes through ``fees.services.money.round2`` and no module here
computes a memo line fee (the single fee rule lives in
``fees.services.memo_fees``); per-period billed is the stored
``Memo.total_fees`` column summed with the ORM.

Naming: the TypeScript source says "partner" (the ``partners`` table); the
Django model is ``Group`` (the ``group`` field, ``group_id`` on ``Memo``). The
pivot ``partner`` dimension therefore reads the firm's group, exactly as the
sibling list services do.
"""
from fees.services.statistics.adjustments import list_adjustments, save_adjustment
from fees.services.statistics.annual import get_annual_breakdown
from fees.services.statistics.legacy import get_statistics
from fees.services.statistics.periods import get_period_statistics
from fees.services.statistics.pivot import get_per_week_pivot, get_pivot
from fees.services.statistics.saved_views import (
    delete_saved_view,
    list_saved_views,
    save_saved_view,
)
from fees.services.statistics.year_end import get_year_end_summary

__all__ = [
    "get_statistics",
    "get_period_statistics",
    "get_year_end_summary",
    "get_annual_breakdown",
    "get_pivot",
    "get_per_week_pivot",
    "list_saved_views",
    "save_saved_view",
    "delete_saved_view",
    "list_adjustments",
    "save_adjustment",
]
