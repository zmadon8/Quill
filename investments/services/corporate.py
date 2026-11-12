"""Corporate actions (plan 8, 3.7 proposed): recorded once and shared, confirmed per profile, never altering a trade.

A profile's holdings change only after it marks an action "applied". Until then the holding is calculated as before and shows a
Provisional tag and a banner (default), or, with the Settings choice "block", its value, gain and XIRR are n/a and it is left out of the
totals. Marking an action not applicable after it was applied re-checks the history, because a later sale may have used the new units.

Decided case by case, when the profile applies an action (``CorporateActionResponse``):

* bonus or split, ``method``: ``events`` (the program adds the units itself, the default) or ``transactions`` (the units are
  transactions with origin bonus or split that the person records or imports, or has created for them here). The two never mix for one
  action, because that would count the units twice; applying one way while transactions of the other way exist is refused.
* demerger: the new company's units always come from transactions with origin demerger (they give the units actually received).
  Applying a demerger creates them for the person (zero price, tagged ``auto_created``, one for each portfolio, broker and folio that held
  the parent the day before the ex-date, units from the ratio); editing the demerger replaces the ones still untouched, and a transaction
  the person recorded or edited is never replaced. ``inherit_dates`` (off by default) says whether those shares keep the purchase dates
  of the parent lots they came from.
"""
from collections import namedtuple
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Count, Min, Q
from django.utils import timezone

from investments import lots
from investments.errors import InvestmentsError, not_found
from investments.models import (
    CA_BONUS, CA_DEMERGER, CA_OTHER, CA_SPLIT, HOLDABLE_KINDS, METHOD_EVENTS, METHOD_TRANSACTIONS, ORIGIN_BONUS, ORIGIN_DEMERGER, ORIGIN_SPLIT,
    STATUS_FINAL, Broker, CorporateAction, CorporateActionResponse, Folio, Instrument, PinnedPrice, Portfolio, ProfileInvestment, Transaction,
)
from investments.services import core, history

STATUS_APPLIED, STATUS_NA, STATUS_PENDING = "applied", "not_applicable", "pending"
#: What the person asks for when applying a bonus or split: the program adds the units, they record the units themselves, or the program
#: creates the (editable) transactions for them now.
CHOICE_AUTO, CHOICE_LINK, CHOICE_CREATE = "auto", "link", "create"
ORIGIN_OF_KIND = {CA_BONUS: ORIGIN_BONUS, CA_SPLIT: ORIGIN_SPLIT, CA_DEMERGER: ORIGIN_DEMERGER}
#: The terms of a demerger the profile has applied: the parent, the day it takes effect, the part of the parent's cost that moves, whether the
#: new shares keep the parent lots' purchase dates and the new company.
DemergerTerms = namedtuple("DemergerTerms", "parent_id ex_date fraction inherit_dates target_id")


def _value(action):
    return action.ratio_new / action.ratio_old


def applied(profile, instrument_ids=None, for_units=True):
    """``{instrument id: [(id, kind, ex_date, value)]}`` of the splits and bonuses this profile applied (value: split factor or bonus ratio).

    With ``for_units`` (the default) an action the profile chose to record as transactions is left out, because its units are already
    transactions. ``for_units=False`` lists every applied one, which is what the price-basis factor needs (the vendor restates the prices
    whichever way the units were recorded)."""
    qs = CorporateActionResponse.objects.filter(profile=profile, status=STATUS_APPLIED).select_related("action")
    if instrument_ids is not None:
        qs = qs.filter(action__instrument_id__in=list(instrument_ids))
    out = {}
    for r in qs:
        a = r.action
        if a.kind in (CA_SPLIT, CA_BONUS):
            if for_units and r.method == METHOD_TRANSACTIONS:
                continue
            out.setdefault(a.instrument_id, []).append((a.pk, a.kind, a.ex_date, _value(a)))
    return out


def applied_demergers(profile, instrument_ids=None):
    """``{parent instrument id: [(id, "demerger", ex_date, fraction)]}`` of the demergers this profile applied; the fraction (0 to 1) is
    the part of each parent lot's cost that moves to the new company's shares."""
    qs = CorporateActionResponse.objects.filter(profile=profile, status=STATUS_APPLIED, action__kind=CA_DEMERGER).select_related("action")
    if instrument_ids is not None:
        qs = qs.filter(action__instrument_id__in=list(instrument_ids))
    out = {}
    for r in qs:
        a = r.action
        if a.cost_percent_to_target is not None and a.target_instrument_id:
            out.setdefault(a.instrument_id, []).append((a.pk, a.kind, a.ex_date, Decimal(a.cost_percent_to_target) / 100))
    return out


def demerger_terms(profile, action_ids):
    """``{action id: DemergerTerms}`` for the demergers among ``action_ids`` that this profile has applied."""
    out = {}
    qs = CorporateActionResponse.objects.filter(profile=profile, status=STATUS_APPLIED, action_id__in=list(action_ids), action__kind=CA_DEMERGER)
    for r in qs.select_related("action"):
        a = r.action
        if a.cost_percent_to_target is not None and a.target_instrument_id:
            out[a.pk] = DemergerTerms(a.instrument_id, a.ex_date, Decimal(a.cost_percent_to_target) / 100, r.inherit_dates, a.target_instrument_id)
    return out


