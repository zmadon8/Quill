"""NSE's list of listed equities, refreshed at most once a week by the nightly job, for finding a share by name, symbol or ISIN."""
from datetime import timedelta

from django.db.models import Max, Q
from django.utils import timezone

from investments.adapters import nse_list
from investments.models import NseSecurity

BATCH = 500
REFRESH_DAYS = 7


def _store(rows):
    batch, n = [], 0
    for symbol, name, isin, series in rows:
        batch.append(NseSecurity(symbol=symbol[:40], name=name[:250], isin=isin[:20], series=series[:4]))
        if len(batch) >= BATCH:
            n += _flush(batch)
    return n + _flush(batch)


def _flush(batch):
    if not batch:
        return 0
    NseSecurity.objects.bulk_create(batch, update_conflicts=True, unique_fields=["symbol"], update_fields=["name", "isin", "series"])
    n = len(batch)
    batch.clear()
    return n


def due():
    last = NseSecurity.objects.aggregate(m=Max("updated_at"))["m"]
    return last is None or timezone.now() - last > timedelta(days=REFRESH_DAYS)


def refresh(force=False):
    if not force and not due():
        return 0
    return nse_list.fetch_list(_store)


def find(query, limit=25):
    """Securities whose name has every word of ``query``, or whose symbol or ISIN is it (symbol and ISIN need 2 characters, names 3)."""
    q = (query or "").strip()
    if len(q) < 2:
        return []
    cond = Q(symbol__iexact=q) | Q(isin__iexact=q)
    if len(q) >= 3:
        words = q.split()
        name_q = Q()
        for w in words:
            name_q &= Q(name__icontains=w)
        cond |= name_q | Q(symbol__istartswith=q)
    return list(NseSecurity.objects.filter(cond).order_by("name")[:limit])
