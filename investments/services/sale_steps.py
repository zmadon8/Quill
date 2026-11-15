"""The value just before a sale of a hand-priced investment, for the sale-date step in its charts and the calculated "Before sale" line of its
Manual Price History (docs/DESIGN.md D188).

* A Lump Sum keeps it (``AltValue.value_before``, written when the sale is saved).
* A share, fund or alternative investment priced per unit has nothing stored: it is worked out here, per profile, as the units held before
  the sale times the sale price (units are the profile's own, while a hand-priced share's price rows are shared by every profile).

Nothing here changes a gain, a cash flow or a period valuation: those use the end-of-day value after the sale."""
from decimal import ROUND_HALF_UP, Decimal

from investments.models import SIDE_SELL, STATUS_FINAL, AltValue, Transaction
from investments.money_auto import format_indian
from investments.services import core, trade_prices

_PAISA = Decimal("0.01")
_PRICE = Decimal("0.0001")


def steps(profile, instrument, start=None, end=None):
    """``[{"date", "before", "after", "sold"}]`` (Decimals, oldest first) for each date with a sale of ``instrument`` in ``start``..``end``:
    the holding's value just before the day's sales, its value after them, and the amount sold. Empty for an investment that is not hand-priced
    or that has an interest rate (its value grows from the latest entry, so units times price is not its value)."""
    if instrument.lump_sum:
        qs = AltValue.objects.filter(profile=profile, instrument=instrument, value_before__isnull=False)
        if start:
            qs = qs.filter(date__gte=start)
        if end:
            qs = qs.filter(date__lte=end)
        return [{"date": day, "before": before, "after": after, "sold": before - after}
                for day, before, after in qs.order_by("date").values_list("date", "value_before", "total_value")]
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
    ``calc_before``: its worked-out value just before the sale. Rows of other days and of a Lump Sum (it stores its own) get None. Reads
    the transactions only when such a row is shown."""
    from investments.services import prices

    sale_rows = [r for r in rows if r.note in (prices.TAG_SALE, prices.TAG_BOTH)]
    for r in rows:
        r.calc_before = None
    if not sale_rows or instrument.lump_sum:
        return rows
    found = {s["date"]: s["before"] for s in steps(profile, instrument, min(r.date for r in sale_rows), max(r.date for r in sale_rows))}
    for r in sale_rows:
        r.calc_before = found.get(r.date)
    return rows
