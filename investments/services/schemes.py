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
    for code, name, isin, day, nav, *rest in rows:     # the adapter adds the category heading as a sixth item
        name = name[:250]
        _, plan, option = fund_names.parse(name)
        if len(rest) >= 3:                       # AMFI's own plan and option columns win over the ones read from the joined name
            plan, option = rest[1] or plan, rest[2] or option
        batch.append(AmfiScheme(code=code, name=name, isin=isin[:20], nav=nav, nav_date=day, plan=plan, option=option, category=rest[0] if rest else "",
                                updated_at=timezone.now()))
        if len(batch) >= BATCH:
            n += _flush(batch)
    n += _flush(batch)
    infer_regular_plans()
    return n


def _flush(batch):
    if not batch:
        return 0
    AmfiScheme.objects.bulk_create(batch, update_conflicts=True, unique_fields=["code"], update_fields=["name", "isin", "nav", "nav_date", "plan", "option", "category", "updated_at"])
    n = len(batch)
    batch.clear()
    return n


def infer_regular_plans():
    """Set plan Regular on schemes whose name does not say the plan but whose fund (same base name) also has a Direct plan: every
    open-ended scheme has both since 2013. No Direct sibling (ETFs, closed-ended, interval) leaves the plan blank. Returns the count."""
    rows = list(AmfiScheme.objects.values_list("pk", "name", "plan"))
    direct = {fund_names.base_key(name) for _, name, plan in rows if plan == fund_names.PLAN_DIRECT}
    ids = [pk for pk, name, plan in rows if not plan and fund_names.base_key(name) in direct]
    for i in range(0, len(ids), BATCH):
        AmfiScheme.objects.filter(pk__in=ids[i:i + BATCH]).update(plan=fund_names.PLAN_REGULAR)
    return len(ids)


def due():
    last = AmfiScheme.objects.aggregate(m=Max("updated_at"))["m"]
    return last is None or timezone.now() - last > timedelta(days=REFRESH_DAYS)


def refresh(force=False, **limits):
    if not force and not due():
        return 0
    return amfi.fetch_scheme_list(_store, **limits)


def find(query, limit=25):
    q = (query or "").strip()
    if len(q) < 3:
        return []
    words = q.split()
    qs = AmfiScheme.objects.all()
    for w in words:
        qs = qs.filter(Q(name__icontains=w) | Q(plan__icontains=w) | Q(option__icontains=w) | Q(code=w) | Q(isin__iexact=w))
    return list(qs.order_by("name")[:limit])
