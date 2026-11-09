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


def compute(profile, *, portfolio=None, broker=None, as_of=None, settings=None, instrument_ids=None, include_dividends=None):
    """``([Holding sorted by name], Totals)`` for the profile as at ``as_of`` (today by default).

    ``portfolio`` and ``broker`` are ids (or None for all). Sold-out investments are included with ``sold_out=True``.
    ``include_dividends`` (default: the profile's Settings choice) counts each dividend as money received on its date in XIRR (plan 7).
    Applied corporate actions change the units (plan 8); an unconfirmed one makes the holding Provisional, or blocked (plan 2).
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

    txns = Transaction.objects.filter(profile=profile, date__lte=as_of).select_related("instrument")
    if instrument_ids is not None:
        txns = txns.filter(instrument_id__in=list(instrument_ids))
    per_instrument = {}
    instruments = {}
    for t in txns.iterator(chunk_size=500):
        per_instrument.setdefault(t.instrument_id, []).append(t)
        instruments[t.instrument_id] = t.instrument
    transfers = {}
    for tr in Transfer.objects.filter(profile=profile, date__lte=as_of).iterator(chunk_size=500):
        transfers.setdefault(tr.instrument_id, []).append(tr)
        if tr.instrument_id not in instruments:
            instruments[tr.instrument_id] = tr.instrument

    ids = list(instruments)
    actions = corporate_service.applied(profile, ids)
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
    total = Totals()
    for iid in sorted(ids, key=lambda i: (instruments[i].name.lower(), i)):
        inst = instruments[iid]
        h = Holding(instrument=inst)
        events, flows = [], []
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
                events.append(lots.Event(lots.BUY, t.effective_date, t.units, core.bucket_of(t), ("txn", t.pk), core.buy_total(t),
                                         paid_on=t.date, order=t.pk, estimated=t.is_estimated))
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
        inst_actions = [a for a in actions.get(iid, []) if a[2] <= as_of]
        events += corporate_math.events(inst_actions)
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
        h.sold_out = h.units == 0 and h.awaiting == 0

        # value
        if inst.kind == KIND_ALTERNATIVE and alts.get(iid):
            alt = valuation.alt_value_on(alts[iid], as_of, settings.alt_treatment)
            if alt is None:
                alt = held_cost
            h.value = (alt if h.units else ZERO) + h.awaiting
            h.price_date = alts[iid][-1][0]
        elif iid in latest and h.units:
            h.price_date, h.price = latest[iid]
            rate = Decimal(1)
            if inst.currency != "INR":
                from investments.services import fx as fx_service

                found = fx_service.rate_on(inst.currency, as_of)
                rate = found[1] if found else (fx or Decimal(1))
            # On a split-adjusted series a past day's units are expressed on today's basis (plan 16.2).
            factor = corporate_math.basis_factor(actions.get(iid, []), as_of, inst.price_basis)
            h.value = h.units * factor * h.price * rate + h.awaiting
        elif inst.kind == KIND_ALTERNATIVE and inst.interest_rate and h.units:
            # A fixed interest rate instead of dated values (plan 11): each lot grows from its date, compounded yearly.
            rate = 1 + float(inst.interest_rate) / 100
            grown = sum((lot.cost * Decimal(str(rate ** ((as_of - lot.bought_on).days / 365.0))) for lot in kept), ZERO)
            h.value = grown.quantize(Decimal("0.01")) + h.awaiting
        else:
            h.value = h.cost
            h.unpriced = bool(h.units) and inst.kind != KIND_ALTERNATIVE
        if h.value is not None and h.sold_out:
            h.value = ZERO
        # XIRR for the holding: every cash flow, and what is held now as money received today.
        if flows and (h.units or h.awaiting):
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
        all_flows.extend((d, float(a)) for d, a in flows)
        total.flows.extend(flows)
    if all_flows:
        total.xirr = xirr.xirr(all_flows + ([(as_of, float(total.value))] if total.value else []))
    return holdings, total


def held(holdings):
    return [h for h in holdings if not h.sold_out]


def allocation(holdings):
    """``[(label, value, share)]`` by asset class, largest first, for the sorted-bars chart (plan 25.3)."""
    by = {}
    for h in held(holdings):
        by[h.instrument.get_asset_class_display()] = by.get(h.instrument.get_asset_class_display(), ZERO) + h.value
    total = sum(by.values(), ZERO)
    rows = sorted(by.items(), key=lambda kv: -kv[1])
    return [(label, value, float(value / total) if total else 0.0) for label, value in rows]
