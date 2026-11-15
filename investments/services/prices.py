"""Price lookups over hand-entered prices (``ManualPrice``), fetched or uploaded prices (``Price``) and pinned prices
(``PinnedPrice``). Nothing outside the adapters knows which vendor supplied a price (plan 15.7), and a hand-entered price always
wins over a fetched one for the same day.
"""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import OuterRef, Subquery

from investments.errors import InvestmentsError, not_found
from investments.models import SIDE_BUY, SIDE_SELL, STATUS_FINAL, AltValue, Instrument, ManualPrice, PinnedPrice, Price, Transaction  # noqa: F401
from investments.services import core, history


def _newest_by_instrument(model, ids, as_of):
    """``{instrument id: (date, close)}`` of each instrument's newest row on or before ``as_of``, in one query.

    The query starts from the instruments and asks the (instrument, date) index for one row each, so it costs one index probe per
    instrument. (Filtering the price rows themselves with a correlated "newest date" subquery made the database test every stored price
    row up to ``as_of`` -- hundreds of thousands for ten years of daily prices -- once per call.)"""
    newest = model.objects.filter(instrument_id=OuterRef("pk"), date__lte=as_of).order_by("-date")
    rows = (
        Instrument.objects.filter(pk__in=ids)
        .annotate(newest_date=Subquery(newest.values("date")[:1]), newest_close=Subquery(newest.values("close")[:1]))
        .filter(newest_date__isnull=False)
        .values_list("pk", "newest_date", "newest_close")
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
    before = {}
    for iid, day, total, value_before in AltValue.objects.filter(profile=profile, instrument_id__in=list(instrument_ids)).order_by("date").values_list(
            "instrument_id", "date", "total_value", "value_before"):
        out.setdefault(iid, []).append((day, total))
        if value_before is not None:
            before.setdefault(iid, {})[day - timedelta(days=1)] = value_before
    # A sale-date entry also holds the value just before that sale. It counts as the value on the day before, unless that day has an entry.
    for iid, extra in before.items():
        rows = out[iid]
        have = {d for d, _ in rows}
        rows.extend((d, v) for d, v in extra.items() if d not in have)
        rows.sort(key=lambda r: r[0])
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


# Notes that mark a Manual Price History entry as made automatically from a transaction (docs/DESIGN.md D181 and D182). They are stored in
# the entry's note, so no model change is needed. A hand edit stores the person's own note, which stops the entry being derived.
TAG_PURCHASE = "From purchase"
TAG_SALE = "From sale"
TAG_BOTH = "From purchase and sale"
TAG_BEFORE_SALE = "Before sale"
TAG_OLD_REMAINING = "Remaining after a sale"   # the note older Lump Sum sales were saved with; still recognised as derived
DERIVED_NOTES = frozenset((TAG_PURCHASE, TAG_SALE, TAG_BOTH, TAG_BEFORE_SALE, TAG_OLD_REMAINING))


def is_derived(note):
    """True when ``note`` is one of the fixed tags of an entry made from a transaction (anything else is a hand entry)."""
    return (note or "").strip() in DERIVED_NOTES


KEEP = object()   # "leave value_before as it is" for save_alt_value


def save_alt_value(profile, user, instrument, day, total_value, nav=None, note="", value_before=KEEP):
    """Write one value of an alternative investment and log it, without bumping the profile's data version (the caller does that once)."""
    if instrument.profile_id != profile.pk:
        raise InvestmentsError("NOT_ALTERNATIVE", "Manual Price History values can only be entered for your own alternative investments.")
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
    if value_before is not KEEP:
        obj.value_before = Decimal(str(value_before)) if value_before is not None else None
    obj.save()
    history.record(profile, user, obj, kind, summary=f"Value of {instrument.name} on {day}" + (f" ({obj.note.lower()})" if is_derived(obj.note) else ""))
    return obj


@transaction.atomic
def set_alt_value(profile, user, instrument, day, total_value, nav=None, note=""):
    """Add or correct a hand-entered value of an alternative investment (logged in the permanent history)."""
    total = Decimal(str(total_value).replace(",", "").strip())
    old = AltValue.objects.filter(profile=profile, instrument=instrument, date=day).first()
    # A hand correction keeps the stored value before a sale only while it still makes a sensible sale (D188): it is at least the new value and
    # a sale and no purchase is recorded on that date. Otherwise it is cleared, so "sold" is never negative or made up.
    keep = old is not None and old.value_before is not None and old.value_before >= total and sale_only_day(profile, instrument, day)
    obj = save_alt_value(profile, user, instrument, day, total_value, nav, note, value_before=KEEP if keep else None)
    core.touch(profile)
    return obj


def sale_only_day(profile, instrument, day):
    """True when ``instrument`` has a final sale and no final purchase on ``day`` (the only kind of day that keeps a ``value_before``)."""
    final = Transaction.objects.filter(profile=profile, instrument=instrument, date=day, status=STATUS_FINAL)
    return final.filter(side=SIDE_SELL).exists() and not final.filter(side=SIDE_BUY).exists()


def remove_alt_value(profile, user, obj):
    """Delete one value and log it, without bumping the data version (the caller does that once)."""
    history.record(profile, user, obj, "delete", summary=f"Deleted value of {obj.instrument.name}")
    obj.delete()


@transaction.atomic
def delete_alt_value(profile, user, pk):
    obj = AltValue.objects.filter(pk=pk, profile=profile).first()
    if obj is None:
        raise not_found("value")
    remove_alt_value(profile, user, obj)
    core.touch(profile)


def last_price_date(instrument_ids):
    """``{instrument id: newest stored price date}`` over hand-entered and fetched prices.

    One index probe per instrument and table (the newest row by date), not a ``GROUP BY`` over every stored price: this runs on every page
    for the status line, and ten years of daily prices is hundreds of thousands of rows."""
    ids = list(instrument_ids)
    if not ids:
        return {}
    out = {}
    for model in (Price, ManualPrice):
        newest = model.objects.filter(instrument_id=OuterRef("pk")).order_by("-date").values("date")[:1]
        rows = Instrument.objects.filter(pk__in=ids).annotate(newest_date=Subquery(newest)).filter(newest_date__isnull=False)
        for iid, m in rows.values_list("pk", "newest_date"):
            if iid not in out or m > out[iid]:
                out[iid] = m
    return out


def recent_closes(instrument_ids, as_of, days=90, points=30):
    """``{instrument id: [close, ...]}`` for the last ``days`` days up to ``as_of``, oldest first, thinned to at most ``points``
    values (a table sparkline). One query per price table for every investment at once; hand-entered prices win a tie."""

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
