"""Holdings, values and XIRR calculated from transactions (plan sections 5, 6 and 9). Nothing here is ever typed in.

``compute`` replays each investment's history once (FIFO per portfolio/broker/folio bucket), then filters the resulting lots by
the chosen portfolio and broker. Prices come from ``services.prices`` (manual in Phase 1). An investment with no price is
valued at cost and flagged ``unpriced``; an awaiting-allotment purchase is valued at cost (the default, plan 6) or left out,
as the profile's setting says.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from investments import lots, valuation, xirr
from investments.models import (
    AWAITING_LEAVE_OUT, KIND_ALTERNATIVE, SIDE_BUY, STATUS_AWAITING, STATUS_FINAL, Instrument,
    Transaction, Transfer,
)
from investments.services import core, prices

ZERO = Decimal(0)
UNIT_DUST = Decimal("0.00005")   # half the smallest unit stored (4 decimal places)


@dataclass
class Holding:
    instrument: Instrument
    units: Decimal = ZERO
    cost: Decimal = ZERO                 # cost of the units held (FIFO), plus awaiting purchases at cost
    awaiting: Decimal = ZERO             # amount paid and not yet allotted
    price: Decimal = None
    price_date: date = None
    value: Decimal = ZERO
    unpriced: bool = False
    xirr: float = None
    lots: list = field(default_factory=list)
    buckets: dict = field(default_factory=dict)   # (portfolio, broker, folio) -> units
    realised: Decimal = ZERO
    sold_out: bool = False
    empty: bool = False                             # added to the profile but nothing bought (as at the date); never "held"
    first_date: date = None
    flows: list = field(default_factory=list)     # [(date, Decimal)] money paid in (negative) and received (positive), dates paid
    index_xirr: float = None
    alpha: float = None
    sect_xirr: float = None
    sect_alpha: float = None
    dividends: Decimal = ZERO                       # received, shown separately; never part of value
    provisional: bool = False                       # a corporate action is waiting for this profile's confirmation
    blocked: bool = False                           # ... and Settings says block: value, gain and XIRR are n/a and left out of totals

    @property
    def is_held(self):
        """True only when units are held or a purchase is awaiting allotment."""
        return not self.sold_out and not self.empty and (self.units > 0 or self.awaiting > 0)

    @property
    def avg_cost(self):
        return self.cost_of_units / self.units if self.units else None

    @property
    def cost_of_units(self):
        return self.cost - self.awaiting

    @property
    def gain(self):
        return self.value - self.cost

    @property
    def gain_pct(self):
        return float(self.gain / self.cost) if self.cost else None


@dataclass
class Totals:
    flows: list = field(default_factory=list)
    dividends: Decimal = ZERO
    provisional: int = 0
    blocked: int = 0
    index_xirr: float = None
    alpha: float = None
    sect_xirr: float = None
    sect_alpha: float = None
    invested: Decimal = ZERO
    value: Decimal = ZERO
    awaiting: Decimal = ZERO
    xirr: float = None
    count: int = 0

    @property
    def gain(self):
        return self.value - self.invested

    @property
    def gain_pct(self):
        return float(self.gain / self.invested) if self.invested else None


def _passes(portfolio, broker, portfolio_id, broker_id):
    return (portfolio is None or portfolio_id == portfolio) and (broker is None or broker_id == broker)


#: The columns of a transaction that ``compute`` and the helpers it calls read. Loading only these (and not the notes, references,
#: timestamps and so on) makes reading thousands of rows noticeably cheaper; the query-count test in test_speed.py guards against a column
#: being forgotten (reading a deferred column costs one query per row).
TXN_FIELDS = ("id", "instrument_id", "side", "status", "date", "allotment_date", "units", "price", "charges", "amount", "cost_override",
              "rupee_amount", "currency", "fx_rate", "portfolio_id", "broker_id", "folio_id", "is_estimated", "origin", "corporate_action_id")


@dataclass
class History:
    """A profile's transactions and transfers up to ``as_of``, read once. ``compute(history=...)`` filters them to its own date, so a caller
    that needs the holdings at several dates (the Overview's opening values) reads the database once instead of once per date."""
    as_of: date
    per_instrument: dict      # instrument id -> [Transaction], newest first (the model's own order)
    transfers: dict           # instrument id -> [Transfer]
    instruments: dict         # instrument id -> Instrument


def load_history(profile, as_of=None, instrument_ids=None):
    """Read the transactions and transfers of ``profile`` dated on or before ``as_of`` (today by default)."""
    as_of = as_of or date.today()
    txns = Transaction.objects.filter(profile=profile, date__lte=as_of).only(*TXN_FIELDS)
    if instrument_ids is not None:
        txns = txns.filter(instrument_id__in=list(instrument_ids))
    per_instrument = {}
    for t in txns.iterator(chunk_size=2000):
        per_instrument.setdefault(t.instrument_id, []).append(t)
    transfers = {}
    for tr in Transfer.objects.filter(profile=profile, date__lte=as_of).iterator(chunk_size=2000):
        transfers.setdefault(tr.instrument_id, []).append(tr)
    # One query for the investments (a few hundred), not one joined copy of an investment per transaction.
    instruments = Instrument.objects.in_bulk(set(per_instrument) | set(transfers))
    return History(as_of, per_instrument, transfers, instruments)


def compute(profile, *, portfolio=None, broker=None, as_of=None, settings=None, instrument_ids=None, include_dividends=None, with_xirr=True,
            history=None):
    """``([Holding sorted by name], Totals)`` for the profile as at ``as_of`` (today by default).

    ``portfolio`` and ``broker`` are ids (or None for all). Sold-out investments are included with ``sold_out=True``.
    ``include_dividends`` (default: the profile's Settings choice) counts each dividend as money received on its date in XIRR (plan 7).
    Applied corporate actions change the units (plan 8); an unconfirmed one makes the holding Provisional, or blocked (plan 2).
    ``with_xirr=False`` skips the XIRR of each holding and of the total (they stay None); units, cost, value and flows are unchanged. A caller
    that only needs a value as at a past date (the opening value of an Overview period) uses it, as XIRR is the slowest step per holding.
    ``history`` is a :class:`History` read earlier for the same profile and a date on or after ``as_of`` (and no ``instrument_ids``): the
    database is then not read for transactions again.
    """
    from investments import corporate as corporate_math
    from investments.models import CA_TAG, Dividend
    from investments.services import corporate as corporate_service

    as_of = as_of or date.today()
    settings = settings or core.get_settings(profile, create=False)
    leave_out = settings.awaiting_treatment == AWAITING_LEAVE_OUT
    if include_dividends is None:
        include_dividends = settings.include_dividends
    block = settings.corporate_action_mode != CA_TAG

    if history is None:
        history = load_history(profile, as_of, instrument_ids)
    elif history.as_of < as_of or instrument_ids is not None:
        raise ValueError("The history must cover the date asked for and be read for the whole profile.")
    per_instrument, transfers = {}, {}
    for iid, rows in history.per_instrument.items():
        kept = rows if history.as_of <= as_of else [t for t in rows if t.date <= as_of]
        if kept:
            per_instrument[iid] = kept
    for iid, rows in history.transfers.items():
        kept = rows if history.as_of <= as_of else [tr for tr in rows if tr.date <= as_of]
        if kept:
            transfers[iid] = kept
    instruments = {iid: history.instruments[iid] for iid in set(per_instrument) | set(transfers)}

    ids = list(instruments)
    actions = corporate_service.applied(profile, ids)
    # Every applied split and bonus, however its units were recorded: a price series restated by the vendor needs them all (plan 16.2).
    basis_actions = corporate_service.applied(profile, ids, for_units=False)
    demergers = corporate_service.applied_demergers(profile, ids)
    demerger_cache = {}
    pending_ids = corporate_service.pending_instrument_ids(profile)
    dividends = {}
    divq = Dividend.objects.filter(profile=profile, date__lte=as_of, instrument_id__in=ids)
    if portfolio:
        divq = divq.filter(portfolio_id=portfolio)
    if broker:
        divq = divq.filter(broker_id=broker)
    for iid, day, amount in divq.values_list("instrument_id", "date", "amount"):
        dividends.setdefault(iid, []).append((day, amount))
    latest = prices.latest_prices(ids, as_of)
    alts = prices.alt_values(profile, [i for i in ids if instruments[i].kind == KIND_ALTERNATIVE])

    holdings = []
    all_flows = []
    fx_found = {}
    total = Totals()
    for iid in sorted(ids, key=lambda i: (instruments[i].name.lower(), i)):
        inst = instruments[iid]
        h = Holding(instrument=inst)
        events, flows, receipts = [], [], []
        fx = None
        for t in per_instrument.get(iid, []):
            if t.fx_rate:
                fx = t.fx_rate
            if t.status == STATUS_AWAITING:
                if leave_out or not _passes(portfolio, broker, t.portfolio_id, t.broker_id):
                    continue
                amount = t.amount or ZERO
                if t.side == SIDE_BUY:
                    h.awaiting += amount
                    flows.append((t.date, -amount))
                continue
            if t.status != STATUS_FINAL or t.units is None:
                continue
            if h.first_date is None or t.date < h.first_date:
                h.first_date = t.date
            if t.side == SIDE_BUY:
                event = core.buy_event(t)
                events.append(event)
                if event.kind == lots.DEMERGER_IN:
                    receipts.append((event, t))
                if _passes(portfolio, broker, t.portfolio_id, t.broker_id):
                    flows.append((t.date, -core.buy_total(t)))
            else:
                events.append(lots.Event(lots.SELL, t.date, t.units, core.bucket_of(t), ("txn", t.pk), core.sell_total(t), order=t.pk))
                if _passes(portfolio, broker, t.portfolio_id, t.broker_id):
                    flows.append((t.date, core.sell_total(t)))
        for tr in transfers.get(iid, []):
            if portfolio is not None or broker is not None:
                # Seen through a portfolio or broker filter, a transfer across the boundary is money leaving one side and arriving at the
                # other at the market value on the transfer date (plan 9, Compare brokers), so neither side's result is distorted.
                out_of = _passes(portfolio, broker, tr.from_portfolio_id, tr.from_broker_id)
                into = _passes(portfolio, broker, tr.to_portfolio_id, tr.to_broker_id)
                if out_of != into:
                    at = prices.latest_prices([iid], tr.date).get(iid)
                    if at:
                        market = tr.units * at[1]
                        flows.append((tr.date, market if out_of else -market))
            events.append(lots.Event(lots.TRANSFER, tr.date, tr.units, lots.Bucket(tr.from_portfolio_id, tr.from_broker_id, tr.from_folio_id),
                                     ("transfer", tr.pk), to_bucket=lots.Bucket(tr.to_portfolio_id, tr.to_broker_id, tr.to_folio_id), order=tr.pk))
        inst_actions = [a for a in actions.get(iid, []) + demergers.get(iid, []) if a[2] <= as_of]
        events += corporate_math.events(inst_actions)
        core.fill_demerger_receipts(profile, receipts, cache=demerger_cache)
        h.dividends = sum((a for _d, a in dividends.get(iid, [])), ZERO)
        if include_dividends:
            flows += [(d, a) for d, a in dividends.get(iid, [])]
        result = lots.replay(events)
        kept = [lot for lot in result.all_lots() if _passes(portfolio, broker, lot.bucket.portfolio, lot.bucket.broker)]
        h.lots = kept
        h.units = sum((lot.units for lot in kept), ZERO)
        held_cost = sum((lot.cost for lot in kept), ZERO)
        h.cost = held_cost + h.awaiting
        for lot in kept:
            key = (lot.bucket.portfolio, lot.bucket.broker, lot.bucket.folio)
            h.buckets[key] = h.buckets.get(key, ZERO) + lot.units
        h.realised = sum((m.gain for m in result.matches), ZERO)
        if abs(h.units) < UNIT_DUST:
            # A corporate-action ratio can leave a remainder below the 4 decimal places units are kept to: that is nothing held.
            h.units = ZERO
        h.sold_out = h.units == 0 and h.awaiting == 0

        # value
        if inst.kind == KIND_ALTERNATIVE and (alts.get(iid) or (inst.interest_rate and h.units)):
            # The latest manual value on or before as_of is a new base that keeps growing at the rate; lots bought after it add their own interest.
            alt = valuation.alt_or_interest_value(alts.get(iid, []), as_of, settings.alt_treatment, [(lot.bought_on, lot.cost) for lot in kept],
                                                  inst.interest_rate, inst.interest_type)
            if alt is None:
                alt = held_cost
            h.value = (alt if h.units else ZERO) + h.awaiting
            if alts.get(iid):
                h.price_date = alts[iid][-1][0]
        elif iid in latest and h.units:
            h.price_date, h.price = latest[iid]
            rate = Decimal(1)
            if inst.currency != "INR":
                from investments.services import fx as fx_service

                if inst.currency not in fx_found:      # one look-up per currency, not per investment
                    fx_found[inst.currency] = fx_service.rate_on(inst.currency, as_of)
                found = fx_found[inst.currency]
                rate = found[1] if found else (fx or Decimal(1))
            # On a split-adjusted series a past day's units are expressed on today's basis (plan 16.2).
            factor = corporate_math.basis_factor(basis_actions.get(iid, []), as_of, inst.price_basis)
            h.value = h.units * factor * h.price * rate + h.awaiting
        else:
            h.value = h.cost
            h.unpriced = bool(h.units) and inst.kind != KIND_ALTERNATIVE
        if h.value is not None and h.sold_out:
            h.value = ZERO
        # XIRR for the holding: every cash flow, and what is held now as money received today.
        if not with_xirr:
            pass
        elif flows and (h.units or h.awaiting):
            h.xirr = xirr.xirr([(d, float(a)) for d, a in flows] + [(as_of, float(h.value))])
        elif flows:
            h.xirr = xirr.xirr([(d, float(a)) for d, a in flows])
        h.flows = list(flows)
        h.provisional = iid in pending_ids and bool(h.units)
        h.blocked = h.provisional and block
        if h.blocked:
            h.xirr = None
        if flows or h.units or h.awaiting:
            holdings.append(h)
        total.dividends += h.dividends
        total.provisional += 1 if h.provisional else 0
        total.blocked += 1 if h.blocked else 0
        if h.blocked:
            continue
        if h.units or h.awaiting:
            total.invested += h.cost
            total.value += h.value
            total.awaiting += h.awaiting
            total.count += 1
        if with_xirr:
            all_flows.extend((d, float(a)) for d, a in flows)
        total.flows.extend(flows)
    if all_flows:
        total.xirr = xirr.xirr(all_flows + ([(as_of, float(total.value))] if total.value else []))
    return holdings, total


def held(holdings):
    return [h for h in holdings if h.is_held]


def allocation(holdings):
    """``[(label, value, share)]`` by asset class, largest first, for the sorted-bars chart (plan 25.3)."""
    by = {}
    for h in held(holdings):
        by[h.instrument.get_asset_class_display()] = by.get(h.instrument.get_asset_class_display(), ZERO) + h.value
    total = sum(by.values(), ZERO)
    rows = sorted(by.items(), key=lambda kv: -kv[1])
    return [(label, value, float(value / total) if total else 0.0) for label, value in rows]
