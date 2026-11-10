"""Transactions: buy, sell, opening balance, transfer, switch, awaiting allotment and its completion (plan sections 6 and 19).

Every function takes ``(profile, user, ...)`` first and runs in one transaction. After each change that could affect units
the whole history of the investment is replayed (``investments.lots``); a change that would leave any broker, folio or
portfolio bucket with negative units on any date is refused with the conflicting sales listed (plan 6, "Editing").
"""
import datetime
from decimal import Decimal

from django.db import transaction

from investments import lots
from investments.errors import InvestmentsError, not_found
from investments.models import (
    ACTION_ORIGINS, CA_DEMERGER, HOLDABLE_KINDS, METHOD_EVENTS, NO_PRICE_ORIGINS, ORIGIN_DEMERGER, ORIGIN_PURCHASE, ORIGINS, SIDE_BUY, SIDE_SELL,
    STATUS_AWAITING, STATUS_FINAL, STATUS_PENDING_SIP, ZERO_PRICE_ORIGINS, Broker, CorporateActionResponse, Folio, Portfolio, Switch, Transaction,
    Transfer, new_group,
)
from investments.services import core, history, pins

ZERO = Decimal(0)
#: Completion tolerance: units times NAV plus charges may differ from the amount paid by this much (rounding).
TOLERANCE_ABS = Decimal("1.00")
TOLERANCE_PCT = Decimal("0.001")


# ---------------------------------------------------------------- validation helpers

def _pin(profile, txn):
    """Pin the index values on the transaction's date from stored prices (plan 17.2). A pin is a convenience for old reports, so a problem
    here must never stop a transaction from being saved; the nightly `pin_prices` step fills anything missing."""
    try:
        pins.pin_transaction(profile, txn)
    except Exception:  # pragma: no cover - defensive
        import logging

        logging.getLogger(__name__).exception("Could not pin prices for transaction %s", getattr(txn, "pk", None))


def _today():
    return datetime.date.today()


def _dec(value, name, allow_none=False, minimum=None):
    if value is None or value == "":
        if allow_none:
            return None
        raise InvestmentsError("REQUIRED", f"{name} is required.")
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except Exception:
        raise InvestmentsError("BAD_NUMBER", f"{name} is not a number.")
    if not number.is_finite():
        raise InvestmentsError("BAD_NUMBER", f"{name} is not a number.")
    if minimum is not None and number < minimum:
        raise InvestmentsError("BAD_NUMBER", f"{name} cannot be less than {minimum}.")
    return number


def _check_refs(profile, instrument, portfolio, broker, folio=None):
    if instrument.profile_id not in (None, profile.pk):
        raise not_found("investment")
    if instrument.kind not in HOLDABLE_KINDS:
        raise InvestmentsError("NOT_HOLDABLE", "An index cannot be bought or sold. It is only used for comparison.")
    if portfolio.profile_id != profile.pk:
        raise not_found("portfolio")
    if broker.profile_id != profile.pk:
        raise not_found("broker")
    if folio is not None and (folio.profile_id != profile.pk or folio.instrument_id != instrument.pk or folio.portfolio_id != portfolio.pk):
        raise InvestmentsError("BAD_FOLIO", "That folio does not belong to this investment and portfolio.")


def _check_date(value, name="Date", allow_future=False):
    if not isinstance(value, datetime.date):
        raise InvestmentsError("BAD_DATE", f"{name} is not a date.")
    if not allow_future and value > _today():
        raise InvestmentsError("FUTURE_DATE", f"{name} cannot be in the future.")


