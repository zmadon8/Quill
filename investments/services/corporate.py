"""Corporate actions (plan 8, 3.7 proposed): recorded once and shared, confirmed per profile, never altering a trade.

A profile's holdings change only after it marks an action "applied". Until then the holding is calculated as before and shows a
Provisional tag and a banner (default), or, with the Settings choice "block", its value, gain and XIRR are n/a and it is left out of the
totals. Marking an action not applicable after it was applied re-checks the history, because a later sale may have used the new units.

Decided case by case, when the profile applies an action (``CorporateActionResponse``):

* bonus or split, ``method``: ``events`` (the program adds the units itself, the default) or ``transactions`` (the units are
  transactions with origin bonus or split that the person records or imports, or has created for them here). The two never mix for one
  action, because that would count the units twice; applying one way while transactions of the other way exist is refused.
* demerger: the new company's units always come from transactions with origin demerger (they give the units actually received);
  ``inherit_dates`` says whether those shares keep the purchase dates of the parent lots they came from.
"""
from collections import namedtuple
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from django.db import transaction
from django.db.models import Count, Q
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
    ids |= set(Transaction.objects.filter(profile=profile).values_list("instrument_id", flat=True))
    return ids


def pending(profile):
    """Actions on this profile's investments that it has neither applied nor marked not applicable, dated after its first purchase."""
    ids = held_instrument_ids(profile)
    decided = set(CorporateActionResponse.objects.filter(profile=profile).exclude(status=STATUS_PENDING).values_list("action_id", flat=True))
    first = {}
    for iid, day in Transaction.objects.filter(profile=profile, instrument_id__in=ids).values_list("instrument_id", "date"):
        first[iid] = min(first.get(iid, day), day)
    out = []
    for action in CorporateAction.objects.filter(instrument_id__in=ids).exclude(pk__in=decided).select_related("instrument"):
        if action.instrument_id in first and action.ex_date > first[action.instrument_id]:
            out.append(action)
    return out


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


@transaction.atomic
def record(profile, user, *, instrument, ex_date, kind, ratio_old=1, ratio_new=1, notes="", detected=False,
           target_instrument=None, cost_percent_to_target=None):
    """Record a shared corporate action. The recording profile still has to confirm it (it may record it and apply it at once).

    A demerger also names the new company (``target_instrument``) and the part of the parent's cost, in percent, that moves to its shares
    (``cost_percent_to_target``, above 0 and up to 100; the figure comes from the company's notice and is for the person's CA to confirm)."""
    if instrument.profile_id not in (None, profile.pk if profile else None):
        raise not_found("investment")
    if kind not in (CA_SPLIT, CA_BONUS, CA_OTHER, CA_DEMERGER):
        raise InvestmentsError("BAD_KIND", "Choose a split, a bonus, a demerger or other.")
    old, new = _check_ratio(kind, ratio_old, ratio_new)
    percent = None
    if kind == CA_DEMERGER:
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
            raise InvestmentsError("BAD_NUMBER", "Enter the percentage of the cost that moves to the new company (for example 12.5).")
        if not percent.is_finite() or percent <= 0 or percent > 100:
            raise InvestmentsError("BAD_NUMBER", "The percentage of the cost that moves must be more than 0 and at most 100.")
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
    """The free units a bonus or split gives for ``held`` units: whole units for a share, four decimals for a fund; never rounded up."""
    if action.kind == CA_BONUS:
        extra = held * action.ratio_new / action.ratio_old
    else:
        extra = held * (action.ratio_new / action.ratio_old - 1)
    places = Decimal(1) if instrument.kind in ("share", "foreign") else Decimal("0.0001")
    return extra.quantize(places, rounding=ROUND_DOWN)


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


@transaction.atomic
def respond(profile, user, action_id, status, choice=None, inherit_dates=None):
    """Apply an action to this profile, or mark it not applicable (logged in the edit history; restorable).

    The decisions are the profile's, case by case. For a bonus or split ``choice`` is ``auto`` (the program adds the units), ``link``
    (the person records or imports the units as transactions) or ``create`` (the program creates those transactions now). Left out, it
    keeps the current choice, or is ``link`` when units are already recorded against the action, else ``auto``. For a demerger the units
    always come from transactions, and ``inherit_dates`` says whether the new shares keep the parent lots' purchase dates (left out: keep
    the current answer, ``True`` at first)."""
    if status not in (STATUS_APPLIED, STATUS_NA, STATUS_PENDING):
        raise InvestmentsError("BAD_CHOICE", "Choose applied or not applicable.")
    if choice not in (None, CHOICE_AUTO, CHOICE_LINK, CHOICE_CREATE):
        raise InvestmentsError("BAD_CHOICE", "Choose how the units are added.")
    action = CorporateAction.objects.filter(pk=action_id).select_related("instrument", "target_instrument").first()
    if action is None or action.instrument_id not in held_instrument_ids(profile):
        raise not_found("corporate action")
    response, created = CorporateActionResponse.objects.get_or_create(profile=profile, action=action)
    before = (response.status, response.method, response.inherit_dates)
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
    if before != (response.status, response.method, response.inherit_dates):
        # Applying, taking off, or changing how the units are added can leave a later sale without the units it used.
        violations = _violations_after(profile, action)
        if violations:
            from investments.services.transactions import _refuse

            if status != STATUS_APPLIED:
                _refuse(violations, "Taking this action off")
            _refuse(violations, "Switching to your own transactions for these units, before they exist (choose \"Create the transactions for me\" to avoid this),")
    history.record(profile, user, response, "edit" if not created else "create", summary=f"{action.describe()} for {action.instrument.name}: {status.replace('_', ' ')}")
    core.touch(profile)
    return response
    return response


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
        a.my_inherit = r.inherit_dates if r else True
        a.linked_count = linked.get(a.pk, 0)
        # What the "Who adds the units?" list starts on: the person's own transactions when they chose that or already recorded some.
        a.my_choice = CHOICE_LINK if (a.my_method == METHOD_TRANSACTIONS and a.my_status == STATUS_APPLIED) or (a.my_status != STATUS_APPLIED and a.linked_count) else CHOICE_AUTO
        a.gaps = demerger_gaps(profile, a) if a.kind == CA_DEMERGER and a.my_status == STATUS_APPLIED else []
        rows.append(a)
    return rows


__all__ = ["record", "respond", "change_kind", "create_unit_transactions", "applied", "applied_demergers", "demerger_terms", "demerger_gaps",
           "linked_transactions", "method_of", "pending", "pending_instrument_ids", "large_moves_without_action", "for_profile", "Q"]
