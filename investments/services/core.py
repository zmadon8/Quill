"""Shared service helpers: settings row, data_version bump, rupee amounts and event building.

Every mutating service takes ``(profile, user, ...)`` first and runs inside one ``transaction.atomic()`` (repository habit).
"""
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import F

from investments import lots
from investments.models import (
    SIDE_BUY, SIDE_SELL, STATUS_FINAL, InvestmentSettings, Transaction, Transfer,
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


def events_for(profile, instrument_id=None, exclude_txn=None, exclude_transfer=None):
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
    events = []
    for t in txns.iterator(chunk_size=500):
        if t.side == SIDE_BUY:
            events.append(lots.Event(lots.BUY, t.effective_date, t.units, bucket_of(t), ("txn", t.pk), buy_total(t),
                                     paid_on=t.date, order=t.pk, estimated=t.is_estimated))
        elif t.side == SIDE_SELL:
            events.append(lots.Event(lots.SELL, t.date, t.units, bucket_of(t), ("txn", t.pk), sell_total(t), order=t.pk))
    for tr in transfers.iterator(chunk_size=500):
        events.append(lots.Event(
            lots.TRANSFER, tr.date, tr.units, lots.Bucket(tr.from_portfolio_id, tr.from_broker_id, tr.from_folio_id),
            ("transfer", tr.pk), to_bucket=lots.Bucket(tr.to_portfolio_id, tr.to_broker_id, tr.to_folio_id), order=tr.pk))
    return events


def txn_event(t):
    """The lot event for one (final) transaction row, used to test a change before it is saved."""
    if t.side == SIDE_BUY:
        return lots.Event(lots.BUY, t.effective_date, t.units, bucket_of(t), ("txn", t.pk), buy_total(t), paid_on=t.date,
                          order=t.pk or 10**12, estimated=t.is_estimated)
    return lots.Event(lots.SELL, t.date, t.units, bucket_of(t), ("txn", t.pk), sell_total(t), order=t.pk or 10**12)