def _check_origin(profile, instrument, origin, action, *, side, awaiting=False, is_opening=False):
    """The rules for how units were acquired. A purchase is ordinary. Bonus, split, demerger and no-cost entries are buys that need no
    price; a bonus, split or demerger may name its corporate action, and a demerger must (its cost comes from the action). Units for a bonus or
    split the profile has chosen to let the program add itself are refused, because they would be counted twice."""
    if origin not in dict(ORIGINS):
        raise InvestmentsError("BAD_ORIGIN", "Choose how the units were acquired.")
    if origin == ORIGIN_PURCHASE:
        if action is not None:
            raise InvestmentsError("BAD_ORIGIN", "Only bonus, split or demerger units can belong to a corporate action.")
        return
    if side != SIDE_BUY or awaiting:
        raise InvestmentsError("BAD_ORIGIN", "Only a purchase entry can be bonus shares, split units, shares received on a demerger or a no-cost entry.")
    if is_opening:
        raise InvestmentsError("BAD_COMBINATION", "An opening balance is a purchase with its cost. Record bonus or split units as a separate entry.")
    if origin not in ACTION_ORIGINS:
        if action is not None:
            raise InvestmentsError("BAD_ORIGIN", "Only bonus, split or demerger units can belong to a corporate action.")
        return
    if origin == ORIGIN_DEMERGER and action is None:
        raise InvestmentsError("REQUIRED", "Choose the demerger these shares were received on. Record it on the Corporate actions page and apply it first.")
    if action is None:
        return
    response = CorporateActionResponse.objects.filter(profile=profile, action=action).first()
    applied = response is not None and response.status == "applied"
    if origin == ORIGIN_DEMERGER:
        if action.kind != CA_DEMERGER or action.target_instrument_id != instrument.pk:
            raise InvestmentsError("BAD_ACTION", "That demerger is not into this investment. Choose the demerger whose new company is this one.")
        if not applied:
            raise InvestmentsError("NOT_APPLIED", "Apply the demerger on the Corporate actions page first: it moves part of the parent's cost, "
                                                  "and these shares take their cost from there.")
        return
    if action.kind != origin or action.instrument_id != instrument.pk:
        raise InvestmentsError("BAD_ACTION", f"That is not a {origin} of this investment.")
    if applied and response.method == METHOD_EVENTS:
        raise InvestmentsError(
            "DOUBLE_COUNT", f"This {origin} is set to be added by the program, so recording its units as well would count them twice. On the "
            "Corporate actions page choose \"I record the units as transactions\" for it first.", 409)


def describe_violation(v):
    """A plain sentence for one :class:`lots.Violation`."""
    broker = Broker.objects.filter(pk=v.bucket.broker).values_list("name", flat=True).first() or "this broker"
    folio = ""
    if v.bucket.folio:
        folio = " in folio " + (Folio.objects.filter(pk=v.bucket.folio).values_list("number", flat=True).first() or "?")
    return (f"On {v.on:%d %b %Y} {v.wanted.normalize():f} units are sold or moved from {broker}{folio}, but only "
            f"{v.available.normalize():f} are held there ({v.shortfall.normalize():f} short).")


def _refuse(violations, what):
    items = []
    for v in violations:
        kind, pk = v.ref
        items.append({"kind": kind, "id": pk, "date": v.on, "message": describe_violation(v), "shortfall": v.shortfall})
    raise InvestmentsError(
        "WOULD_GO_NEGATIVE",
        f"{what} would leave a broker or folio with fewer units than were sold or moved on a later date. "
        "Fix the later entry first.",
        409, {"conflicts": items},
    )


def _recheck(profile, instrument_id, add=None, exclude_txn=None, exclude_transfer=None, what="This change"):
    events = core.events_for(profile, instrument_id, exclude_txn=exclude_txn, exclude_transfer=exclude_transfer)
    events.extend(add or [])
    violations = lots.check_history(events)
    if violations:
        _refuse(violations, what)


def verify_restored(profile, obj):
    """Used by ``history.restore``: refuse bringing back a row that would break the units history."""
    if isinstance(obj, Transaction) and obj.status == STATUS_FINAL:
        _recheck(profile, obj.instrument_id, add=[core.txn_event(obj)], what="Restoring this entry")
    elif isinstance(obj, Transfer):
        _recheck(profile, obj.instrument_id, add=[_transfer_event(obj)], what="Restoring this transfer")


def _transfer_event(tr):
    return lots.Event(lots.TRANSFER, tr.date, tr.units, lots.Bucket(tr.from_portfolio_id, tr.from_broker_id, tr.from_folio_id),
                      ("transfer", tr.pk or 10**12), to_bucket=lots.Bucket(tr.to_portfolio_id, tr.to_broker_id, tr.to_folio_id),
                      order=tr.pk or 10**12)


# ---------------------------------------------------------------- reading