def linked_transactions(profile, action):
    """This profile's final transactions that belong to ``action`` (bonus or split units, or shares received on a demerger)."""
    return Transaction.objects.filter(profile=profile, corporate_action=action, status=STATUS_FINAL)


def method_of(profile, action):
    """How this profile's units for ``action`` are added: ``events`` (the default, also while it has not applied it) or ``transactions``."""
    response = CorporateActionResponse.objects.filter(profile=profile, action=action).first()
    return response.method if response is not None and response.status == STATUS_APPLIED else METHOD_EVENTS


def held_instrument_ids(profile):
    ids = set(ProfileInvestment.objects.filter(profile=profile).values_list("instrument_id", flat=True))
    ids |= set(Transaction.objects.filter(profile=profile).order_by().values_list("instrument_id", flat=True).distinct())
    return ids


def pending(profile):
    """Actions on this profile's investments that it has neither applied nor marked not applicable, dated after its first purchase."""
    ids = held_instrument_ids(profile)
    decided = set(CorporateActionResponse.objects.filter(profile=profile).exclude(status=STATUS_PENDING).values_list("action_id", flat=True))
    actions = list(CorporateAction.objects.filter(instrument_id__in=ids).exclude(pk__in=decided).select_related("instrument"))
    if not actions:        # the usual case: nothing to look up (and this runs with every calculation of the holdings)
        return []
    # The first purchase of just the investments that have an action: one row each, not every transaction.
    first = dict(Transaction.objects.filter(profile=profile, instrument_id__in={a.instrument_id for a in actions}).order_by()
                 .values_list("instrument_id").annotate(first=Min("date")))
    return [a for a in actions if a.instrument_id in first and a.ex_date > first[a.instrument_id]]


def pending_instrument_ids(profile):
    return {a.instrument_id for a in pending(profile)}


def _check_ratio(kind, old, new):
    old, new = Decimal(str(old)), Decimal(str(new))
    if kind in (CA_SPLIT, CA_BONUS, CA_DEMERGER) and (old <= 0 or new <= 0):
        raise InvestmentsError("BAD_RATIO", "Both numbers of the ratio must be more than zero.")
    if kind == CA_SPLIT and old == new:
        raise InvestmentsError("BAD_RATIO", "A split changes the number of shares, so the two numbers must differ.")
    return old, new


def adjust_pins(action):
    """A split or bonus on a split-adjusted instrument restates its earlier prices, so earlier pins are divided by the factor (exact, plan 17.2).
    Pins of a raw instrument do not change. Done once per action, whichever profile records it."""
    if action.pins_adjusted or action.kind in (CA_OTHER, CA_DEMERGER) or action.instrument.price_basis != "split_adjusted":
        return 0
    factor = action.factor
    n = 0
    for pin in PinnedPrice.objects.filter(instrument=action.instrument, asked_date__lt=action.ex_date):
        pin.close = (pin.close / factor).quantize(Decimal("0.0001"))
        pin.save(update_fields=["close"])
        n += 1
    CorporateAction.objects.filter(pk=action.pk).update(pins_adjusted=True)
    action.pins_adjusted = True
    return n


def _check_demerger(profile, instrument, target_instrument, cost_percent_to_target):
    """The checks on a demerger's new company and cost split; returns the percentage as a Decimal (0 to 100: 0 leaves all the cost with the
    parent's shares, 100 moves all of it)."""
    if target_instrument is None:
        raise InvestmentsError("REQUIRED", "Choose the new company whose shares are received. Add it under Investments first if it is not there yet.")
    if target_instrument.pk == instrument.pk:
        raise InvestmentsError("BAD_TARGET", "The new company must be a different investment from the one demerged.")
    if target_instrument.profile_id not in (None, profile.pk if profile else None):
        raise not_found("investment")
    if target_instrument.kind not in HOLDABLE_KINDS:
        raise InvestmentsError("NOT_HOLDABLE", "An index cannot be received. Choose a share or fund.")
    try:
        percent = Decimal(str(cost_percent_to_target))
    except Exception:
        raise InvestmentsError("BAD_NUMBER", "Enter the percentage of the cost that moves to the new company (for example 12.5, or 0 to keep all of it with the old shares).")
    if not percent.is_finite() or percent < 0 or percent > 100:
        raise InvestmentsError("BAD_NUMBER", "The percentage of the cost that moves must be between 0 and 100.")
    return percent


