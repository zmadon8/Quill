"""Price lookups. Phase 1 knows manual prices only (``ManualPrice``); the price phase adds fetched ``Price`` rows behind the
same functions, so nothing outside this module needs to change (plan 15.7: nothing outside the adapters knows the vendor).
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Max, OuterRef, Subquery

from investments.errors import InvestmentsError, not_found
from investments.models import AltValue, ManualPrice
from investments.services import core, history


def latest_prices(instrument_ids, as_of):
    """``{instrument id: (date, price)}`` of the last price on or before ``as_of``. One SQL query, no price rows loaded beyond one per instrument."""
    ids = list(instrument_ids)
    if not ids:
        return {}
    newest = (
        ManualPrice.objects.filter(instrument_id=OuterRef("instrument_id"), date__lte=as_of)
        .order_by("-date").values("date")[:1]
    )
    rows = (
        ManualPrice.objects.filter(instrument_id__in=ids, date__lte=as_of)
        .annotate(newest=Subquery(newest)).filter(date=Subquery(newest))
        .values_list("instrument_id", "date", "close")
    )
    return {iid: (day, close) for iid, day, close in rows}


def series_from(instrument, start, limit=10):
    """``[(date, price)]`` from ``start`` onwards, oldest first (for the NAV suggestions on the completion screen)."""
    return list(ManualPrice.objects.filter(instrument=instrument, date__gte=start).order_by("date").values_list("date", "close")[:limit])


def series(instrument, start=None, end=None):
    qs = ManualPrice.objects.filter(instrument=instrument)
    if start:
        qs = qs.filter(date__gte=start)
    if end:
        qs = qs.filter(date__lte=end)
    return list(qs.order_by("date").values_list("date", "close"))


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
    return dict(ManualPrice.objects.filter(instrument_id__in=list(instrument_ids)).values_list("instrument_id").annotate(m=Max("date")).order_by())