def available_by_bucket(profile, instrument, on=None, exclude_txn=None):
    """``[(portfolio, broker, folio_or_None, units)]`` held on ``on`` (today by default), units above zero only. For the sale form."""
    events = core.events_for(profile, instrument.pk, exclude_txn=exclude_txn)
    held = lots.available_by_bucket(events, on or _today())
    portfolios = {p.pk: p for p in Portfolio.objects.filter(profile=profile)}
    brokers = {b.pk: b for b in Broker.objects.filter(profile=profile)}
    folios = {f.pk: f for f in Folio.objects.filter(profile=profile, instrument=instrument)}
    out = []
    for bucket, units in held.items():
        if units > 0:
            out.append((portfolios.get(bucket.portfolio), brokers.get(bucket.broker), folios.get(bucket.folio), units))
    out.sort(key=lambda r: (r[0].name if r[0] else "", r[1].name if r[1] else "", r[2].number if r[2] else ""))
    return out


def get_transaction(profile, pk):
    txn = Transaction.objects.select_related("instrument", "portfolio", "broker", "folio").filter(pk=pk, profile=profile).first()
    if txn is None:
        raise not_found("transaction")
    return txn


def nav_suggestions(profile, txn, limit=10):
    """Stored NAVs on and after the payment date with the units each would give. A suggestion only (plan 6)."""
    from investments.services import prices

    if txn.status != STATUS_AWAITING or txn.amount is None:
        return []
    rows = []
    for day, nav in prices.series_from(txn.instrument, txn.date, limit):
        if nav and nav > 0:
            units = ((txn.amount - (txn.charges or ZERO)) / nav).quantize(Decimal("0.0001"))
            rows.append({"date": day, "nav": nav, "units": units})
    return rows


# ---------------------------------------------------------------- create

def _new_txn(profile, user, side, instrument, portfolio, broker, folio, day, **extra):
    return Transaction(profile=profile, side=side, instrument=instrument, portfolio=portfolio, broker=broker, folio=folio,
                       date=day, created_by=user if getattr(user, "pk", None) else None, **extra)