@transaction.atomic
def record(profile, user, *, instrument, ex_date, kind, ratio_old=1, ratio_new=1, notes="", detected=False,
           target_instrument=None, cost_percent_to_target=None):
    """Record a shared corporate action. The recording profile still has to confirm it (it may record it and apply it at once).

    A demerger also names the new company (``target_instrument``) and the part of the parent's cost, in percent, that moves to its shares
    (``cost_percent_to_target``, from 0 to 100; the figure comes from the company's notice and is for the person's CA to confirm)."""
    if instrument.profile_id not in (None, profile.pk if profile else None):
        raise not_found("investment")
    if kind not in (CA_SPLIT, CA_BONUS, CA_OTHER, CA_DEMERGER):
        raise InvestmentsError("BAD_KIND", "Choose a split, a bonus, a demerger or other.")
    old, new = _check_ratio(kind, ratio_old, ratio_new)
    percent = None
    if kind == CA_DEMERGER:
        percent = _check_demerger(profile, instrument, target_instrument, cost_percent_to_target)
    else:
        target_instrument = None
    existing = CorporateAction.objects.filter(instrument=instrument, ex_date=ex_date, kind=kind).first()
    if existing:
        if kind == CA_DEMERGER and (existing.target_instrument_id != target_instrument.pk or existing.cost_percent_to_target != percent):
            raise InvestmentsError("NEAR_DUPLICATE", f"A demerger on {existing.ex_date:%-d %b %Y} is already recorded with other terms. Confirm that one instead.", 409)
        return existing
    near = CorporateAction.objects.filter(instrument=instrument, kind=kind, ex_date__range=(ex_date - timedelta(days=5), ex_date + timedelta(days=5))).first()
    if near:
        raise InvestmentsError("NEAR_DUPLICATE", f"A {near.get_kind_display().lower()} on {near.ex_date:%-d %b %Y} is already recorded. Confirm that one instead.", 409)
    action = CorporateAction.objects.create(instrument=instrument, ex_date=ex_date, kind=kind, ratio_old=old, ratio_new=new, notes=(notes or "")[:300],
                                            detected=detected, recorded_by=user if getattr(user, "pk", None) else None,
                                            target_instrument=target_instrument, cost_percent_to_target=percent)
    adjust_pins(action)
    if profile is not None:
        core.touch(profile)
    from investments.services import fetch

    fetch.bump_version()
    apply_automatic_for_action(action)
    return action


def change_kind(profile, user, action_id, kind):
    """Turn a detected "split" into the bonus it really was (a price source reports an Indian bonus issue as a split), before it is applied.
    The ratio stays: a source's 2-for-1 split becomes a bonus of 1 free for every 1 held, so the two ratio numbers are re-read."""
    action = CorporateAction.objects.filter(pk=action_id).select_related("instrument").first()
    if action is None or action.instrument_id not in held_instrument_ids(profile):
        raise not_found("corporate action")
    if {action.kind, kind} != {CA_SPLIT, CA_BONUS}:
        raise InvestmentsError("BAD_KIND", "Only a split can be changed to a bonus, or a bonus to a split.")
    if CorporateActionResponse.objects.filter(action=action).exclude(status=STATUS_PENDING).exists() or Transaction.objects.filter(corporate_action=action).exists():
        raise InvestmentsError("IN_USE", "Someone has already applied this action or recorded units against it, so its kind cannot be changed. Record a new action instead.", 409)
    if CorporateAction.objects.filter(instrument=action.instrument, ex_date=action.ex_date, kind=kind).exists():
        raise InvestmentsError("NEAR_DUPLICATE", f"A {kind} on {action.ex_date:%-d %b %Y} is already recorded.", 409)
    if kind == CA_BONUS:
        # split "old becomes new" is a bonus of (new - old) free for every old held
        free = action.ratio_new - action.ratio_old
        if free <= 0:
            raise InvestmentsError("BAD_RATIO", "A split that reduces the number of shares cannot be a bonus.")
        action.ratio_new = free
    else:
        action.ratio_new = action.ratio_old + action.ratio_new
    action.kind = kind
    action.save(update_fields=["kind", "ratio_new"])
    core.touch(profile)
    return action


def _violations_after(profile, action):
    """The selling-limit problems in the history of the investments this action touches, as the history now stands."""
    found = []
    for instrument_id in {action.instrument_id, action.target_instrument_id} - {None}:
        found += lots.check_history(core.events_for(profile, instrument_id))
    return found


def _bucket_units_before(profile, action):
    """``{Bucket: units}`` held in the action's investment at the end of the day before its ex-date, as the history now stands."""
    events = core.events_for(profile, action.instrument_id)
    return lots.available_by_bucket(events, action.ex_date - timedelta(days=1))


def _units_to_add(action, held, instrument):
    """The free units a bonus or split gives, or the shares a demerger gives in the new company, for ``held`` units: whole units for a share, four decimals for a fund; never rounded up."""
    if action.kind in (CA_BONUS, CA_DEMERGER):
        extra = held * action.ratio_new / action.ratio_old
    else:
        extra = held * (action.ratio_new / action.ratio_old - 1)
    places = Decimal(1) if instrument.kind in ("share", "foreign") else Decimal("0.0001")
    return extra.quantize(places, rounding=ROUND_DOWN)


AUTO_LABELS = {CA_SPLIT: "Split (added automatically)", CA_BONUS: "Bonus shares (added automatically)"}


