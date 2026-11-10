"""Shared service helpers: settings row, data_version bump, rupee amounts and event building.

Every mutating service takes ``(profile, user, ...)`` first and runs inside one ``transaction.atomic()`` (repository habit).
"""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import F

from investments import lots
from investments.models import (
    ORIGIN_DEMERGER, SIDE_BUY, SIDE_SELL, STATUS_FINAL, InvestmentSettings, Transaction, Transfer,
)

ZERO = Decimal(0)
_PAISA = Decimal("0.01")


def get_settings(profile, create=True):
    """The profile's settings row. With ``create=False`` an unsaved row with the defaults is returned when none exists."""
    row = InvestmentSettings.objects.filter(profile=profile).first()
    if row is None:
        row = InvestmentSettings(profile=profile)
        if create:
            row.save()
    return row


def touch(profile):
    """Bump ``data_version`` (cache key, plan 26.4). Creates the settings row if the profile has none."""
    get_settings(profile)
    InvestmentSettings.objects.filter(profile=profile).update(data_version=F("data_version") + 1)


def atomic(fn):
    """Run a service function in one transaction."""
    def wrapper(*args, **kwargs):
        with transaction.atomic():
            return fn(*args, **kwargs)

    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def money(value):
    """Round to paise, half away from zero."""
    return Decimal(value).quantize(_PAISA, rounding=ROUND_HALF_UP)


def buy_total(txn):
    """Cost of a purchase in rupees: units times price plus charges, the rupee amount for foreign, or the override."""
    if txn.cost_override is not None:
        return Decimal(txn.cost_override)
    if txn.rupee_amount is not None:
        return Decimal(txn.rupee_amount) + (Decimal(txn.charges or 0) if txn.currency == "INR" else ZERO)
    return Decimal(txn.units) * Decimal(txn.price) + Decimal(txn.charges or 0)


def sell_total(txn):
    """Proceeds of a sale in rupees: units times price less charges (or the rupee amount for foreign)."""
    if txn.rupee_amount is not None:
        return Decimal(txn.rupee_amount)
    return Decimal(txn.units) * Decimal(txn.price) - Decimal(txn.charges or 0)


def bucket_of(txn):
    return lots.Bucket(txn.portfolio_id, txn.broker_id, txn.folio_id)


def buy_event(t):
    """The lot event for a "buy" row. Shares received on a demerger (origin demerger) are a DEMERGER_IN event whose lots are made from the
    parent's lots by :func:`fill_demerger_receipts`; every other origin is an ordinary purchase (a bonus is simply one at no cost)."""
    if t.origin == ORIGIN_DEMERGER:
        return lots.Event(lots.DEMERGER_IN, t.effective_date, t.units, bucket_of(t), ("txn", t.pk), paid_on=t.date,
                          order=t.pk or 10**12, estimated=t.is_estimated)
    return lots.Event(lots.BUY, t.effective_date, t.units, bucket_of(t), ("txn", t.pk), buy_total(t), paid_on=t.date,
                      order=t.pk or 10**12, estimated=t.is_estimated)


def parent_lots_on(profile, instrument_id, day, seen=frozenset(), cache=None):
    """The lots of ``instrument_id`` held at the end of ``day``, as the profile's history stands (a parent's cost already reduced by any
    earlier demerger). ``seen`` guards against two demergers that point at each other."""
    key = (instrument_id, day)
    if cache is not None and key in cache:
        return cache[key]
    found = lots.replay(events_for(profile, instrument_id, _seen=seen | {instrument_id}), as_of=day).all_lots()
    if cache is not None:
        cache[key] = found
    return found


def fill_demerger_receipts(profile, receipts, seen=frozenset(), cache=None):
    """Give each DEMERGER_IN event its ``sources``. ``receipts`` is ``[(event, transaction)]``.

    A receipt takes its cost, and (if the profile chose so) its purchase dates, from the parent's lots held in the same portfolio and
    broker at the end of the day before the ex-date, spread by units. When several receipts share a portfolio and broker, each moves its
    own part of the cost (by the units it received), so the cost moved always equals the cost the parent lost. A receipt whose action is not
    applied by this profile, or whose parent held nothing there, gets one lot at nil cost dated the day received (the page warns)."""
    from investments import corporate as corporate_math
    from investments.services import corporate as corporate_service

    receipts = [(e, t) for e, t in receipts if t.corporate_action_id]
    if not receipts:
        return
    action_ids = {t.corporate_action_id for _e, t in receipts}
    terms = corporate_service.demerger_terms(profile, action_ids)
    if not terms:
        return
    totals = {}
    rows = Transaction.objects.filter(profile=profile, status=STATUS_FINAL, origin=ORIGIN_DEMERGER, corporate_action_id__in=list(terms),
                                      units__isnull=False).values_list("corporate_action_id", "portfolio_id", "broker_id", "units")
    for action_id, portfolio_id, broker_id, units in rows:
        totals[(action_id, portfolio_id, broker_id)] = totals.get((action_id, portfolio_id, broker_id), ZERO) + units
    cache = {} if cache is None else cache
    for event, t in receipts:
        term = terms.get(t.corporate_action_id)
        if term is None or term.parent_id in seen or t.instrument_id != term.target_id:
            continue
        total = totals.get((t.corporate_action_id, t.portfolio_id, t.broker_id)) or t.units
        if not total:
            continue
        parent = [lot for lot in parent_lots_on(profile, term.parent_id, term.ex_date - timedelta(days=1), seen, cache)
                  if lot.bucket.portfolio == t.portfolio_id and lot.bucket.broker == t.broker_id]
        event.sources = tuple(corporate_math.receipt_sources(parent, t.units, term.fraction * t.units / total, term.inherit_dates, event.on))