@transaction.atomic
def add_transaction(profile, user, *, side, instrument, portfolio, broker, date, units=None, price=None, charges=0, folio=None,
                    awaiting=False, amount=None, expected_allotment_date=None, reference="", note="", is_opening=False,
                    is_estimated=False, allotment_date=None, status=None, switch=None, currency=None, fx_rate=None,
                    rupee_amount=None, origin=ORIGIN_PURCHASE, corporate_action=None):
    """Record one purchase or sale. ``awaiting=True`` saves only the date paid and the amount (plan 6).

    ``origin`` says how bought units came to be held: a purchase (the default, with a price), bonus shares, units from a split, shares
    received on a demerger, or other at no cost. Bonus, split and demerger entries have a price of 0 (a demerger's cost comes from its
    ``corporate_action``, applied on the Corporate actions page); the original purchases are never touched."""
    if side not in (SIDE_BUY, SIDE_SELL):
        raise InvestmentsError("BAD_SIDE", "Choose Buy or Sell.")
    _check_refs(profile, instrument, portfolio, broker, folio)
    _check_date(date)
    _check_origin(profile, instrument, origin, corporate_action, side=side, awaiting=awaiting, is_opening=is_opening)
    charges = _dec(charges or 0, "Charges", minimum=ZERO)
    common = dict(charges=charges, reference=(reference or "").strip(), note=(note or "").strip(), is_opening=is_opening,
                  is_estimated=is_estimated, switch=switch, currency=currency or instrument.currency)
    if awaiting:
        if is_opening:
            raise InvestmentsError("BAD_COMBINATION", "An opening balance needs its units and cost.")
        amount = _dec(amount, "Amount paid" if side == SIDE_BUY else "Expected proceeds", minimum=Decimal("0.01"))
        if expected_allotment_date:
            _check_date(expected_allotment_date, "Expected allotment date", allow_future=True)
        txn = _new_txn(profile, user, side, instrument, portfolio, broker, folio, date, status=STATUS_AWAITING, amount=amount,
                       expected_allotment_date=expected_allotment_date, **common)
        txn.save()
        history.record(profile, user, txn, "create", summary=f"Awaiting {side} of {instrument.name}")
        _pin(profile, txn)
        core.touch(profile)
        return txn
    units = _dec(units, "Units", minimum=Decimal("0.0001"))
    if origin in ZERO_PRICE_ORIGINS:
        if price not in (None, "") and _dec(price, "Price", minimum=ZERO) != ZERO:
            raise InvestmentsError("BAD_NUMBER", "These units are recorded at no cost, so the price must be 0.")
        price = ZERO
    else:
        price = _dec(price if origin == ORIGIN_PURCHASE or price not in (None, "") else 0, "Price", minimum=ZERO if (is_opening or origin in NO_PRICE_ORIGINS) else Decimal("0.0001"))
    if instrument.currency != "INR" and rupee_amount in (None, "") and not (origin != ORIGIN_PURCHASE and price == ZERO):
        # Foreign investment (plan 22): units, price and charges are in its currency; the rupee amount uses the day's rate unless given.
        from investments.services import fx

        if fx_rate in (None, ""):
            found = fx.rate_on(instrument.currency, date)
            if found is None:
                raise InvestmentsError("NO_RATE", f"No {instrument.currency} to rupee rate is stored for that date. Enter the rate you got, or the rupee amount.")
            fx_rate = found[1]
        fx_rate = _dec(fx_rate, "Exchange rate", minimum=Decimal("0.000001"))
        local = units * price + (charges if side == SIDE_BUY else -charges)
        rupee_amount = (local * fx_rate).quantize(Decimal("0.01"))
    elif rupee_amount not in (None, ""):
        rupee_amount = _dec(rupee_amount, "Rupee amount", minimum=ZERO)
        if instrument.currency != "INR" and fx_rate in (None, ""):
            local = units * price + (charges if side == SIDE_BUY else -charges)
            fx_rate = (rupee_amount / local).quantize(Decimal("0.000001")) if local else None
    if allotment_date and allotment_date < date:
        raise InvestmentsError("BAD_DATE", "The allotment date cannot be before the date paid.")
    txn = _new_txn(profile, user, side, instrument, portfolio, broker, folio, date, units=units, price=price,
                   status=status or STATUS_FINAL, allotment_date=allotment_date, fx_rate=fx_rate, rupee_amount=rupee_amount,
                   origin=origin, corporate_action=corporate_action, **common)
    if txn.status == STATUS_FINAL:
        txn.pk = None
        add = [core.txn_event(txn)]
        _recheck(profile, instrument.pk, add=add, what="This sale" if side == SIDE_SELL else "This purchase")
    txn.save()
    if origin != ORIGIN_PURCHASE:
        summary = f"Recorded {units} {instrument.name} ({txn.get_origin_display().lower()})"
    else:
        summary = f"{'Bought' if side == SIDE_BUY else 'Sold'} {units} {instrument.name}"
    history.record(profile, user, txn, "create", summary=summary)
    _pin(profile, txn)
    core.touch(profile)
    return txn


@transaction.atomic
def add_opening_balances(profile, user, *, instrument, portfolio, broker, folio=None, lines):
    """Several opening lots for one investment in one go (plan 19). ``lines`` is ``[{date, units, cost_per_unit, estimated}]``."""
    if not lines:
        raise InvestmentsError("REQUIRED", "Add at least one lot.")
    new_group()
    created = []
    for line in lines:
        txn = add_transaction(profile, user, side=SIDE_BUY, instrument=instrument, portfolio=portfolio, broker=broker, folio=folio,
                              date=line["date"], units=line["units"], price=line["cost_per_unit"], charges=0, is_opening=True,
                              is_estimated=bool(line.get("estimated")), note=line.get("note", ""))
        created.append(txn)
    return created