def automatic_unit_rows(profile, portfolio=None, broker=None, asat=None, q=""):
    """Read-only display rows for the units the program adds itself (a bonus or split applied with the method ``events``), newest first.

    These units are not transactions (making them real would count them twice), so the Transactions page shows them as extra rows: one for
    each portfolio, broker and folio that held the investment the day before the ex-date, with the units added, a price of 0 and a label.
    A bonus or split the profile records as transactions is not listed here, because its transactions are listed with their own origin.
    Each row is a dict: ``date``, ``instrument``, ``action``, ``label``, ``units``, ``portfolio``, ``broker``, ``folio`` (names) and ``kind``."""
    out = []
    responses = CorporateActionResponse.objects.filter(profile=profile, status=STATUS_APPLIED, method=METHOD_EVENTS,
                                                       action__kind__in=(CA_SPLIT, CA_BONUS)).select_related("action", "action__instrument")
    if asat:
        responses = responses.filter(action__ex_date__lte=asat)
    if q:
        responses = responses.filter(Q(action__instrument__name__icontains=q) | Q(action__instrument__code__icontains=q))
    responses = list(responses)
    if not responses:
        return out
    names_p = dict(Portfolio.objects.filter(profile=profile).values_list("pk", "name"))
    names_b = dict(Broker.objects.filter(profile=profile).values_list("pk", "name"))
    for r in responses:
        action = r.action
        folios = {}
        for bucket, held in _bucket_units_before(profile, action).items():
            if held <= 0 or (portfolio and bucket.portfolio != int(portfolio)) or (broker and bucket.broker != int(broker)):
                continue
            units = _units_to_add(action, held, action.instrument)
            if units <= 0:
                continue
            if bucket.folio and bucket.folio not in folios:
                folios[bucket.folio] = Folio.objects.filter(pk=bucket.folio).values_list("number", flat=True).first() or ""
            out.append({"date": action.ex_date, "instrument": action.instrument, "action": action, "kind": action.kind,
                        "label": AUTO_LABELS[action.kind], "units": units, "portfolio": names_p.get(bucket.portfolio, ""),
                        "broker": names_b.get(bucket.broker, ""), "folio": folios.get(bucket.folio, "") if bucket.folio else ""})
    out.sort(key=lambda row: (row["date"], row["action"].pk), reverse=True)
    return out


def create_unit_transactions(profile, user, action):
    """Create the zero-cost transactions (origin bonus or split) for a bonus or split this profile records as transactions: one for each
    portfolio, broker and folio that held units the day before the ex-date, dated the ex-date, linked to the action. They are ordinary
    rows the person can edit (for example to put in the real allotment date or the units the statement shows). A bucket that already has a
    linked transaction is left alone, so pressing it twice creates nothing twice. Returns the transactions created."""
    from investments.services import transactions as tx

    if action.kind not in (CA_BONUS, CA_SPLIT):
        raise InvestmentsError("BAD_KIND", "Only a bonus or a split can have its transactions created.")
    if action.kind == CA_SPLIT and action.ratio_new <= action.ratio_old:
        raise InvestmentsError("BAD_RATIO", "A split that reduces the number of shares cannot be recorded as transactions. Choose Automatic.")
    existing = {(t.portfolio_id, t.broker_id, t.folio_id) for t in linked_transactions(profile, action)}
    made = []
    for bucket, held in _bucket_units_before(profile, action).items():
        if held <= 0 or (bucket.portfolio, bucket.broker, bucket.folio) in existing:
            continue
        units = _units_to_add(action, held, action.instrument)
        if units <= 0:
            continue
        folio = Folio.objects.filter(pk=bucket.folio).first() if bucket.folio else None
        made.append(tx.add_transaction(
            profile, user, side="buy", instrument=action.instrument, portfolio=Portfolio.objects.get(pk=bucket.portfolio),
            broker=Broker.objects.get(pk=bucket.broker), folio=folio, date=action.ex_date, units=units, price=0,
            origin=ORIGIN_OF_KIND[action.kind], corporate_action=action, reference=f"From the {action.kind} of {action.ex_date:%-d %b %Y}",
            note="Created from the corporate action; check the units against your statement"))
    return made


def remove_demerger_allotments(profile, user, action):
    """Take away the entries the program made for a demerger that is no longer applied. Returns whether any were removed."""
    found = list(linked_transactions(profile, action).filter(auto_created=True))
    for t in found:
        history.record(profile, user, t, "delete", summary=f"Removed {t.instrument.name} received on a demerger")
        t.delete()
    return bool(found)


def _places(instrument):
    return Decimal(1) if instrument.kind in ("share", "foreign") else Decimal("0.0001")


def _bucket_key(bucket):
    return f"{bucket.portfolio}:{bucket.broker}:{bucket.folio or 0}"


def _overrides(profile, action):
    response = CorporateActionResponse.objects.filter(profile=profile, action=action).only("units_override").first()
    return dict(response.units_override or {}) if response else {}


def _override_units(text, instrument):
    """The units an override string stands for, or None when it is not a valid whole or four-decimal, non-negative number."""
    try:
        value = Decimal(str(text).strip())
        if not value.is_finite() or value < 0 or value != value.quantize(_places(instrument), rounding=ROUND_DOWN):
            return None
        return value.quantize(_places(instrument))
    except (InvalidOperation, ValueError):   # too many digits to quantize (for example 1e30)
        return None


