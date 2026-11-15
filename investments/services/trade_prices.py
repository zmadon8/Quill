"""Manual Price History entries made from transactions (docs/DESIGN.md D181 and D182).

A buy or sell of an investment whose prices are typed by hand (an alternative investment, or one whose price source is Entered by hand or
Uploaded) is itself a price on that date. These entries are ordinary ``ManualPrice`` / ``AltValue`` rows, marked by a fixed note
(``prices.TAG_*``), so nothing that reads prices needs to know about them and no model changes. They only fill gaps: an entry a person
typed, or a price a file supplied, is never replaced.

Callers (``transactions.py``) run these inside their own transaction, after saving the transaction and before ``core.touch``.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from investments import lots
from investments.models import (
    HOLDABLE_KINDS, KIND_ALTERNATIVE, ORIGIN_PURCHASE, SIDE_BUY, SIDE_SELL, STATUS_FINAL, AltValue, ManualPrice, Price, Transaction,
)
from investments.services import core, fetch, prices

ZERO = Decimal(0)
_PRICE = Decimal("0.0001")
_PAISA = Decimal("0.01")
_ONE_DAY = timedelta(days=1)
_PER_UNIT_TAGS = (prices.TAG_PURCHASE, prices.TAG_SALE, prices.TAG_BOTH)


def eligible(instrument):
    """True when a trade price can stand as a Manual Price History entry: hand-priced, no interest rate (interest grows from the latest value,
    so a principal-based value would wipe the accrued interest) and not a Lump Sum (it has no per-unit price; see ``record_lump_*``)."""
    return (instrument.kind in HOLDABLE_KINDS and (instrument.kind == KIND_ALTERNATIVE or instrument.price_source in ("manual", "upload"))
            and not instrument.interest_rate and not instrument.lump_sum)


def _trades_by_date(profile, instrument, days):
    """``{date: [(side, units, price)]}`` of the final, priced purchases and sales on ``days``: for a shared investment those of every profile
    (one profile's edit then cannot delete another's entry), for a private one this profile's."""
    qs = Transaction.objects.filter(instrument=instrument, date__in=days, status=STATUS_FINAL, origin=ORIGIN_PURCHASE, is_opening=False,
                                    is_estimated=False, price__gt=0, units__gt=0)
    if instrument.profile_id is not None:
        qs = qs.filter(profile=profile)
    out = defaultdict(list)
    for day, side, units, price in qs.values_list("date", "side", "units", "price"):
        out[day].append((side, units, price))
    return out


def _average(trades):
    """``(price, tag)``: the units-weighted average price of the day's trades (so the order they were entered in does not matter)."""
    units = sum((u for _s, u, _p in trades), ZERO)
    price = (sum((u * p for _s, u, p in trades), ZERO) / units).quantize(_PRICE, rounding=ROUND_HALF_UP)
    sides = {s for s, _u, _p in trades}
    tag = prices.TAG_PURCHASE if sides == {SIDE_BUY} else prices.TAG_SALE if sides == {SIDE_SELL} else prices.TAG_BOTH
    return price, tag


def units_held(events, on):
    """Units held in every portfolio, broker and folio after the events up to and including ``on``."""
    return sum(lots.available_by_bucket(events, on).values(), ZERO)


def sync_trade_prices(profile, user, instrument, dates):
    """Make the derived Manual Price History entries of ``instrument`` on ``dates`` match its transactions as they are now.

    Call after the transaction is saved, edited (the old date and the new one) or deleted. A date with no qualifying trade loses its derived
    entry; a date with an entry that is not derived is left alone. The caller bumps the data version."""
    days = {d for d in dates if d}
    if not days or not eligible(instrument):
        return
    if instrument.kind == KIND_ALTERNATIVE:
        _sync_alt(profile, user, instrument, days)
    else:
        _sync_manual(user, instrument, days, _trades_by_date(profile, instrument, days))
        if instrument.profile_id is None:
            fetch.bump_version()  # a shared price is read by every profile, whose caches the caller's touch does not reach


