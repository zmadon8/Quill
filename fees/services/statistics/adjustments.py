"""Period-adjustment CRUD for the Fee Register statistics (T3.8).

Ports the ``listAdjustments`` / ``saveAdjustment`` pair from
``statisticsService.ts``. A ``PeriodAdjustment`` row carries, per financial-year
month, the manually entered working days, the extra appearance / conference /
draft counts added to the computed figures, and the optional ``ov_*`` overrides
that REPLACE a computed figure when not null.

``list_adjustments`` is a pure read ordered by month. ``save_adjustment`` is a
mutator: it UPSERTS the ``(profile, financial_year, month)`` row inside one
``transaction.atomic()`` and calls ``memos.touch(profile)`` exactly once (it
changes what the statistics show). A null override is stored as NULL, clearing
any prior override so the figure reverts to the computed value (matching the TS
``?? null`` and the "blank override goes back to computed" behaviour).

DTO keys are snake_case; the ``override_*`` keys map to the model's ``ov_*``
columns.
"""
from __future__ import annotations

from django.db import transaction

from fees.models import PeriodAdjustment
from fees.services.memos import touch

__all__ = ["list_adjustments", "save_adjustment"]

#: DTO key -> model field for the override columns.
_OVERRIDE_FIELDS = {
    "override_appearances": "ov_appearances",
    "override_conferences": "ov_conferences",
    "override_drafts": "ov_drafts",
    "override_billed": "ov_billed",
    "override_received": "ov_received",
    "override_received_plus_tds": "ov_received_plus_tds",
}


def _to_dto(row):
    """Builds the snake_case DTO dict for one ``PeriodAdjustment`` row."""
    return {
        "financial_year": row.financial_year,
        "month": row.month,
        "working_days": row.working_days,
        "extra_appearances": row.extra_appearances,
        "extra_conferences": row.extra_conferences,
        "extra_drafts": row.extra_drafts,
        "override_appearances": row.ov_appearances,
        "override_conferences": row.ov_conferences,
        "override_drafts": row.ov_drafts,
        "override_billed": row.ov_billed,
        "override_received": row.ov_received,
        "override_received_plus_tds": row.ov_received_plus_tds,
    }


def list_adjustments(profile, financial_year):
    """Lists one FY's adjustments as DTO dicts, ordered by month (pure read).

    Returns an empty list when the FY has no adjustment rows. One query; does NOT
    bump ``data_version``.
    """
    rows = PeriodAdjustment.objects.filter(
        profile=profile, financial_year=financial_year
    ).order_by("month")
    return [_to_dto(row) for row in rows]


def save_adjustment(profile, adjustment):
    """Upserts a month's adjustment row (working days, extras, optional overrides).

    ``adjustment`` is a dict with ``financial_year`` and ``month`` plus any of the
    extra / override keys (snake_case). Missing extras default to 0; a missing or
    ``None`` override is stored as NULL (so a prior override is cleared). Runs in
    one ``transaction.atomic()`` and calls ``memos.touch(profile)`` once. Returns
    ``None``.
    """
    financial_year = adjustment["financial_year"]
    month = adjustment["month"]
    defaults = {
        "working_days": adjustment.get("working_days", 0) or 0,
        "extra_appearances": adjustment.get("extra_appearances", 0) or 0,
        "extra_conferences": adjustment.get("extra_conferences", 0) or 0,
        "extra_drafts": adjustment.get("extra_drafts", 0) or 0,
    }
    for dto_key, field in _OVERRIDE_FIELDS.items():
        # A missing key and an explicit None both mean "no override" (store NULL).
        defaults[field] = adjustment.get(dto_key, None)
    with transaction.atomic():
        PeriodAdjustment.objects.update_or_create(
            profile=profile,
            financial_year=financial_year,
            month=month,
            defaults=defaults,
        )
        touch(profile)
    return None
