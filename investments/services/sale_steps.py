"""The value just before a sale of a hand-priced investment, for the sale-date step in its charts and the calculated "Before sale" line of its
Manual Price History (docs/DESIGN.md D188).

* A Lump Sum keeps it (``AltValue.value_before``, written when the sale is saved). A sale saved before that was stored has none, so it is worked
  out here from the sale's own transactions: the typed money amount sold plus the value the sale left (``derived_value_before``), and only for
  an entry noted From sale, never a hand-typed one. Migration 0038 stores that figure for older sales; this keeps the page right for any date
  the migration did not reach.
* A share, fund or alternative investment priced per unit has nothing stored: it is worked out here, per profile, as the units held before
  the sale times the sale price (units are the profile's own, while a hand-priced share's price rows are shared by every profile).

Nothing here changes a gain, a cash flow or a period valuation: those use the end-of-day value after the sale."""
import re
from datetime import timedelta
from decimal import ROUND_HALF_DOWN, ROUND_HALF_UP, Decimal

from django.db.models import Q

from investments.models import SIDE_BUY, SIDE_SELL, STATUS_FINAL, AltValue, Transaction
from investments.money_auto import format_indian
from investments.services import core, trade_prices

_PAISA = Decimal("0.01")
_PRICE = Decimal("0.0001")
_ONE_DAY = timedelta(days=1)
TAG_SALE = "From sale"   # the note of an entry made by a sale (prices.TAG_SALE)
_ROUNDING_NOTE = re.compile(r"Price rounding (\d+(?:\.\d+)?) added to charges")


def sold_amount(units, price, note):
    """The amount a Lump Sum sale transaction took out, as the person typed it: units times price, less the price rounding that
    ``add_lump_sum_transaction`` added to the price (it is written in the note), to the paisa."""
    found = _ROUNDING_NOTE.search(note or "")
    rounding = Decimal(found.group(1)) if found else Decimal(0)
    return (units * price - rounding).quantize(_PAISA, rounding=ROUND_HALF_DOWN)


def derived_value_before(sells, after):
    """A Lump Sum's value just before a day's sales: the amount they sold (``[(units, price, note)]``) plus ``after``, the value the entry of that
    date holds after them. With several sales on one date this is the value before the first one, taking the value the earlier sale left to be
    the later sale's amount plus what it left. When other places still hold the investment after a sell-all, the entry already includes them."""
    return (sum((sold_amount(u, p, n) for u, p, n in sells), Decimal(0)) + after).quantize(_PAISA, rounding=ROUND_HALF_UP)


def _lump_steps(profile, instrument, start, end):
    sells = Transaction.objects.filter(profile=profile, instrument=instrument, side=SIDE_SELL, status=STATUS_FINAL, units__gt=0, price__gt=0)
    if start:
        sells = sells.filter(date__gte=start)
    if end:
        sells = sells.filter(date__lte=end)
    by_day = {}
    for day, units, price, note in sells.order_by("date", "pk").values_list("date", "units", "price", "note"):
        by_day.setdefault(day, []).append((units, price, note))
    qs = AltValue.objects.filter(profile=profile, instrument=instrument)
    qs = qs.filter(Q(value_before__isnull=False) | Q(date__in=list(by_day)))
    if start:
        qs = qs.filter(date__gte=start)
    if end:
        qs = qs.filter(date__lte=end)
    rows = list(qs.order_by("date").values_list("date", "value_before", "total_value", "note"))
    # a figure is worked out only for an entry the sale itself made (noted From sale): an entry with another note was typed by hand, and a hand
    # value that cleared ``value_before`` (prices.set_alt_value) must not get its step back
    rows = [r for r in rows if r[1] is not None or (r[3] or "").strip() == TAG_SALE]
    missing = [day for day, before, _after, _note in rows if before is None]
    buys, events = set(), None
    if missing:
        buys = set(Transaction.objects.filter(profile=profile, instrument=instrument, side=SIDE_BUY, status=STATUS_FINAL, date__in=missing)
                   .values_list("date", flat=True))
        events = core.events_for(profile, instrument.pk)
    out = []
    for day, before, after, _note in rows:
        if before is None:
            # same-day rule (D188): no step on a date with a purchase; nothing held before the date: nothing was sold
            if day in buys or trade_prices.units_held(events, day - _ONE_DAY) <= 0:
                continue
            before = derived_value_before(by_day[day], after)
        elif before < after:
            continue
        out.append({"date": day, "before": before, "after": after, "sold": before - after})
    return out


