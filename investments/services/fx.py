"""Exchange rates (plan 22): rupees for one unit of a foreign currency. A hand-entered rate wins over a fetched one; on weekends and
holidays the last available rate is used. Fetched from Yahoo as ``{CUR}INR=X`` (to be confirmed on Render, plan 15.3)."""
from decimal import Decimal

from django.db import transaction

from investments.errors import InvestmentsError
from investments.models import KIND_FOREIGN, FxRate, Instrument, ManualFxRate

ONE = Decimal(1)


def rate_on(currency, day):
    """``(date, rate, source)`` of the last rate on or before ``day`` (hand-entered wins a tie), or None. Rupees are always 1."""
    if not currency or currency == "INR":
        return day, ONE, "fixed"
    manual = ManualFxRate.objects.filter(currency=currency, date__lte=day).order_by("-date").values_list("date", "rate").first()
    fetched = FxRate.objects.filter(currency=currency, date__lte=day).order_by("-date").values_list("date", "rate").first()
    if manual and (not fetched or manual[0] >= fetched[0]):
        return manual[0], manual[1], "manual"
    if fetched:
        return fetched[0], fetched[1], "api"
    return None


def currencies_in_use():
    return sorted(set(Instrument.objects.filter(kind=KIND_FOREIGN).exclude(currency="INR").values_list("currency", flat=True)))


@transaction.atomic
def set_manual(currency, day, rate, note=""):
    rate = Decimal(str(rate))
    if rate <= 0:
        raise InvestmentsError("BAD_NUMBER", "An exchange rate must be more than zero.")
    obj, _ = ManualFxRate.objects.update_or_create(currency=currency.upper(), date=day, defaults={"rate": rate, "note": note[:200]})
    from investments.services import fetch

    fetch.bump_version()
    return obj


def store_fetched(currency, rows):
    """Store fetched ``[(date, rate)]``; never touches hand-entered rates (they are a separate table)."""
    added = 0
    existing = set(FxRate.objects.filter(currency=currency, date__in=[d for d, _ in rows]).values_list("date", flat=True))
    new = [FxRate(currency=currency, date=d, rate=r) for d, r in rows if d not in existing and r > 0]
    FxRate.objects.bulk_create(new)
    added += len(new)
    return added


def fetch_all(today=None, spacing=1.0):
    """Fetch the latest rates of every currency in use from Yahoo. Returns ``(updated, failures)``."""
    from investments.adapters import http, yahoo
    from investments.adapters.base import FetchError

    updated, failures = 0, []
    for n, cur in enumerate(currencies_in_use()):
        if n:
            http.sleep(spacing)
        last = FxRate.objects.filter(currency=cur).order_by("-date").values_list("date", flat=True).first()
        try:
            result = yahoo.fetch(f"{cur}INR=X", last, years=10, today=today)
            updated += 1 if store_fetched(cur, result.rows) else 0
        except FetchError as exc:
            failures.append({"id": 0, "name": f"{cur} to INR", "error": str(exc)})
    return updated, failures


def sampled(currency, days):
    """``[rate or None]`` at each of ``days`` from two queries (hand-entered rates win a tie)."""
    from bisect import bisect_right
    from datetime import timedelta

    if not days:
        return []
    start = days[0] - timedelta(days=30)
    merged = dict(FxRate.objects.filter(currency=currency, date__range=(start, days[-1])).values_list("date", "rate"))
    merged.update(ManualFxRate.objects.filter(currency=currency, date__range=(start, days[-1])).values_list("date", "rate"))
    before = rate_on(currency, start)
    rows = ([(before[0], before[1])] if before else []) + sorted(merged.items())
    keys = [d for d, _ in rows]
    out = []
    for d in days:
        i = bisect_right(keys, d)
        out.append(rows[i - 1][1] if i else None)
    return out
