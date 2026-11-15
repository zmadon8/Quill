"""Fills in what older Lump Sum entries lack (data only: no model changes, so ``makemigrations --check`` sees nothing to do).

* ``AltValue.value_before`` of a sale date saved before it was stored: the amount sold plus the value the sale left.
* The value of a first purchase, which used to write no entry: one entry on the purchase date, noted From purchase.

The helper functions take plain data and repeat the rules of ``investments.services.sale_steps`` and ``trade_prices`` (a migration must not
import code that may change later). Everything is idempotent: an entry that already has a value is never replaced."""
import re
from decimal import ROUND_HALF_DOWN, ROUND_HALF_UP, Decimal

from django.db import migrations

PAISA = Decimal("0.01")
TAG_PURCHASE = "From purchase"
ROUNDING_NOTE = re.compile(r"Price rounding (\d+(?:\.\d+)?) added to charges")


def sold_amount(units, price, note):
    found = ROUNDING_NOTE.search(note or "")
    rounding = Decimal(found.group(1)) if found else Decimal(0)
    return (units * price - rounding).quantize(PAISA, rounding=ROUND_HALF_DOWN)


def derived_value_before(sells, after):
    """``[(units, price, note)]`` of a date's sales plus the value left after them."""
    return (sum((sold_amount(u, p, n) for u, p, n in sells), Decimal(0)) + after).quantize(PAISA, rounding=ROUND_HALF_UP)


def held_before(trades, day):
    """Units held at the start of ``day``; ``trades`` is ``[(date, side, units)]``."""
    return sum((u if side == "buy" else -u for d, side, u in trades if d < day), Decimal(0))


def backfill_values_before(trades, sells_by_day, entries):
    """``{date: value before}`` for the entries (``[(date, value_before, total_value)]``) of one holding that lack it and sit on a date with a
    sale, no purchase and units held before."""
    buy_days = {d for d, side, _u in trades if side == "buy"}
    out = {}
    for day, before, total in entries:
        if before is not None or day not in sells_by_day or day in buy_days or held_before(trades, day) <= 0:
            continue
        value = derived_value_before(sells_by_day[day], total)
        if value >= total:
            out[day] = value
    return out


def first_purchase_entry(trades, entry_dates):
    """``(date, amount)`` of the entry a first purchase should have, or None: the earliest purchase date, when the holding has no entry on or
    before it and no sale on that date."""
    buys = sorted(d for d, side, _u in trades if side == "buy")
    if not buys:
        return None
    first = buys[0]
    if any(d <= first for d in entry_dates) or any(d == first and side == "sell" for d, side, _u in trades):
        return None
    return first, sum((u for d, side, u in trades if d == first and side == "buy"), Decimal(0)).quantize(PAISA)


def backfill(apps, schema_editor):
    Instrument = apps.get_model("investments", "Instrument")
    Transaction = apps.get_model("investments", "Transaction")
    AltValue = apps.get_model("investments", "AltValue")
    for inst in Instrument.objects.filter(lump_sum=True):
        by_profile = {}
        for profile_id, day, side, units, price, note in Transaction.objects.filter(instrument=inst, status="final", units__isnull=False).order_by(
                "date", "pk").values_list("profile_id", "date", "side", "units", "price", "note"):
            by_profile.setdefault(profile_id, []).append((day, side, units, price, note))
        for profile_id, rows in by_profile.items():
            trades = [(d, side, u) for d, side, u, _p, _n in rows]
            sells_by_day = {}
            for d, side, u, p, n in rows:
                if side == "sell" and u > 0 and p is not None and p > 0:
                    sells_by_day.setdefault(d, []).append((u, p, n))
            alt = AltValue.objects.filter(profile_id=profile_id, instrument=inst)
            for day, value in backfill_values_before(trades, sells_by_day, [(a.date, a.value_before, a.total_value) for a in alt]).items():
                alt.filter(date=day).update(value_before=value)
            if not inst.interest_rate:
                found = first_purchase_entry(trades, list(alt.values_list("date", flat=True)))
                if found:
                    AltValue.objects.create(profile_id=profile_id, instrument=inst, date=found[0], total_value=found[1], note=TAG_PURCHASE)


class Migration(migrations.Migration):
    dependencies = [("investments", "0037_altvalue_value_before")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