def bucket_allotments(profile, action):
    """The rows of the edit page for a demerger: one per portfolio, broker and folio that held the parent the day before the ex-date.

    Each row has ``key``, the names, ``held``, ``default`` (from the ratio), ``override`` (the text the person entered, or ``""``), ``units``
    (what the program enters: the override when there is one, else the default) and ``own`` (the person recorded shares there themselves,
    so the program makes no entry and an override does nothing)."""
    target = action.target_instrument
    if action.kind != CA_DEMERGER or target is None:
        return []
    overrides = _overrides(profile, action)
    own = {(t.portfolio_id, t.broker_id) for t in linked_transactions(profile, action).filter(auto_created=False)}
    held_by = {b: h for b, h in _bucket_units_before(profile, action).items() if h > 0}
    portfolios = dict(Portfolio.objects.filter(pk__in={b.portfolio for b in held_by}).values_list("pk", "name"))
    brokers = dict(Broker.objects.filter(pk__in={b.broker for b in held_by}).values_list("pk", "name"))
    folios = dict(Folio.objects.filter(pk__in={b.folio for b in held_by if b.folio}).values_list("pk", "name")) if any(b.folio for b in held_by) else {}
    rows = []
    for bucket, held in held_by.items():
        key = _bucket_key(bucket)
        default = _units_to_add(action, held, target)
        override = overrides.get(key, "")
        value = _override_units(override, target) if override != "" else None
        rows.append({"key": key, "field": "units_" + key.replace(":", "_"), "portfolio": portfolios.get(bucket.portfolio, ""), "broker": brokers.get(bucket.broker, ""),
                     "folio": folios.get(bucket.folio, "") if bucket.folio else "", "held": held, "default": default,
                     "override": override, "units": default if value is None else value, "own": (bucket.portfolio, bucket.broker) in own})
    rows.sort(key=lambda r: (r["portfolio"], r["broker"], r["folio"]))
    return rows


def sync_demerger_allotments(profile, user, action):
    """Make the new company's shares for an applied demerger match its ratio: one zero-price entry (origin demerger, tagged ``auto_created``)
    for each portfolio, broker and folio that held the parent the day before the ex-date, dated the ex-date, units from the ratio (whole
    shares for a share, four decimals for a fund; never rounded up). Where the person entered the units they were allotted
    (``CorporateActionResponse.units_override``) those are used instead; 0 means no entry. An override for a bucket that held nothing that
    day is ignored but kept.

    Safe to run again after the demerger is edited: an entry the program made that still matches is kept, one that no longer matches is
    removed and made again, so nothing is counted twice. An entry the person recorded or edited themselves is never touched, and its
    portfolio and broker (any folio) get no automatic one. Returns whether anything was removed or created."""
    from investments.services import transactions as tx

    target = action.target_instrument
    changed = False
    wanted = {}
    if action.kind == CA_DEMERGER and target is not None:
        overrides = _overrides(profile, action)
        for bucket, held in _bucket_units_before(profile, action).items():
            if held <= 0:
                continue
            units = _units_to_add(action, held, target)
            given = overrides.get(_bucket_key(bucket), "")
            if given != "":
                value = _override_units(given, target)
                if value is not None:
                    units = value
            if units > 0:
                wanted[(bucket.portfolio, bucket.broker, bucket.folio)] = units
    own = set()
    kept = set()
    for t in linked_transactions(profile, action).order_by("id"):
        key = (t.portfolio_id, t.broker_id, t.folio_id)
        if not t.auto_created:
            own.add(key[:2])   # a hand entry may be one combined receipt or under another folio: it covers the whole portfolio and broker
        elif key in wanted and key not in kept and t.units == wanted[key] and t.date == action.ex_date and t.instrument_id == action.target_instrument_id:
            kept.add(key)
        else:
            history.record(profile, user, t, "delete", summary=f"Replaced {t.instrument.name} received on a demerger")
            t.delete()
            changed = True
    for key, units in wanted.items():
        if key[:2] in own or key in kept:
            continue
        portfolio_id, broker_id, folio_id = key
        tx.add_transaction(
            profile, user, side="buy", instrument=target, portfolio=Portfolio.objects.get(pk=portfolio_id), broker=Broker.objects.get(pk=broker_id),
            folio=Folio.objects.filter(pk=folio_id).first() if folio_id else None, date=action.ex_date, units=units, price=0,
            origin=ORIGIN_DEMERGER, corporate_action=action, auto_created=True, reference=f"From the demerger of {action.ex_date:%-d %b %Y}",
            note="Created from the corporate action; check the units against your statement")
        changed = True
    return changed