@transaction.atomic
def add_transfer(profile, user, *, instrument, date, units, from_portfolio, from_broker, to_portfolio, to_broker,
                 from_folio=None, to_folio=None, note=""):
    _check_refs(profile, instrument, from_portfolio, from_broker, from_folio)
    _check_refs(profile, instrument, to_portfolio, to_broker, to_folio)
    _check_date(date)
    units = _dec(units, "Units", minimum=Decimal("0.0001"))
    if (from_portfolio.pk, from_broker.pk, getattr(from_folio, "pk", None)) == (to_portfolio.pk, to_broker.pk, getattr(to_folio, "pk", None)):
        raise InvestmentsError("SAME_PLACE", "The units would stay where they are. Choose a different portfolio, broker or folio.")
    tr = Transfer(profile=profile, date=date, instrument=instrument, units=units, from_portfolio=from_portfolio,
                  from_broker=from_broker, from_folio=from_folio, to_portfolio=to_portfolio, to_broker=to_broker,
                  to_folio=to_folio, note=(note or "").strip(), created_by=user if getattr(user, "pk", None) else None)
    _recheck(profile, instrument.pk, add=[_transfer_event(tr)], what="This transfer")
    tr.save()
    history.record(profile, user, tr, "create", summary=f"Transferred {units} {instrument.name}")
    core.touch(profile)
    return tr


@transaction.atomic
def delete_transfer(profile, user, pk):
    tr = Transfer.objects.filter(pk=pk, profile=profile).first()
    if tr is None:
        raise not_found("transfer")
    _recheck(profile, tr.instrument_id, exclude_transfer=tr.pk, what="Deleting this transfer")
    history.record(profile, user, tr, "delete", summary=f"Deleted transfer of {tr.instrument.name}")
    tr.delete()
    core.touch(profile)


@transaction.atomic
def add_switch(profile, user, *, date, portfolio, broker, from_instrument, units_out, price_out, to_instrument, units_in,
               price_in, charges=0, from_folio=None, to_folio=None, note=""):
    """A fund switch: a sale of one fund and a purchase of another on the same day, linked (plan 19)."""
    sw = Switch.objects.create(profile=profile, date=date, note=(note or "").strip())
    history.record(profile, user, sw, "create", summary="Fund switch")
    sale = add_transaction(profile, user, side=SIDE_SELL, instrument=from_instrument, portfolio=portfolio, broker=broker,
                           folio=from_folio, date=date, units=units_out, price=price_out, charges=charges, switch=sw)
    buy = add_transaction(profile, user, side=SIDE_BUY, instrument=to_instrument, portfolio=portfolio, broker=broker,
                          folio=to_folio, date=date, units=units_in, price=price_in, charges=0, switch=sw)
    return sw, sale, buy


# ---------------------------------------------------------------- edit and delete

def _check_clash(txn, expected_version):
    if expected_version is not None and int(expected_version) != txn.version:
        raise InvestmentsError("CLASH", "Someone else changed this entry after you opened it. Reload and try again.", 409)


@transaction.atomic
def edit_transaction(profile, user, pk, *, expected_version=None, **fields):
    """Edit any field of a transaction. ``fields`` uses the same names as ``add_transaction`` (only those given change)."""
    txn = Transaction.objects.select_for_update().filter(pk=pk, profile=profile).first()
    if txn is None:
        raise not_found("transaction")
    _check_clash(txn, expected_version)
    allowed = {"date", "units", "price", "charges", "instrument", "portfolio", "broker", "folio", "note", "reference", "amount",
               "expected_allotment_date", "allotment_date", "is_estimated", "cost_override", "cost_override_note", "origin", "corporate_action"}
    unknown = set(fields) - allowed
    if unknown:
        raise InvestmentsError("BAD_FIELD", f"Cannot edit: {', '.join(sorted(unknown))}.")
    for key, value in fields.items():
        if key in ("units", "price", "charges", "amount", "cost_override"):
            value = _dec(value, key, allow_none=key in ("units", "price", "amount", "cost_override"), minimum=ZERO)
        setattr(txn, key, value)
    _check_refs(profile, txn.instrument, txn.portfolio, txn.broker, txn.folio)
    _check_date(txn.date)
    _check_origin(profile, txn.instrument, txn.origin, txn.corporate_action, side=txn.side, awaiting=txn.status == STATUS_AWAITING,
                  is_opening=txn.is_opening)
    if txn.origin in ZERO_PRICE_ORIGINS:
        if txn.price not in (None, ZERO):
            raise InvestmentsError("BAD_NUMBER", "These units are recorded at no cost, so the price must be 0.")
        txn.price = ZERO
    if txn.status == STATUS_AWAITING:
        if txn.amount is None or txn.amount <= 0:
            raise InvestmentsError("REQUIRED", "Amount paid is required.")
    else:
        if not txn.units or txn.units <= 0:
            raise InvestmentsError("BAD_NUMBER", "Units must be more than zero.")
        if txn.price is None or (txn.price <= 0 and not txn.is_opening and txn.origin not in NO_PRICE_ORIGINS):
            raise InvestmentsError("BAD_NUMBER", "Price must be more than zero.")
        if txn.allotment_date and txn.allotment_date < txn.date:
            raise InvestmentsError("BAD_DATE", "The allotment date cannot be before the date paid.")
    old_instrument_ids = {Transaction.objects.values_list("instrument_id", flat=True).get(pk=txn.pk), txn.instrument_id}
    if txn.status == STATUS_FINAL:
        for instrument_id in old_instrument_ids:
            add = [core.txn_event(txn)] if instrument_id == txn.instrument_id else []
            _recheck(profile, instrument_id, add=add, exclude_txn=txn.pk, what="This change")
    txn.version += 1
    txn.save()
    history.record(profile, user, txn, "edit", summary=f"Edited {txn.instrument.name}")
    _pin(profile, txn)
    core.touch(profile)
    return txn


