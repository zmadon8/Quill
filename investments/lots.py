"""FIFO lots, selling limits and the whole-history re-check (plan sections 6 and 16.5).

Pure Python, no Django imports. Everything here works on plain ``Event`` objects, so it is easy to test and the services
(`investments/services/transactions.py`) can replay a profile's whole history after every change.

Rules implemented (plan section 6):

* A **bucket** is ``(portfolio, broker, folio)`` (``folio`` may be ``None``: units recorded with no folio form a group of
  their own). A sale draws only on the bucket it names, first bought first sold (FIFO) within that bucket, so it can never
  exceed the units owned in total, with the broker, in the folio, or with both.
* On the same date purchases (and transfers in) count before sales.
* A purchase counts from its **effective date**: the allotment date if one is recorded, else the transaction date
  (the date paid). That is when the units exist and when the holding period starts. The caller leaves out entries that have
  no units yet (awaiting allotment, pending SIP).
* Charges are added to a purchase's cost and deducted from a sale's proceeds, and a sale's charges are spread over the lots it
  consumes in proportion to the units taken from each.
* A **transfer** moves units from one bucket to another, taking the oldest lots first and keeping each lot's date and cost.
* ``cost_override`` on a purchase replaces its total cost (grandfathering; plan 3.2, proposed).
* A **demerger** moves part of the cost of the parent's lots to shares of a new company, for the calculations only: the parent's
  lots lose that share of their cost (``DEMERGER_OUT``), and the shares received (``DEMERGER_IN``) form lots whose cost and, if the
  person chose it, purchase dates come from the parent lots they were derived from. Every lot remembers how much of its cost came
  from such an adjustment (``Lot.adjustment``), so the cost of the original transactions can always be shown beside it.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

ZERO = Decimal(0)

BUY = "buy"
SELL = "sell"
TRANSFER = "transfer"
SPLIT = "split"        # every lot's units times ``units`` (the factor); cost and dates unchanged
BONUS = "bonus"        # a new lot in each bucket of held units times ``units`` (the bonus ratio), at zero cost, dated the ex-date
DEMERGER_OUT = "demerger_out"  # the parent: every lot's cost times (1 - ``units``) stays, ``units`` (a fraction, 0 to 1) moves to the new company
DEMERGER_IN = "demerger_in"    # the new company: units received; lots come from ``sources`` (the parent's lots), or one lot at nil cost

#: Order of kinds inside one date: a corporate action applies to what was held at the end of the day before, then purchases,
#: transfers and sales.
_KIND_ORDER = {SPLIT: -2, BONUS: -1, DEMERGER_OUT: -1, BUY: 0, DEMERGER_IN: 0, TRANSFER: 1, SELL: 2}


@dataclass(frozen=True)
class Bucket:
    portfolio: int
    broker: int
    folio: Optional[int] = None


@dataclass
class Event:
    """One thing that changes units. ``ref`` identifies the source row (any hashable, used in messages and matches)."""

    kind: str
    on: date                      # effective date (allotment date for a purchase that has one)
    units: Decimal
    bucket: Bucket                # the bucket bought into, sold from, or (for a transfer) taken from
    ref: object = None
    total: Decimal = ZERO         # buy: cost incl. charges; sell: proceeds net of charges
    paid_on: Optional[date] = None  # buy: the transaction date (date paid); defaults to ``on``
    to_bucket: Optional[Bucket] = None  # transfer only
    order: int = 0                # tie-break inside one date and kind (row id)
    estimated: bool = False
    #: DEMERGER_IN only: ``[(bought_on, paid_on, units, cost, estimated)]``, the pieces the units received are made of (their units add up
    #: to ``units``). Empty: one lot at nil cost dated ``on``.
    sources: tuple = ()


@dataclass
class Lot:
    ref: object
    bought_on: date               # effective date: starts the holding period, decides FIFO order
    paid_on: date
    units: Decimal                # units still held
    cost: Decimal                 # cost still held
    original_units: Decimal
    bucket: Bucket
    estimated: bool = False
    #: How much of ``cost`` is there because of a demerger rather than the original transactions: negative on the parent's lot (cost moved
    #: away), the whole cost on a lot of shares received. ``cost - adjustment`` is the cost the original transactions give.
    adjustment: Decimal = ZERO

    @property
    def original_cost(self):
        return self.cost - self.adjustment

    @property
    def unit_cost(self):
        return self.cost / self.units if self.units else ZERO


@dataclass(frozen=True)
class Match:
    """Part of a sale matched to part of a purchase (one line of a capital-gains table)."""

    sell_ref: object
    buy_ref: object
    units: Decimal
    cost: Decimal
    proceeds: Decimal
    bought_on: date
    paid_on: date
    sold_on: date
    bucket: Optional[Bucket] = None
    estimated: bool = False
    adjustment: Decimal = ZERO    # the part of ``cost`` that a demerger put there (see ``Lot.adjustment``)

    @property
    def original_cost(self):
        return self.cost - self.adjustment

    @property
    def holding_days(self):
        return (self.sold_on - self.bought_on).days

    @property
    def gain(self):
        return self.proceeds - self.cost


@dataclass(frozen=True)
class Violation:
    """A sale (or transfer) that asks for more units than its bucket holds on its date."""

    ref: object
    on: date
    bucket: Bucket
    wanted: Decimal
    available: Decimal

    @property
    def shortfall(self):
        return self.wanted - self.available


@dataclass
class Result:
    lots: dict = field(default_factory=dict)       # bucket -> [Lot] oldest first (units > 0 only)
    matches: list = field(default_factory=list)
    violations: list = field(default_factory=list)

    def units(self, bucket=None):
        """Units held in one bucket, or in total."""
        if bucket is not None:
            return sum((lot.units for lot in self.lots.get(bucket, ())), ZERO)
        return sum((lot.units for lots in self.lots.values() for lot in lots), ZERO)

    def cost(self):
        return sum((lot.cost for lots in self.lots.values() for lot in lots), ZERO)

    def all_lots(self):
        return [lot for lots in self.lots.values() for lot in lots]


def sort_events(events):
    return sorted(events, key=lambda e: (e.on, _KIND_ORDER[e.kind], e.order))


def _take(lots, units, wanted_ref, sold_on, proceeds_total, result, move_to=None):
    """Consume ``units`` from ``lots`` oldest first. Returns the consumed (lot, units, cost, adjustment) list."""
    taken = []
    left = units
    while left > 0 and lots:
        lot = lots[0]
        use = min(left, lot.units)
        if use == lot.units:
            cost = lot.cost
            adjustment = lot.adjustment
        else:
            cost = (lot.cost * use / lot.units)
            adjustment = (lot.adjustment * use / lot.units)
        taken.append((lot, use, cost, adjustment))
        lot.units -= use
        lot.cost -= cost
        lot.adjustment -= adjustment
        left -= use
        if lot.units == 0:
            lots.pop(0)
    return taken


def replay(events, as_of=None):
    """Apply ``events`` in date order and return a :class:`Result`.

    ``as_of`` stops the replay after that date (positions on a past date). A sale or transfer that asks for more units
    than its bucket holds is recorded as a :class:`Violation` and takes what is there (so later lines stay meaningful).
    """
    result = Result()
    for event in sort_events(events):
        if as_of is not None and event.on > as_of:
            break
        if event.kind == BUY:
            lots = result.lots.setdefault(event.bucket, [])
            lots.append(Lot(event.ref, event.on, event.paid_on or event.on, event.units, event.total, event.units,
                            event.bucket, event.estimated))
        elif event.kind == SELL:
            lots = result.lots.setdefault(event.bucket, [])
            have = sum((lot.units for lot in lots), ZERO)
            if event.units > have:
                result.violations.append(Violation(event.ref, event.on, event.bucket, event.units, have))
            taken = _take(lots, min(event.units, have), event.ref, event.on, event.total, result)
            for lot, use, cost, adjustment in taken:
                share = event.total * use / event.units if event.units else ZERO
                result.matches.append(Match(event.ref, lot.ref, use, cost, share, lot.bought_on, lot.paid_on, event.on, event.bucket, lot.estimated,
                                            adjustment))
        elif event.kind == TRANSFER:
            src = result.lots.setdefault(event.bucket, [])
            dst = result.lots.setdefault(event.to_bucket, [])
            have = sum((lot.units for lot in src), ZERO)
            if event.units > have:
                result.violations.append(Violation(event.ref, event.on, event.bucket, event.units, have))
            taken = _take(src, min(event.units, have), event.ref, event.on, ZERO, result)
            for lot, use, cost, adjustment in taken:
                dst.append(Lot(lot.ref, lot.bought_on, lot.paid_on, use, cost, use, event.to_bucket, lot.estimated, adjustment))
            dst.sort(key=lambda l: (l.bought_on, str(l.ref)))
        elif event.kind == SPLIT:
            for lots in result.lots.values():
                for lot in lots:
                    lot.units *= event.units
                    lot.original_units *= event.units
        elif event.kind == BONUS:
            for bucket, lots in list(result.lots.items()):
                held = sum((lot.units for lot in lots), ZERO)
                if held > 0:
                    lots.append(Lot(event.ref, event.on, event.on, held * event.units, ZERO, held * event.units, bucket, False))
                    lots.sort(key=lambda l: (l.bought_on, str(l.ref)))
        elif event.kind == DEMERGER_OUT:
            # The part of every lot's cost that moves to the new company's shares leaves the parent's lots (units and dates unchanged).
            for lots in result.lots.values():
                for lot in lots:
                    moved = lot.cost * event.units
                    lot.cost -= moved
                    lot.adjustment -= moved
        elif event.kind == DEMERGER_IN:
            lots = result.lots.setdefault(event.bucket, [])
            if event.sources:
                for bought_on, paid_on, units, cost, estimated in event.sources:
                    lots.append(Lot(event.ref, bought_on, paid_on, units, cost, units, event.bucket, estimated, cost))
            else:
                lots.append(Lot(event.ref, event.on, event.paid_on or event.on, event.units, ZERO, event.units, event.bucket, event.estimated))
            lots.sort(key=lambda l: (l.bought_on, str(l.ref)))
        else:  # pragma: no cover - guarded by the constants above
            raise ValueError(f"unknown event kind {event.kind!r}")
    for bucket in list(result.lots):
        result.lots[bucket] = [lot for lot in result.lots[bucket] if lot.units > 0]
        if not result.lots[bucket]:
            del result.lots[bucket]
    return result


def check_history(events):
    """The violations over the whole history (empty list when every sale and transfer is covered)."""
    return replay(events).violations


def available(events, bucket, on):
    """Units in ``bucket`` after every event up to and including ``on`` (purchases of that day count before sales)."""
    return replay(events, as_of=on).units(bucket)


def available_by_bucket(events, on=None):
    """``{bucket: units}`` held after all events (or up to ``on``)."""
    result = replay(events, as_of=on)
    return {bucket: sum((lot.units for lot in lots), ZERO) for bucket, lots in result.lots.items()}


def average_cost(result):
    """Average cost per unit of the units still held (None when nothing is held)."""
    units = result.units()
    return result.cost() / units if units else None