def _sync_manual(user, instrument, days, trades):
    existing = {m.date: m for m in ManualPrice.objects.filter(instrument=instrument, date__in=days)}
    # An uploaded file is as good as a hand entry: a price it supplied for the date is kept.
    stored = set(Price.objects.filter(instrument=instrument, date__in=days).values_list("date", flat=True)) if instrument.price_source == "upload" else set()
    entered_by = user if getattr(user, "pk", None) else None
    for day in sorted(days):
        row = existing.get(day)
        if (row is not None and not prices.is_derived(row.note)) or day in stored:
            continue
        if day in trades:
            price, tag = _average(trades[day])
            if row is None:
                ManualPrice.objects.create(instrument=instrument, date=day, close=price, note=tag, entered_by=entered_by)
            elif row.close != price or row.note != tag:
                row.close, row.note, row.entered_by = price, tag, entered_by
                row.save()
        elif row is not None:
            row.delete()


def _sync_alt(profile, user, instrument, days):
    """An alternative investment's entry is the value of the whole holding: units held at the end of the date times the price. A trade
    changes the units held on every later date too, so every derived entry from the earliest changed date on is worked out again."""
    later = {d for d in AltValue.objects.filter(profile=profile, instrument=instrument, date__gte=min(days), note__in=_PER_UNIT_TAGS).values_list(
        "date", flat=True)}
    every = days | later
    existing = {a.date: a for a in AltValue.objects.filter(profile=profile, instrument=instrument, date__in=every)}
    trades = _trades_by_date(profile, instrument, every)
    events = core.events_for(profile, instrument.pk)
    for day in sorted(every):
        row = existing.get(day)
        if row is not None and not prices.is_derived(row.note):
            continue
        units = units_held(events, day) if day in trades else ZERO
        if units > 0:
            price, tag = _average(trades[day])
            total = (units * price).quantize(_PAISA, rounding=ROUND_HALF_UP)
            if row is None or row.total_value != total or row.nav != price or row.note != tag:
                prices.save_alt_value(profile, user, instrument, day, total, nav=price, note=tag)
        elif row is not None:
            prices.remove_alt_value(profile, user, row)


def drop_per_unit_values(profile, user, instrument):
    """Remove the values made from this investment's purchases and sales (used when it is given an interest rate)."""
    for row in AltValue.objects.filter(profile=profile, instrument=instrument, note__in=_PER_UNIT_TAGS).select_related("instrument"):
        prices.remove_alt_value(profile, user, row)


# ---------------------------------------------------------------- Lump Sum investments (D182)

def units_before(profile, instrument, day):
    """Units of ``instrument`` held at the start of ``day`` (everything up to the day before)."""
    return units_held(core.events_for(profile, instrument.pk), day - _ONE_DAY)


def record_lump_purchase(profile, user, instrument, day, amount, value_after, held_before):
    """The value after a Lump Sum purchase. A value typed on the form is saved as it is (it replaces whatever is on that date). Without one,
    the amount is added to the last value given, but only when something was held before, there is such a value, the investment has no
    interest rate (it grows from the latest value) and the date holds no value of a person's own. When nothing was held before (the first
    purchase, or one after everything was sold) the value is the amount itself, so the history starts at what was put in; an investment with
    an interest rate gets none (its value grows from the purchase, an entry would only restate the amount)."""
    if value_after is not None:
        old = AltValue.objects.filter(profile=profile, instrument=instrument, date=day).first()
        # A typed value replaces one a person entered, but keeps that entry's note so deleting the purchase later does not delete it.
        keep = old.note if old is not None and not prices.is_derived(old.note) else prices.TAG_PURCHASE
        prices.save_alt_value(profile, user, instrument, day, value_after, note=keep, value_before=_before_after_purchase(profile, instrument, day))
        return
    if instrument.interest_rate:
        return
    if held_before <= 0:
        _first_purchase_value(profile, user, instrument, day, amount)
        return
    last = AltValue.objects.filter(profile=profile, instrument=instrument, date__lte=day).order_by("-date").first()
    if last is None:
        return
    if last.date == day and last.note not in (prices.TAG_PURCHASE, prices.TAG_SALE, prices.TAG_OLD_REMAINING):
        return
    prices.save_alt_value(profile, user, instrument, day, (last.total_value + amount).quantize(_PAISA),
                          note=last.note if last.date == day else prices.TAG_PURCHASE, value_before=_before_after_purchase(profile, instrument, day))