@transaction.atomic
def delete_transaction(profile, user, pk, kind="delete"):
    txn = Transaction.objects.select_for_update().filter(pk=pk, profile=profile).first()
    if txn is None:
        raise not_found("transaction")
    if txn.switch_id:
        raise InvestmentsError("LINKED", "This entry is half of a fund switch. Delete the switch instead.", 409)
    if txn.status == STATUS_FINAL:
        _recheck(profile, txn.instrument_id, exclude_txn=txn.pk, what="Deleting this entry")
    history.record(profile, user, txn, kind, summary=f"{'Cancelled' if kind == 'cancel' else 'Deleted'} {txn.instrument.name}")
    txn.delete()
    core.touch(profile)


@transaction.atomic
def delete_switch(profile, user, pk):
    sw = Switch.objects.filter(pk=pk, profile=profile).first()
    if sw is None:
        raise not_found("switch")
    group = new_group()
    legs = list(Transaction.objects.filter(profile=profile, switch=sw))
    instruments = {t.instrument_id for t in legs}
    exclude = {t.pk for t in legs}
    for instrument_id in instruments:
        events = [e for e in core.events_for(profile, instrument_id) if e.ref[0] != "txn" or e.ref[1] not in exclude]
        violations = lots.check_history(events)
        if violations:
            _refuse(violations, "Deleting this switch")
    for leg in legs:
        history.record(profile, user, leg, "delete", group=group, summary=f"Deleted switch leg {leg.instrument.name}")
        leg.switch = None
        leg.delete()
    history.record(profile, user, sw, "delete", group=group, summary="Deleted fund switch")
    sw.delete()
    core.touch(profile)


# ---------------------------------------------------------------- awaiting allotment

def completion_figures(txn, *, units=None, nav=None, charges=None):
    """Work out the third of units, NAV and amount (plan 6). Any two of units, nav and the amount paid give the third.

    Returns ``(units, nav, charges, total, difference)`` where ``total`` is units times NAV plus charges and ``difference``
    is ``total`` less the amount paid.
    """
    amount = txn.amount
    charges = _dec(txn.charges if charges in (None, "") else charges, "Charges", minimum=ZERO)
    units = _dec(units, "Units", allow_none=True, minimum=ZERO)
    nav = _dec(nav, "NAV", allow_none=True, minimum=ZERO)
    if units and nav is None:
        nav = ((amount - charges) / units).quantize(Decimal("0.0001"))
    elif nav and units is None:
        units = ((amount - charges) / nav).quantize(Decimal("0.0001"))
    if not units or not nav:
        raise InvestmentsError("REQUIRED", "Enter at least two of units, NAV and the amount (the amount paid is already known).")
    total = (units * nav + charges)
    return units, nav, charges, total, total - amount


def tolerance_for(amount):
    return max(TOLERANCE_ABS, (amount * TOLERANCE_PCT).quantize(Decimal("0.01")))


