"""Price lookups over hand-entered prices (``ManualPrice``), fetched or uploaded prices (``Price``) and pinned prices
(``PinnedPrice``). Nothing outside the adapters knows which vendor supplied a price (plan 15.7), and a hand-entered price always
wins over a fetched one for the same day.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Max, OuterRef, Subquery

from investments.errors import InvestmentsError, not_found
from investments.models import AltValue, Instrument, ManualPrice, PinnedPrice, Price  # noqa: F401
from investments.services import core, history


def _newest_by_instrument(model, ids, as_of):
    newest = (
        model.objects.filter(instrument_id=OuterRef("instrument_id"), date__lte=as_of).order_by("-date").values("date")[:1]
    )
    rows = (
        model.objects.filter(instrument_id__in=ids, date__lte=as_of)
        .annotate(newest=Subquery(newest)).filter(date=Subquery(newest))
        .values_list("instrument_id", "date", "close")
    )
    return {iid: (day, close) for iid, day, close in rows}


def latest_prices(instrument_ids, as_of):
    """``{instrument id: (date, price)}`` of the last price on or before ``as_of``: a hand-entered price wins over a fetched
    one for the same day, and the later day wins otherwise. Two SQL queries however many instruments, no rows loaded beyond one each."""
    ids = list(instrument_ids)
    if not ids:
        return {}
    manual = _newest_by_instrument(ManualPrice, ids, as_of)
    fetched = _newest_by_instrument(Price, ids, as_of)
    out = dict(fetched)
    for iid, (day, close) in manual.items():
        if iid not in out or day >= out[iid][0]:
            out[iid] = (day, close)
    # A pin for exactly this date wins (plan 17.2): a 31 March report gives the same numbers whether or not the daily prices still exist.
    for iid, trading, close in PinnedPrice.objects.filter(instrument_id__in=ids, asked_date=as_of).values_list("instrument_id", "trading_date", "close"):
        out[iid] = (trading, close)
    return out


def price_on(instrument, day):
    """``(trading date, close, source, approximate)`` for ``day`` or None. Order (plan 17.2): a pin for that exact date, then the
    stored prices (last close on or before the day; a hand-entered price wins a tie), then the nearest earlier pin (approximate)."""
    pin = PinnedPrice.objects.filter(instrument=instrument, asked_date=day).order_by("-pinned_at").first()
    if pin:
        return pin.trading_date, pin.close, pin.source, pin.approximate
    found = latest_prices([instrument.pk], day).get(instrument.pk)
    if found:
        manual = ManualPrice.objects.filter(instrument=instrument, date=found[0]).exists()
        return found[0], found[1], "manual" if manual else "api", False
    older = PinnedPrice.objects.filter(instrument=instrument, trading_date__lte=day).order_by("-trading_date").first()
    return (older.trading_date, older.close, older.source, True) if older else None


def series_from(instrument, start, limit=10):
    """``[(date, price)]`` from ``start`` onwards, oldest first, hand-entered prices winning (for the NAV suggestions)."""
    merged = {d: c for d, c in Price.objects.filter(instrument=instrument, date__gte=start).order_by("date").values_list("date", "close")[:limit]}
    merged.update(ManualPrice.objects.filter(instrument=instrument, date__gte=start).order_by("date").values_list("date", "close")[:limit])
    return sorted(merged.items())[:limit]


def series(instrument, start=None, end=None):
    manual = ManualPrice.objects.filter(instrument=instrument)
    fetched = Price.objects.filter(instrument=instrument)
    if start:
        manual, fetched = manual.filter(date__gte=start), fetched.filter(date__gte=start)
    if end:
        manual, fetched = manual.filter(date__lte=end), fetched.filter(date__lte=end)
    merged = dict(fetched.order_by("date").values_list("date", "close"))
    merged.update(manual.order_by("date").values_list("date", "close"))
    return sorted(merged.items())


def alt_values(profile, instrument_ids):
    """``{instrument id: [(date, total_value)]}`` for the profile's alternative investments, oldest first."""
    out = {}
    for iid, day, total in AltValue.objects.filter(profile=profile, instrument_id__in=list(instrument_ids)).order_by("date").values_list(
            "instrument_id", "date", "total_value"):
        out.setdefault(iid, []).append((day, total))
    return out


