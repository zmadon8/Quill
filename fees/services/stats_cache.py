"""Database-backed statistics cache for the Fee Register (T3.6, R-NFR-3, R-NFR-10).

A single read-through cache over the ``fees.StatsCache`` table so the dashboard,
statistics and pivot read services can memoise an expensive aggregate instead of
recomputing it on every page view (design lines 51, 74, 261; requirements
R-NFR-3 "no process-local caches, only the database StatsCache" and R-NFR-10
"keyed by (profile, kind, params hash), valid while data_version matches;
results that include the current month also keyed by the local date; never
shared across profiles; at most 200 entries per profile").

The one entry point is :func:`get_or_compute`:

    payload = get_or_compute(profile, "dashboard", params, compute)

* ``kind`` is a short label such as ``"dashboard"`` or ``"statistics"`` and maps
  to the ``StatsCache.kind`` column.
* ``params`` is a dict of the query parameters; it is hashed deterministically
  (:func:`_params_hash`) to a 64-char hex digest that fills the ``params_hash``
  column, so two calls with the same parameters share one row.
* ``compute`` is a zero-argument callable returning a JSON-serialisable payload
  (a dict or list). It is called ONLY on a cache miss.
* ``today_sensitive`` marks a result whose value depends on the current date
  (anything that includes the current month). Such a row stores ``valid_on =
  today`` and is a miss on any later day; a date-independent row stores
  ``valid_on = None`` and stays valid until ``data_version`` advances.

Validity of a stored row (both must hold):

* ``data_version`` equals the profile's current ``FeesSettings.data_version``
  (every mutating service calls ``memos.touch`` which bumps it, logically
  invalidating every cached row); AND
* ``valid_on`` is ``None`` (date-independent) OR equals today.

On a hit the stored ``payload`` is returned WITHOUT calling ``compute``. On a
miss ``compute`` is called, the row for ``(profile, kind, params_hash)`` is
upserted with the fresh payload, the current ``data_version`` and the right
``valid_on``, the profile's cache is pruned, and the payload is returned.

Pruning on every write (design line 261, R-NFR-10): the profile's rows older
than the current ``data_version`` are deleted, then if the profile still has
more than :data:`MAX_ROWS_PER_PROFILE` rows the oldest by ``created_at`` are
evicted down to the cap. ``memos.touch`` additionally deletes ALL of the
profile's rows when ``data_version`` is bumped, so stale rows never accumulate
across mutating operations (design lines 67, 141).

"Today" is read through the module-level :func:`_today` helper (a thin wrapper
over ``datetime.date.today()``, matching ``financial_year`` and ``memo_fees``),
so a test can monkeypatch ``fees.services.stats_cache._today`` to simulate a
different day and exercise the date-sensitive miss. There is no module-level
mutable cache state (R-NFR-3): the only state is the database table.
"""
from __future__ import annotations

import datetime
import hashlib
import json

from django.db import transaction

from fees.models import FeesSettings, StatsCache

__all__ = [
    "MAX_ROWS_PER_PROFILE",
    "get_or_compute",
]

#: At most this many cached rows are kept per profile (R-NFR-10).
MAX_ROWS_PER_PROFILE = 200


def _today():
    """Today's local date (patchable in tests to simulate another day)."""
    return datetime.date.today()


def _params_hash(params):
    """A deterministic 64-char hex digest of ``params`` for the ``params_hash`` column.

    ``params`` is serialised with sorted keys and a ``str`` fallback for
    non-JSON values (dates, Decimals) so the same parameters always hash to the
    same digest regardless of dict ordering, then hashed with SHA-256 whose hex
    digest is exactly 64 characters, matching the column width.
    """
    encoded = json.dumps(params or {}, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _current_data_version(profile):
    """The profile's current ``FeesSettings.data_version`` (0 if no row yet)."""
    row = (
        FeesSettings.objects.filter(profile=profile)
        .values_list("data_version", flat=True)
        .first()
    )
    return row or 0


def _prune(profile, data_version):
    """Prunes the profile's cache after a write (design line 261, R-NFR-10).

    First deletes the profile's rows whose ``data_version`` is older than the
    current one (they can never be valid again), then, if the profile still has
    more than :data:`MAX_ROWS_PER_PROFILE` rows, evicts the oldest by
    ``created_at`` (then id) down to the cap.
    """
    StatsCache.objects.filter(profile=profile, data_version__lt=data_version).delete()

    surplus = (
        StatsCache.objects.filter(profile=profile).count() - MAX_ROWS_PER_PROFILE
    )
    if surplus > 0:
        stale_ids = list(
            StatsCache.objects.filter(profile=profile)
            .order_by("created_at", "id")
            .values_list("id", flat=True)[:surplus]
        )
        if stale_ids:
            StatsCache.objects.filter(pk__in=stale_ids).delete()


def get_or_compute(profile, kind, params, compute, today_sensitive=False):
    """Returns a cached payload for ``(profile, kind, params)`` or computes it.

    Looks for a VALID row: one whose ``data_version`` equals the profile's
    current settings ``data_version`` and whose ``valid_on`` is ``None`` or today
    (when ``today_sensitive`` the computed row is stamped with today's date, so
    it is only valid on the day it was computed). On a hit the stored ``payload``
    is returned and ``compute`` is NOT called.

    On a miss (no row, a stale ``data_version`` or a stale date) ``compute()`` is
    called to build a fresh JSON-serialisable payload, the row for ``(profile,
    kind, params_hash)`` is upserted with that payload, the current
    ``data_version`` and ``valid_on`` (today when ``today_sensitive`` else
    ``None``), the profile's cache is pruned to at most
    :data:`MAX_ROWS_PER_PROFILE` rows, and the payload is returned.

    The payload is never shared across profiles: every lookup and write is scoped
    to ``profile`` (R-NFR-10).
    """
    params_hash = _params_hash(params)
    data_version = _current_data_version(profile)
    today = _today()

    existing = StatsCache.objects.filter(
        profile=profile, kind=kind, params_hash=params_hash
    ).first()
    if (
        existing is not None
        and existing.data_version == data_version
        and (existing.valid_on is None or existing.valid_on == today)
    ):
        return existing.payload

    payload = compute()
    valid_on = today if today_sensitive else None

    with transaction.atomic():
        StatsCache.objects.update_or_create(
            profile=profile,
            kind=kind,
            params_hash=params_hash,
            defaults={
                "payload": payload,
                "data_version": data_version,
                "valid_on": valid_on,
            },
        )
        _prune(profile, data_version)

    return payload
