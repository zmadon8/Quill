"""What a Lump Sum investment's records show (docs/DESIGN.md D192): money only, never units or a price per unit.

A Lump Sum is stored as units = money at price 1 (D182), so its units and price are bookkeeping. ``annotate`` gives each of its transactions
``lump_amount`` (the money paid or received) and ``value_after`` (the investment's value on that date, from the value entries the purchase or sale
saved), in one query for the whole list. Other transactions get ``lump_amount`` and ``value_after`` None.
"""
from decimal import Decimal

from investments.models import SIDE_BUY, STATUS_FINAL, AltValue
from investments.services import core


def amount_of(txn):
    """The money a Lump Sum transaction moved: what was paid in, or what came out of a sale."""
    if txn.units is None or txn.status != STATUS_FINAL:
        return txn.amount
    return core.buy_total(txn) if txn.side == SIDE_BUY else core.sell_total(txn)


def annotate(profile, txns):
    """Set ``lump_amount`` and ``value_after`` on each transaction of ``txns`` (a list; ``instrument`` must be loaded) and return it.

    ``value_after`` is the total value saved on the transaction's date by ``trade_prices.record_lump_purchase`` / ``record_lump_sale`` or typed by a
    person; None (shown as a dash) when the date has no value entry."""
    lumps = [t for t in txns if t.instrument.lump_sum]
    for t in txns:
        t.lump_amount = t.value_after = None
    if not lumps:
        return txns
    ids = {t.instrument_id for t in lumps}
    days = {t.date for t in lumps}
    found = {(i, d): v for i, d, v in AltValue.objects.filter(profile=profile, instrument_id__in=ids, date__in=days).values_list(
        "instrument_id", "date", "total_value")}
    for t in lumps:
        amount = amount_of(t)
        t.lump_amount = None if amount is None else Decimal(amount).quantize(Decimal("0.01"))
        t.value_after = found.get((t.instrument_id, t.date))
    return txns


def _rupees(value):
    from investments.money_auto import format_indian

    return f"\u20b9{format_indian(value)}"


def describe_history(profile, rows, names):
    """Replace the History description of each Lump Sum transaction row with money wording ("Sold ₹200 of X, leaving ₹50", "Bought ₹100 of X"),
    and drop its unit, price and charges changes. ``names`` is ``{instrument id: name}`` of the rows' investments. One query for every row."""
    from investments.models import Instrument

    mine = [r for r in rows if r.record_type == "transaction" and r.instrument_id_ref in names and r.snapshot.get("units") is not None]
    if not mine:
        return
    lump_ids = set(Instrument.objects.filter(pk__in={r.instrument_id_ref for r in mine}, lump_sum=True).values_list("pk", flat=True))
    mine = [r for r in mine if r.instrument_id_ref in lump_ids]
    if not mine:
        return
    days = {r.snapshot.get("date") for r in mine}
    found = {(i, d.isoformat()): v for i, d, v in AltValue.objects.filter(profile=profile, instrument_id__in=lump_ids, date__in=days).values_list(
        "instrument_id", "date", "total_value")}
    for r in mine:
        snap = r.snapshot
        amount = Decimal(snap["units"]) * Decimal(snap.get("price") or 1)
        name = names[r.instrument_id_ref]
        if snap.get("side") == "sell":
            left = found.get((r.instrument_id_ref, snap.get("date")))
            text = f"Sold {_rupees(amount)} of {name}" + (f", leaving {_rupees(left)}" if left is not None else "")
        else:
            text = f"Bought {_rupees(amount)} of {name}"
        r.description = text
        r.changes = [c for c in r.changes if c[0] not in ("units", "price", "charges")]