@transaction.atomic
def set_units_overrides(profile, user, action_id, overrides):
    """Save the units the person was allotted in the demerged company, bucket by bucket. ``overrides`` maps ``"portfolio:broker:folio"``
    (folio 0 for none) to a text: blank removes the override, else it must be a non-negative number (whole for a share, up to four decimals
    for a fund) for a bucket that held the parent the day before the ex-date. Keys not given are left as they are. The program's entries
    are made again when the demerger is applied. Returns whether anything changed."""
    action = CorporateAction.objects.filter(pk=action_id).select_related("instrument", "target_instrument").first()
    if action is None or action.instrument_id not in held_instrument_ids(profile):
        raise not_found("corporate action")
    if action.kind != CA_DEMERGER or action.target_instrument_id is None:
        raise InvestmentsError("BAD_KIND", "Only a demerger with a new company has units to override.")
    valid = {r["key"] for r in bucket_allotments(profile, action)}
    response, _created = CorporateActionResponse.objects.get_or_create(profile=profile, action=action)
    stored = dict(response.units_override or {})
    for key, text in overrides.items():
        text = (text or "").strip()
        if text == "":
            stored.pop(key, None)
            continue
        if key not in valid:
            raise InvestmentsError("BAD_BUCKET", "That portfolio, broker and folio held none of this investment the day before the ex-date.")
        value = _override_units(text, action.target_instrument)
        if value is None:
            places = "a whole number" if _places(action.target_instrument) == 1 else "a number with up to four decimals"
            raise InvestmentsError("BAD_UNITS", f"Enter the units allotted as {places}, 0 or more, or leave it blank to use the calculated units.")
        stored[key] = format(value, "f")
    if stored == (response.units_override or {}):
        return False
    response.units_override = stored
    response.version += 1
    response.save(update_fields=["units_override", "version"])
    if response.status == STATUS_APPLIED:
        sync_demerger_allotments(profile, user, action)
        violations = _violations_after(profile, action)
        if violations:
            from investments.services.transactions import _refuse

            _refuse(violations, "Changing the units allotted")
    history.record(profile, user, response, "edit", summary=f"Set the units allotted on the demerger of {action.instrument.name}")
    from investments.services import fetch

    fetch.bump_version()
    core.touch(profile)
    return True


@transaction.atomic
def update(profile, user, action_id, *, ex_date, ratio_old=1, ratio_new=1, notes="", target_instrument=None, cost_percent_to_target=None):
    """Edit a recorded action (its date, ratio, notes and, for a demerger, the new company and the cost split), also after it was applied.

    The investment and the kind stay. Everyone's answers are kept: this profile's applied demerger gets its automatic entries made again
    from the new terms (see ``sync_demerger_allotments``) and the lots are derived afresh from the history, so nothing is counted twice.
    Refused when another profile has already answered it or recorded units against it, because the change would alter their figures."""
    action = CorporateAction.objects.filter(pk=action_id).select_related("instrument", "target_instrument").first()
    if action is None or action.instrument_id not in held_instrument_ids(profile):
        raise not_found("corporate action")
    if CorporateActionResponse.objects.filter(action=action).exclude(profile=profile).exclude(status=STATUS_PENDING).exists() \
            or Transaction.objects.filter(corporate_action=action).exclude(profile=profile).exists():
        raise InvestmentsError("IN_USE", "Another profile has already applied this action or recorded units against it, so it cannot be changed here.", 409)
    old, new = _check_ratio(action.kind, ratio_old, ratio_new)
    percent = None
    if action.kind == CA_DEMERGER:
        percent = _check_demerger(profile, action.instrument, target_instrument, cost_percent_to_target)
        if target_instrument.pk != action.target_instrument_id and linked_transactions(profile, action).filter(auto_created=False).exists():
            raise InvestmentsError("IN_USE", "You have recorded shares of the current new company against this demerger. Delete or change those first, "
                                             "then change the company.", 409)
    else:
        target_instrument = None
    if action.kind in (CA_SPLIT, CA_BONUS) and action.pins_adjusted and (old, new, ex_date) != (action.ratio_old, action.ratio_new, action.ex_date):
        raise InvestmentsError("IN_USE", "The earlier prices of this investment were already restated for this action, so its date and ratio cannot be changed. "
                                         "Record the right action instead.", 409)
    others = CorporateAction.objects.filter(instrument=action.instrument, kind=action.kind).exclude(pk=action.pk)
    if others.filter(ex_date=ex_date).exists():
        raise InvestmentsError("NEAR_DUPLICATE", f"A {action.get_kind_display().lower()} on {ex_date:%-d %b %Y} is already recorded.", 409)
    near = others.filter(ex_date__range=(ex_date - timedelta(days=5), ex_date + timedelta(days=5))).first()
    if near:
        raise InvestmentsError("NEAR_DUPLICATE", f"A {near.get_kind_display().lower()} on {near.ex_date:%-d %b %Y} is already recorded. Confirm that one instead.", 409)
    action.ex_date, action.ratio_old, action.ratio_new, action.notes = ex_date, old, new, (notes or "")[:300]
    action.target_instrument, action.cost_percent_to_target = target_instrument, percent
    action.save(update_fields=["ex_date", "ratio_old", "ratio_new", "notes", "target_instrument", "cost_percent_to_target"])
    response = CorporateActionResponse.objects.filter(profile=profile, action=action).first()
    applied_here = response is not None and response.status == STATUS_APPLIED
    if applied_here:
        if action.kind == CA_DEMERGER:
            sync_demerger_allotments(profile, user, action)
        response.version += 1
        response.save(update_fields=["version"])
        violations = _violations_after(profile, action)
        if violations:
            from investments.services.transactions import _refuse

            _refuse(violations, "Changing this action")
        history.record(profile, user, response, "edit", summary=f"Edited {action.describe()} for {action.instrument.name}")
    from investments.services import fetch

    fetch.bump_version()
    core.touch(profile)
    return action


