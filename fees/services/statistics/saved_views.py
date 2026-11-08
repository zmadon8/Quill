"""Saved pivot views for the Fee Register statistics (T3.8).

Ports ``listSavedViews`` / ``saveSavedView`` / ``deleteSavedView`` from
``statisticsService.ts``. A ``SavedView`` stores a named pivot configuration
(measure, row / column dimension, optional firm filter, optional FY range).

``list_saved_views`` is a pure read ordered case-insensitively by name. The TS
stored ``null`` for an absent firm / from_fy / to_fy; the Django model uses a
nullable FK for the firm and blank ``''`` CharFields for the FY bounds, so the
DTO surfaces an empty-string FY bound as ``None`` and the firm as its id or
``None``.

``save_saved_view`` and ``delete_saved_view`` are mutators: each runs in one
``transaction.atomic()``, calls ``memos.touch(profile)`` once, and returns the
refreshed list. ``save_saved_view`` validates the name length (1 to 100) and
raises ``FeesError('UNKNOWN', ...)`` with the original message otherwise.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models.functions import Lower

from fees.errors import FeesError
from fees.models import SavedView
from fees.services.memos import touch

__all__ = ["list_saved_views", "save_saved_view", "delete_saved_view"]

#: Name length bounds (ported from saveSavedView).
MIN_NAME = 1
MAX_NAME = 100


def _fy_or_none(value):
    """An empty-string FY bound surfaces as ``None`` on the DTO (TS stored null)."""
    return value or None


def _to_dto(row):
    """Builds the DTO dict for one ``SavedView`` row."""
    return {
        "id": row.pk,
        "name": row.name,
        "measure": row.measure,
        "row_dim": row.row_dim,
        "col_dim": row.col_dim,
        "firm_id": row.firm_id,
        "from_fy": _fy_or_none(row.from_fy),
        "to_fy": _fy_or_none(row.to_fy),
    }


def list_saved_views(profile):
    """Lists the profile's saved views as DTO dicts, ordered by ``Lower(name)``.

    Pure read; one query; does NOT bump ``data_version``.
    """
    rows = SavedView.objects.filter(profile=profile).order_by(Lower("name"))
    return [_to_dto(row) for row in rows]


def save_saved_view(profile, view_input):
    """Creates a saved view then returns the refreshed list (mutator).

    ``view_input`` is a dict with ``name`` plus optional ``measure``, ``row_dim``,
    ``col_dim``, ``firm_id``, ``from_fy``, ``to_fy``. The name is trimmed and must
    be 1 to 100 characters (``FeesError('UNKNOWN', ...)`` otherwise). Absent FY
    bounds are stored as ``''`` (the model default); an absent firm as NULL. One
    transaction; ``memos.touch(profile)`` called once.
    """
    name = (view_input.get("name") or "").strip()
    if len(name) < MIN_NAME or len(name) > MAX_NAME:
        raise FeesError(
            "UNKNOWN", "View name must be between 1 and 100 characters"
        )
    with transaction.atomic():
        SavedView.objects.create(
            profile=profile,
            name=name,
            measure=view_input.get("measure") or "",
            row_dim=view_input.get("row_dim") or "",
            col_dim=view_input.get("col_dim") or "",
            firm_id=view_input.get("firm_id"),
            from_fy=view_input.get("from_fy") or "",
            to_fy=view_input.get("to_fy") or "",
        )
        touch(profile)
    return list_saved_views(profile)


def delete_saved_view(profile, view_id):
    """Deletes a saved view by id then returns the refreshed list (mutator).

    Deleting a missing id is a no-op (the filtered delete removes nothing). One
    transaction; ``memos.touch(profile)`` called once.
    """
    with transaction.atomic():
        SavedView.objects.filter(profile=profile, pk=view_id).delete()
        touch(profile)
    return list_saved_views(profile)
