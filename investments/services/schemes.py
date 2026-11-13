"""AMFI's list of schemes, refreshed at most once a week by the nightly job, for picking the exact fund plan by name (plan 6)."""
from datetime import timedelta

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from investments.adapters import amfi
from investments.services import fund_names
from investments.models import AmfiScheme

BATCH = 500
REFRESH_DAYS = 7


def _store(rows):
    """All or nothing: a format error raised at the end of the stream (a changed layout) rolls back every batch written so far."""
    with transaction.atomic():
        return _store_rows(rows)


def _store_rows(rows):
    batch, n = [], 0
    for code, name, isin, day, nav in rows:
        name = name[:250]
        _, plan, option = fund_names.parse(name)
        batch.append(AmfiScheme(code=code, name=name, isin=isin[:20], nav=nav, nav_date=day, plan=plan, option=option))
        if len(batch) >= BATCH:
            n += _flush(batch)
    return n + _flush(batch)


def _flush(batch):
    if not batch:
        return 0
    AmfiScheme.objects.bulk_create(batch, update_conflicts=True, unique_fields=["code"], update_fields=["name", "isin", "nav", "nav_date", "plan", "option"])
    n = len(batch)
    batch.clear()
    return n


def due():
    last = AmfiScheme.objects.aggregate(m=Max("updated_at"))["m"]
    return last is None or timezone.now() - last > timedelta(days=REFRESH_DAYS)


def refresh(force=False):
    if not force and not due():
        return 0
    return amfi.fetch_scheme_list(_store)


def find(query, limit=25):
    q = (query or "").strip()
    if len(q) < 3:
        return []
    words = q.split()
    qs = AmfiScheme.objects.all()
    for w in words:
        qs = qs.filter(Q(name__icontains=w) | Q(plan__icontains=w) | Q(option__icontains=w) | Q(code=w) | Q(isin__iexact=w))
    return list(qs.order_by("name")[:limit])