@transaction.atomic
def complete_transaction(profile, user, pk, *, allotment_date, units=None, nav=None, charges=None, confirm_difference=False,
                         expected_version=None):
    """Turn an awaiting entry into an ordinary one. The date paid stays; the allotment date is recorded (plan 6)."""
    txn = Transaction.objects.select_for_update().filter(pk=pk, profile=profile).first()
    if txn is None:
        raise not_found("transaction")
    if txn.status != STATUS_AWAITING:
        raise InvestmentsError("NOT_AWAITING", "This entry is not waiting for allotment.", 409)
    _check_clash(txn, expected_version)
    if not isinstance(allotment_date, datetime.date):
        raise InvestmentsError("BAD_DATE", "Enter the allotment date.")
    if allotment_date < txn.date:
        raise InvestmentsError("BAD_DATE", "The allotment date cannot be before the date paid.")
    _check_date(allotment_date)
    units, nav, charges, total, difference = completion_figures(txn, units=units, nav=nav, charges=charges)
    if abs(difference) > tolerance_for(txn.amount) and not confirm_difference:
        raise InvestmentsError(
            "DIFFERENCE", f"Units times NAV plus charges is {total:,.2f}, which differs from the amount paid "
            f"({txn.amount:,.2f}) by {abs(difference):,.2f}. Tick the box to confirm if that is right (for example a partial allotment).",
            409, {"difference": difference, "total": total})
    txn.units, txn.price, txn.charges = units, nav, charges
    txn.allotment_date = allotment_date
    txn.status = STATUS_FINAL
    if txn.side == SIDE_SELL:
        pass
    _recheck(profile, txn.instrument_id, add=[core.txn_event(txn)], exclude_txn=txn.pk,
             what="Completing this redemption" if txn.side == SIDE_SELL else "Completing this purchase")
    txn.amount = None
    txn.version += 1
    txn.save()
    history.record(profile, user, txn, "complete", summary=f"Completed {txn.instrument.name}: {units} units at {nav}")
    core.touch(profile)
    return txn


@transaction.atomic
def cancel_awaiting(profile, user, pk):
    txn = Transaction.objects.filter(pk=pk, profile=profile).first()
    if txn is None:
        raise not_found("transaction")
    if txn.status != STATUS_AWAITING:
        raise InvestmentsError("NOT_AWAITING", "Only an entry waiting for allotment can be cancelled this way.", 409)
    delete_transaction(profile, user, pk, kind="cancel")


@transaction.atomic
def confirm_pending(profile, user, pk, *, units=None, price=None):
    """Confirm a pending SIP entry (optionally correcting its units and price first). Plan 6."""
    txn = Transaction.objects.select_for_update().filter(pk=pk, profile=profile).first()
    if txn is None:
        raise not_found("transaction")
    if txn.status != STATUS_PENDING_SIP:
        raise InvestmentsError("NOT_PENDING", "This entry is not a pending SIP entry.", 409)
    if units is not None:
        txn.units = _dec(units, "Units", minimum=Decimal("0.0001"))
    if price is not None:
        txn.price = _dec(price, "Price", minimum=Decimal("0.0001"))
    txn.status = STATUS_FINAL
    txn.version += 1
    _recheck(profile, txn.instrument_id, add=[core.txn_event(txn)], exclude_txn=txn.pk, what="Confirming this entry")
    txn.save()
    history.record(profile, user, txn, "complete", summary=f"Confirmed SIP entry for {txn.instrument.name}")
    core.touch(profile)
    return txn


def awaiting_for(profile):
    return Transaction.objects.filter(profile=profile, status=STATUS_AWAITING).select_related("instrument", "broker", "portfolio").order_by("date", "id")


def to_complete(profile):
    """Entries on the To complete page: awaiting allotment and pending SIP entries."""
    return Transaction.objects.filter(profile=profile, status__in=[STATUS_AWAITING, STATUS_PENDING_SIP]).select_related(
        "instrument", "broker", "portfolio").order_by("date", "id")


def overdue(txn, days, today=None):
    """True when an awaiting entry has waited longer than the reminder days (plan 6)."""
    today = today or _today()
    return txn.status == STATUS_AWAITING and (today - txn.date).days > days