def events_for(profile, instrument_id=None, exclude_txn=None, exclude_transfer=None, _seen=frozenset()):
    """Lot events for the profile's final transactions and transfers (one instrument when given).

    Entries that have no units yet (awaiting allotment) or are not confirmed (pending SIP) are left out: they have no
    units, so they cannot be sold, are not in FIFO and do not count in average cost (plan 6).
    """
    txns = Transaction.objects.filter(profile=profile, status=STATUS_FINAL, units__isnull=False)
    transfers = Transfer.objects.filter(profile=profile)
    if instrument_id is not None:
        txns = txns.filter(instrument_id=instrument_id)
        transfers = transfers.filter(instrument_id=instrument_id)
    if exclude_txn is not None:
        txns = txns.exclude(pk=exclude_txn)
    if exclude_transfer is not None:
        transfers = transfers.exclude(pk=exclude_transfer)
    events, receipts = [], []
    for t in txns.iterator(chunk_size=500):
        if t.side == SIDE_BUY:
            event = buy_event(t)
            events.append(event)
            if event.kind == lots.DEMERGER_IN:
                receipts.append((event, t))
        elif t.side == SIDE_SELL:
            events.append(lots.Event(lots.SELL, t.date, t.units, bucket_of(t), ("txn", t.pk), sell_total(t), order=t.pk))
    fill_demerger_receipts(profile, receipts, _seen)
    from investments import corporate as corporate_math
    from investments.services import corporate as corporate_service

    ids = None if instrument_id is None else [instrument_id]
    for actions in corporate_service.applied(profile, ids).values():
        events.extend(corporate_math.events(actions))
    for actions in corporate_service.applied_demergers(profile, ids).values():
        events.extend(corporate_math.events(actions))
    for tr in transfers.iterator(chunk_size=500):
        events.append(lots.Event(
            lots.TRANSFER, tr.date, tr.units, lots.Bucket(tr.from_portfolio_id, tr.from_broker_id, tr.from_folio_id),
            ("transfer", tr.pk), to_bucket=lots.Bucket(tr.to_portfolio_id, tr.to_broker_id, tr.to_folio_id), order=tr.pk))
    return events


def txn_event(t):
    """The lot event for one (final) transaction row, used to test a change before it is saved. A demerger receipt carries no ``sources``
    here (only its units matter for the selling limits)."""
    if t.side == SIDE_BUY:
        return buy_event(t)
    return lots.Event(lots.SELL, t.date, t.units, bucket_of(t), ("txn", t.pk), sell_total(t), order=t.pk or 10**12)


def events_by_instrument(profile):
    """``{instrument id: [lot events]}`` for every investment of the profile, from three queries (for reports that replay everything)."""
    from investments import corporate as corporate_math
    from investments.services import corporate as corporate_service

    out = {}
    fields = ("id", "instrument_id", "side", "date", "allotment_date", "units", "price", "charges", "cost_override", "rupee_amount", "currency",
              "portfolio_id", "broker_id", "folio_id", "is_estimated", "origin", "corporate_action_id")
    receipts = []
    for t in Transaction.objects.filter(profile=profile, status=STATUS_FINAL, units__isnull=False).only(*fields).iterator(chunk_size=1000):
        event = txn_event(t)
        out.setdefault(t.instrument_id, []).append(event)
        if event.kind == lots.DEMERGER_IN:
            receipts.append((event, t))
    fill_demerger_receipts(profile, receipts)
    for tr in Transfer.objects.filter(profile=profile).iterator(chunk_size=500):
        out.setdefault(tr.instrument_id, []).append(lots.Event(
            lots.TRANSFER, tr.date, tr.units, lots.Bucket(tr.from_portfolio_id, tr.from_broker_id, tr.from_folio_id), ("transfer", tr.pk),
            to_bucket=lots.Bucket(tr.to_portfolio_id, tr.to_broker_id, tr.to_folio_id), order=tr.pk))
    for iid, actions in corporate_service.applied(profile).items():
        out.setdefault(iid, []).extend(corporate_math.events(actions))
    for iid, actions in corporate_service.applied_demergers(profile).items():
        out.setdefault(iid, []).extend(corporate_math.events(actions))
    return out
