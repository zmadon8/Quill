"""Corporate actions in the units arithmetic (plan 8 and 16.2). Pure Python, no Django imports.

* ``events(actions)`` turns applied actions into lot events: a split multiplies every lot's units (cost and purchase dates unchanged);
  a bonus adds a lot at zero cost dated the ex-date, with its own holding period (CA to confirm the treatment); a demerger takes a
  share of the cost off every parent lot (the new company's lots are made from the transactions that record the shares received).
* ``basis_factor(actions, day)``: for a split-adjusted price series, the factor that expresses the units held on ``day`` on the
  series' basis, i.e. the product of every applied action after ``day``. A raw series needs no factor.
"""
from decimal import Decimal

from investments import lots

ONE = Decimal(1)


def events(actions):
    """``actions`` is ``[(id, kind, ex_date, value)]``: a split gives its factor (new/old), a bonus its ratio (new/old) and a demerger the
    fraction (0 to 1) of the parent's cost that moves to the new company."""
    out = []
    for pk, kind, ex_date, value in actions:
        if kind == "split":
            out.append(lots.Event(lots.SPLIT, ex_date, Decimal(value), None, ("ca", pk), order=pk))
        elif kind == "bonus":
            out.append(lots.Event(lots.BONUS, ex_date, Decimal(value), None, ("ca", pk), order=pk))
        elif kind == "demerger":
            out.append(lots.Event(lots.DEMERGER_OUT, ex_date, Decimal(value), None, ("ca", pk), order=pk))
    return out


def receipt_sources(parent_lots, units, share_of_cost, inherit_dates, received_on):
    """The pieces the units received on a demerger are made of (``lots.Event.sources``).

    ``parent_lots`` are the parent's lots held in the same portfolio and broker on the day before the ex-date (each with ``units``,
    ``cost``, ``bought_on``, ``paid_on`` and ``estimated``). ``units`` are the shares received, spread over those lots in proportion to
    the units each held. ``share_of_cost`` is the part of each lot's cost that moves to the new company's shares, already multiplied by
    this receipt's part of all the units received for the same parent lots (so several receipts never move the same cost twice).
    With ``inherit_dates`` each piece keeps the parent lot's purchase date; otherwise all start on ``received_on``.
    Returns ``[]`` when the parent held nothing there."""
    units = Decimal(units)
    held = sum((Decimal(l.units) for l in parent_lots), Decimal(0))
    if held <= 0:
        return []
    out = []
    for lot in parent_lots:
        if lot.units <= 0:
            continue
        piece_units = units * Decimal(lot.units) / held
        piece_cost = Decimal(lot.cost) * Decimal(share_of_cost)
        if inherit_dates:
            out.append((lot.bought_on, lot.paid_on, piece_units, piece_cost, bool(lot.estimated)))
        else:
            out.append((received_on, received_on, piece_units, piece_cost, False))
    return out


def basis_factor(actions, day, basis):
    """Units-on-basis multiplier for a valuation on ``day`` (plan 16.2)."""
    if basis != "split_adjusted":
        return ONE
    factor = ONE
    for _pk, kind, ex_date, value in actions:
        if ex_date > day and kind in ("split", "bonus"):
            factor *= Decimal(value) if kind == "split" else (ONE + Decimal(value))
    return factor
