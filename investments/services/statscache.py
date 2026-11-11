"""The statistics cache (plan 26.4), adapted from the Fee Register's: a result is keyed by profile, kind and a hash of its parameters
and is valid only while the profile's `data_version` and the global price version both still match (and the date, for results that
include today). At most 200 rows per profile; no process-local caches. Payloads are JSON: Decimals travel as text."""
import datetime
import hashlib
import json

from investments.models import InvestmentsStatsCache
from investments.services import core, fetch

MAX_ROWS_PER_PROFILE = 200


def _hash(params):
    return hashlib.sha256(json.dumps(params or {}, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def peek(profile, kind, params, today=None):
    """The cached payload for ``(profile, kind, params)`` only if it is still valid; never computes (the suite Home page)."""
    today = today or datetime.date.today()
    settings_row = core.get_settings(profile, create=False)
    data_version = getattr(settings_row, "data_version", 0) or 0
    row = InvestmentsStatsCache.objects.filter(profile=profile, kind=kind, params_hash=_hash(params)).first()
    if row and row.data_version == data_version and row.price_version == fetch.price_version() and (row.valid_on is None or row.valid_on == today):
        return row.payload
    return None


def get_or_compute(profile, kind, params, compute, today_sensitive=False, today=None):
    """The cached payload for ``(profile, kind, params)`` if valid, else ``compute()`` stored and returned."""
    today = today or datetime.date.today()
    data_version = core.get_settings(profile, create=False).data_version or 0
    price_version = fetch.price_version()
    key = _hash(params)
    row = InvestmentsStatsCache.objects.filter(profile=profile, kind=kind, params_hash=key).first()
    if row and row.data_version == data_version and row.price_version == price_version and (row.valid_on is None or row.valid_on == today):
        return row.payload
    payload = json.loads(json.dumps(compute(), default=str))
    InvestmentsStatsCache.objects.update_or_create(
        profile=profile, kind=kind, params_hash=key,
        defaults={"data_version": data_version, "price_version": price_version, "valid_on": today if today_sensitive else None, "payload": payload})
    _prune(profile, data_version, price_version)
    return payload


def _prune(profile, data_version, price_version):
    InvestmentsStatsCache.objects.filter(profile=profile).exclude(data_version=data_version, price_version=price_version).delete()
    surplus = InvestmentsStatsCache.objects.filter(profile=profile).count() - MAX_ROWS_PER_PROFILE
    if surplus > 0:
        ids = list(InvestmentsStatsCache.objects.filter(profile=profile).order_by("created_at", "id").values_list("pk", flat=True)[:surplus])
        InvestmentsStatsCache.objects.filter(pk__in=ids).delete()