def _first_purchase_value(profile, user, instrument, day, amount):
    """The value on the date of a purchase made when nothing was held before it: the amount, noted From purchase. A second purchase on that
    date adds to the entry this one made; a value of a person's own, or the entry of a sale on that date, is left alone."""
    row = AltValue.objects.filter(profile=profile, instrument=instrument, date=day).first()
    total = amount.quantize(_PAISA)
    if row is not None:
        if row.note != prices.TAG_PURCHASE:
            return
        total = (row.total_value + amount).quantize(_PAISA)
    prices.save_alt_value(profile, user, instrument, day, total, note=prices.TAG_PURCHASE, value_before=_before_after_purchase(profile, instrument, day))


def _before_after_purchase(profile, instrument, day):
    """What ``value_before`` becomes when a purchase changes the date's value. Same-day rule (D188): a date with both a purchase and a sale has
    no ``value_before`` (the entry is the day's closing value, a net of both, and no step is drawn), whichever was recorded first. The purchase
    changes the value the sale's ``value_before`` was measured against, so keeping it would show a wrong or negative "sold"."""
    return None if Transaction.objects.filter(profile=profile, instrument=instrument, date=day, side=SIDE_SELL, status=STATUS_FINAL).exists() \
        else prices.KEEP


def record_lump_sale(profile, user, instrument, txn, amount, remaining, held_before):
    """What a Lump Sum sale leaves: ``remaining`` as the value on the sale date, and the value just before the sale (amount sold plus
    remaining) in that same entry's ``value_before``, so charts show no false gain or loss. Nothing is saved on the day before.

    ``value_before`` is left empty when nothing was held before the date. A value a person typed on the sale date keeps its note (so deleting
    the sale does not delete it); the remaining amount replaces its value, as the sale form says. A second sale on the same date keeps the first
    sale's ``value_before``: it is the value before the day's first sale, and the later sale's amount plus remaining is not."""
    day = txn.date
    row = AltValue.objects.filter(profile=profile, instrument=instrument, date=day).first()
    note = row.note if row is not None and not prices.is_derived(row.note) else prices.TAG_SALE
    if held_before <= 0 or Transaction.objects.filter(profile=profile, instrument=instrument, date=day, side=SIDE_BUY, status=STATUS_FINAL).exists():
        before = None   # nothing held before the date, or a purchase on the same date (same-day rule, D188: no step on a day with both)
    elif row is not None and row.value_before is not None and Transaction.objects.filter(
            profile=profile, instrument=instrument, date=day, side=SIDE_SELL, status=STATUS_FINAL).exclude(pk=txn.pk).exists():
        before = row.value_before
    else:
        before = (amount + remaining).quantize(_PAISA)
    prices.save_alt_value(profile, user, instrument, day, remaining, note=note, value_before=before)


def forget_lump(profile, user, instrument, side, day):
    """After a Lump Sum transaction is deleted: remove the entries made for it, unless another of the same kind remains on that date.

    Same-day rule (D188): a date with a purchase and a sale holds one entry with no ``value_before``. Deleting either one leaves that entry's
    value as it is (it cannot be split again) and ``value_before`` stays empty, so no step or "sold" figure appears until the sale is recorded
    again. Deleting the sale removes a sale-noted entry (the day's value went with it); deleting the purchase removes a purchase-noted one."""
    final = Transaction.objects.filter(profile=profile, instrument=instrument, date=day, side=side, status=STATUS_FINAL)
    if final.exists():
        return
    notes = (prices.TAG_SALE, prices.TAG_OLD_REMAINING) if side == SIDE_SELL else (prices.TAG_PURCHASE,)
    for row in AltValue.objects.filter(profile=profile, instrument=instrument, date=day).select_related("instrument"):
        if row.note in notes:
            prices.remove_alt_value(profile, user, row)
        elif side == SIDE_SELL and row.value_before is not None:
            # a value a person typed stays; only the pre-sale value that belonged to the deleted sale goes
            prices.save_alt_value(profile, user, instrument, day, row.total_value, nav=row.nav, note=row.note, value_before=None)
    if side == SIDE_SELL:
        # entries older versions saved on the day before
        for row in AltValue.objects.filter(profile=profile, instrument=instrument, date=day - _ONE_DAY, note=prices.TAG_BEFORE_SALE).select_related("instrument"):
            prices.remove_alt_value(profile, user, row)