def steps(profile, instrument, start=None, end=None):
    """``[{"date", "before", "after", "sold"}]`` (Decimals, oldest first) for each date with a sale of ``instrument`` in ``start``..``end``:
    the holding's value just before the day's sales, its value after them, and the amount sold. Empty for an investment that is not hand-priced
    or that has an interest rate (its value grows from the latest entry, so units times price is not its value)."""
    if instrument.lump_sum:
        return _lump_steps(profile, instrument, start, end)
    if not trade_prices.eligible(instrument):
        return []
    qs = Transaction.objects.filter(profile=profile, instrument=instrument, side=SIDE_SELL, status=STATUS_FINAL, units__gt=0, price__gt=0)
    if start:
        qs = qs.filter(date__gte=start)
    if end:
        qs = qs.filter(date__lte=end)
    by_day = {}
    for day, units, price in qs.order_by("date", "pk").values_list("date", "units", "price"):
        by_day.setdefault(day, []).append((units, price))
    if not by_day:
        return []
    events = core.events_for(profile, instrument.pk)
    out = []
    for day, sales in sorted(by_day.items()):
        sold_units = sum((u for u, _p in sales), Decimal(0))
        price = (sum((u * p for u, p in sales), Decimal(0)) / sold_units).quantize(_PRICE, rounding=ROUND_HALF_UP)
        left = trade_prices.units_held(events, day)
        out.append({"date": day, "before": ((left + sold_units) * price).quantize(_PAISA, rounding=ROUND_HALF_UP),
                    "after": (left * price).quantize(_PAISA, rounding=ROUND_HALF_UP),
                    "sold": (sold_units * price).quantize(_PAISA, rounding=ROUND_HALF_UP)})
    return out


def text(step):
    """The tooltip line of a step (plain text; the template escapes it)."""
    return (f"Before sale \u20b9{format_indian(step['before'])}, after sale \u20b9{format_indian(step['after'])}, "
            f"sold \u20b9{format_indian(step['sold'])}")


def insert_points(days, lines, found, before_on_first=True):
    """``(days, lines, notes)`` with each sale date in ``found`` (see ``steps``) given two points at that date: the one just before the sale
    first, then the one after it (the chart draws a vertical drop). ``lines`` is a list of value lists (the first line is the holding's value:
    its before point is the step's value before the sale when ``before_on_first``; otherwise, and for every other line, the point repeats the
    day's value). ``notes`` is ``[[iso day, tooltip text]]`` for the sale dates that were found among ``days``."""
    by_day = {s["date"]: s for s in found}
    out_days, out_lines, notes = [], [[] for _ in lines], []
    for i, day in enumerate(days):
        step = by_day.get(day)
        if step is not None:
            out_days.append(day)
            for k, line in enumerate(lines):
                out_lines[k].append(float(step["before"]) if k == 0 and before_on_first else line[i])
            notes.append([day.isoformat(), text(step)])
        out_days.append(day)
        for k, line in enumerate(lines):
            out_lines[k].append(line[i])
    return out_days, out_lines, notes


def add_calculated_before(profile, instrument, rows):
    """Marks each Manual Price History row that is a sale (``From sale`` or ``From purchase and sale``) of a per-unit investment with
    ``calc_before``: its worked-out value just before the sale. Rows of other days get None, and so does a Lump Sum's row that stores its own
    ``value_before``. Reads the transactions only when such a row is shown."""
    from investments.services import prices

    sale_rows = [r for r in rows if r.note in (prices.TAG_SALE, prices.TAG_BOTH)]
    for r in rows:
        r.calc_before = None
    if instrument.lump_sum:
        sale_rows = [r for r in sale_rows if r.value_before is None]
    if not sale_rows:
        return rows
    found = {s["date"]: s["before"] for s in steps(profile, instrument, min(r.date for r in sale_rows), max(r.date for r in sale_rows))}
    for r in sale_rows:
        r.calc_before = found.get(r.date)
    return rows