@transaction.atomic
def set_manual_price(profile, user, instrument, day, close, note=""):
    """Enter or correct a price by hand. Shared (every profile sees it), so an Editor of any profile holding the investment may do it."""
    if instrument.profile_id not in (None, profile.pk):
        raise not_found("investment")
    try:
        close = Decimal(str(close).replace(",", "").strip())
    except Exception:
        raise InvestmentsError("BAD_NUMBER", "Price is not a number.")
    if close <= 0:
        raise InvestmentsError("BAD_NUMBER", "A price must be more than zero.")
    obj, _ = ManualPrice.objects.update_or_create(
        instrument=instrument, date=day, defaults={"close": close, "note": (note or "")[:200], "entered_by": user if getattr(user, "pk", None) else None})
    core.touch(profile)
    return obj


@transaction.atomic
def delete_manual_price(profile, user, price_id):
    obj = ManualPrice.objects.select_related("instrument").filter(pk=price_id).first()
    if obj is None or obj.instrument.profile_id not in (None, profile.pk):
        raise not_found("price")
    obj.delete()
    core.touch(profile)


@transaction.atomic
def set_alt_value(profile, user, instrument, day, total_value, nav=None, note=""):
    """Add or correct a dated value of an alternative investment (logged in the permanent history)."""
    if instrument.profile_id != profile.pk:
        raise InvestmentsError("NOT_ALTERNATIVE", "Dated values can only be entered for your own alternative investments.")
    total = Decimal(str(total_value).replace(",", "").strip())
    if total < 0:
        raise InvestmentsError("BAD_NUMBER", "A value cannot be negative.")
    obj = AltValue.objects.filter(profile=profile, instrument=instrument, date=day).first()
    kind = "edit" if obj else "create"
    if obj is None:
        obj = AltValue(profile=profile, instrument=instrument, date=day)
    obj.total_value = total
    obj.nav = Decimal(str(nav)) if nav not in (None, "") else None
    obj.note = (note or "")[:200]
    obj.save()
    history.record(profile, user, obj, kind, summary=f"Value of {instrument.name} on {day}")
    core.touch(profile)
    return obj


@transaction.atomic
def delete_alt_value(profile, user, pk):
    obj = AltValue.objects.filter(pk=pk, profile=profile).first()
    if obj is None:
        raise not_found("value")
    history.record(profile, user, obj, "delete", summary=f"Deleted value of {obj.instrument.name}")
    obj.delete()
    core.touch(profile)


def last_price_date(instrument_ids):
    """``{instrument id: newest stored price date}`` over hand-entered and fetched prices."""
    ids = list(instrument_ids)
    out = dict(Price.objects.filter(instrument_id__in=ids).values_list("instrument_id").annotate(m=Max("date")).order_by())
    for iid, m in ManualPrice.objects.filter(instrument_id__in=ids).values_list("instrument_id").annotate(m=Max("date")).order_by():
        if iid not in out or m > out[iid]:
            out[iid] = m
    return out


def recent_closes(instrument_ids, as_of, days=90, points=30):
    """``{instrument id: [close, ...]}`` for the last ``days`` days up to ``as_of``, oldest first, thinned to at most ``points``
    values (a table sparkline). One query per price table for every investment at once; hand-entered prices win a tie."""
    from datetime import timedelta

    ids = [i for i in instrument_ids if i]
    if not ids:
        return {}
    since = as_of - timedelta(days=days)
    merged = {}
    for model in (Price, ManualPrice):
        rows = model.objects.filter(instrument_id__in=ids, date__range=(since, as_of)).values_list("instrument_id", "date", "close")
        for iid, day, close in rows.iterator(chunk_size=2000):
            merged.setdefault(iid, {})[day] = close
    out = {}
    for iid, by_day in merged.items():
        closes = [c for _d, c in sorted(by_day.items())]
        if len(closes) > points:
            step = (len(closes) - 1) / (points - 1)
            closes = [closes[round(k * step)] for k in range(points)]
        out[iid] = closes
    return out