@transaction.atomic
def respond(profile, user, action_id, status, choice=None, inherit_dates=None):
    """Apply an action to this profile, or mark it not applicable (logged in the edit history; restorable).

    The decisions are the profile's, case by case. For a bonus or split ``choice`` is ``auto`` (the program adds the units), ``link``
    (the person records or imports the units as transactions) or ``create`` (the program creates those transactions now). Left out, it
    keeps the current choice, or is ``link`` when units are already recorded against the action, else ``auto``. For a demerger the units
    always come from transactions, and ``inherit_dates`` says whether the new shares keep the parent lots' purchase dates (left out: keep
    the current answer, ``False`` at first)."""
    if status not in (STATUS_APPLIED, STATUS_NA, STATUS_PENDING):
        raise InvestmentsError("BAD_CHOICE", "Choose applied or not applicable.")
    if choice not in (None, CHOICE_AUTO, CHOICE_LINK, CHOICE_CREATE):
        raise InvestmentsError("BAD_CHOICE", "Choose how the units are added.")
    action = CorporateAction.objects.filter(pk=action_id).select_related("instrument", "target_instrument").first()
    if action is None or action.instrument_id not in held_instrument_ids(profile):
        raise not_found("corporate action")
    response, created = CorporateActionResponse.objects.get_or_create(profile=profile, action=action)
    before = (response.status, response.method, response.inherit_dates)
    allotments_changed = False
    linked = linked_transactions(profile, action).exists()
    if status == STATUS_APPLIED:
        if action.kind == CA_DEMERGER:
            if action.target_instrument_id is None or action.cost_percent_to_target is None:
                raise InvestmentsError("INCOMPLETE", "This demerger has no new company or cost percentage recorded, so it cannot be applied.")
            response.method = METHOD_TRANSACTIONS
            if inherit_dates is not None:
                response.inherit_dates = bool(inherit_dates)
        elif action.kind in (CA_SPLIT, CA_BONUS):
            if choice is None:
                choice = CHOICE_LINK if (linked or (not created and response.status == STATUS_APPLIED and response.method == METHOD_TRANSACTIONS)) else CHOICE_AUTO
            if choice == CHOICE_AUTO and linked:
                raise InvestmentsError(
                    "DOUBLE_COUNT", "Units for this action are already recorded as transactions, so the program cannot also add them itself: they would be "
                    "counted twice. Choose \"I record the units as transactions\", or delete those transactions first.", 409)
            response.method = METHOD_EVENTS if choice == CHOICE_AUTO else METHOD_TRANSACTIONS
    response.status = status
    response.decided_at = timezone.now()
    response.decided_by = user if getattr(user, "pk", None) else None
    if not created:
        response.version += 1
    response.save()
    if status == STATUS_APPLIED and choice == CHOICE_CREATE and action.kind in (CA_SPLIT, CA_BONUS):
        # First the transactions that stand in for the units the program would have added, then the check below sees them.
        create_unit_transactions(profile, user, action)
    if action.kind == CA_DEMERGER:
        # The new company's shares exist only while the demerger is applied; the ones the program made follow the terms.
        allotments_changed = sync_demerger_allotments(profile, user, action) if status == STATUS_APPLIED else remove_demerger_allotments(profile, user, action)
    if allotments_changed or before != (response.status, response.method, response.inherit_dates):
        # Applying, taking off, or changing how the units are added can leave a later sale without the units it used.
        violations = _violations_after(profile, action)
        if violations:
            from investments.services.transactions import _refuse

            if status != STATUS_APPLIED:
                _refuse(violations, "Taking this action off")
            if action.kind == CA_DEMERGER:
                _refuse(violations, "Applying this demerger")
            _refuse(violations, "Switching to your own transactions for these units, before they exist (choose \"Create the transactions for me\" to avoid this),")
    history.record(profile, user, response, "edit" if not created else "create", summary=f"{action.describe()} for {action.instrument.name}: {status.replace('_', ' ')}")
    core.touch(profile)
    return response


def auto_apply(profile, kind):
    """Whether this profile has chosen to have actions of ``kind`` (``dividend``, ``split``, ``bonus``, ``demerger`` or ``other``) logged
    automatically instead of waiting for its approval. Off unless switched on, which is how it worked before the choice existed."""
    return bool((core.get_settings(profile, create=False).corporate_auto or {}).get(kind))


def apply_automatic(profile, instrument_ids=None):
    """Apply the pending actions of the kinds this profile logs automatically (splits and bonuses with the program adding the units).
    A demerger that is missing its new company or cost percentage stays pending, and so does anything that would leave a later sale
    without its units. Returns the actions applied."""
    done = []
    if not any((core.get_settings(profile, create=False).corporate_auto or {}).values()):
        return done
    for action in pending(profile):
        if instrument_ids is not None and action.instrument_id not in instrument_ids:
            continue
        if not auto_apply(profile, action.kind):
            continue
        if action.kind == CA_DEMERGER and (action.target_instrument_id is None or action.cost_percent_to_target is None):
            continue
        try:
            respond(profile, None, action.pk, STATUS_APPLIED, choice=CHOICE_AUTO if action.kind in (CA_SPLIT, CA_BONUS) else None)
        except InvestmentsError:
            continue
        done.append(action)
    return done


def apply_automatic_for_action(action):
    """After an action is recorded: apply it for every profile that holds the investment and logs this kind automatically."""
    from investments.models import InvestmentSettings

    profile_ids = set(ProfileInvestment.objects.filter(instrument_id=action.instrument_id).values_list("profile_id", flat=True))
    profile_ids |= set(Transaction.objects.filter(instrument_id=action.instrument_id).order_by().values_list("profile_id", flat=True).distinct())
    from accounts.models import Profile

    on = {row.profile_id for row in InvestmentSettings.objects.filter(profile_id__in=profile_ids) if (row.corporate_auto or {}).get(action.kind)}
    for profile in Profile.objects.filter(pk__in=on):
        apply_automatic(profile, {action.instrument_id})


def demerger_gaps(profile, action):
    """Where cost left the parent but no shares of the new company are recorded yet: ``[(portfolio name, broker name)]`` of every portfolio and
    broker that held the parent the day before the ex-date and has no transaction for the shares received. Empty for anything but an applied
    demerger. Used to warn the person, because that cost would otherwise vanish from the figures."""
    if action.kind != CA_DEMERGER or not CorporateActionResponse.objects.filter(profile=profile, action=action, status=STATUS_APPLIED).exists():
        return []
    held = {(b.portfolio, b.broker) for b, units in _bucket_units_before(profile, action).items() if units > 0}
    got = set(linked_transactions(profile, action).values_list("portfolio_id", "broker_id"))
    names_p = dict(Portfolio.objects.filter(profile=profile).values_list("pk", "name"))
    names_b = dict(Broker.objects.filter(profile=profile).values_list("pk", "name"))
    return sorted((names_p.get(p, "?"), names_b.get(b, "?")) for p, b in held - got)


def large_moves_without_action(profile, threshold=Decimal("0.35"), days=400):
    """Second safety net (plan 8): one-day falls of more than ``threshold`` on held investments with no action recorded near that date."""
    from investments.models import Price

    out = []
    since = timezone.localdate() - timedelta(days=days)
    for inst in Instrument.objects.filter(pk__in=held_instrument_ids(profile)).exclude(kind="alternative"):
        rows = list(Price.objects.filter(instrument=inst, date__gte=since).order_by("date").values_list("date", "close"))
        for (d0, c0), (d1, c1) in zip(rows, rows[1:]):
            if c0 and (c0 - c1) / c0 > threshold:
                if not CorporateAction.objects.filter(instrument=inst, ex_date__range=(d1 - timedelta(days=5), d1 + timedelta(days=5))).exists():
                    out.append((inst, d1, c0, c1))
    return out


def for_profile(profile):
    """All actions on this profile's investments, with this profile's answer: ``my_status``, ``my_method`` (bonus and split: ``events`` or
    ``transactions``), ``my_inherit`` (demerger), ``linked_count`` (its transactions) and, for an applied demerger, ``gaps`` (portfolios and
    brokers whose parent shares have no matching shares of the new company recorded)."""
    ids = held_instrument_ids(profile)
    answers = {r.action_id: r for r in CorporateActionResponse.objects.filter(profile=profile)}
    linked = dict(Transaction.objects.filter(profile=profile, status=STATUS_FINAL, corporate_action__isnull=False)
                  .values_list("corporate_action_id").annotate(n=Count("id")))
    rows = []
    for a in CorporateAction.objects.filter(instrument_id__in=ids).select_related("instrument", "target_instrument").order_by("-ex_date"):
        r = answers.get(a.pk)
        a.my_status = r.status if r else STATUS_PENDING
        a.my_method = r.method if r else METHOD_EVENTS
        a.my_inherit = r.inherit_dates if r else False
        a.linked_count = linked.get(a.pk, 0)
        # What the "Who adds the units?" list starts on: the person's own transactions when they chose that or already recorded some.
        a.my_choice = CHOICE_LINK if (a.my_method == METHOD_TRANSACTIONS and a.my_status == STATUS_APPLIED) or (a.my_status != STATUS_APPLIED and a.linked_count) else CHOICE_AUTO
        a.gaps = demerger_gaps(profile, a) if a.kind == CA_DEMERGER and a.my_status == STATUS_APPLIED else []
        rows.append(a)
    return rows


__all__ = ["record", "update", "respond", "sync_demerger_allotments", "set_units_overrides", "bucket_allotments", "remove_demerger_allotments", "auto_apply", "apply_automatic", "apply_automatic_for_action", "change_kind", "create_unit_transactions", "applied", "applied_demergers", "demerger_terms", "demerger_gaps",
           "linked_transactions", "method_of", "pending", "pending_instrument_ids", "large_moves_without_action", "for_profile", "Q"]
