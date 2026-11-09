"""Corporate actions (plan 8, 3.7 proposed): recorded once and shared, confirmed per profile, never altering a trade.

A profile's holdings change only after it marks an action "applied". Until then the holding is calculated as before and shows a
Provisional tag and a banner (default), or, with the Settings choice "block", its value, gain and XIRR are n/a and it is left out of the
totals. Marking an action not applicable after it was applied re-checks the history, because a later sale may have used the new units.
"""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from investments import lots
from investments.errors import InvestmentsError, not_found
from investments.models import (
    CA_BONUS, CA_OTHER, CA_SPLIT, CorporateAction, CorporateActionResponse, Instrument, PinnedPrice, ProfileInvestment, Transaction,
)
from investments.services import core, history

STATUS_APPLIED, STATUS_NA, STATUS_PENDING = "applied", "not_applicable", "pending"


def _value(action):
    return action.ratio_new / action.ratio_old


def applied(profile, instrument_ids=None):
    """``{instrument id: [(id, kind, ex_date, value)]}`` of the actions this profile applied (value: split factor or bonus ratio)."""
    qs = CorporateActionResponse.objects.filter(profile=profile, status=STATUS_APPLIED).select_related("action")
    if instrument_ids is not None:
        qs = qs.filter(action__instrument_id__in=list(instrument_ids))
    out = {}
    for r in qs:
        a = r.action
        if a.kind in (CA_SPLIT, CA_BONUS):
            out.setdefault(a.instrument_id, []).append((a.pk, a.kind, a.ex_date, _value(a)))
    return out


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
    if kind in (CA_SPLIT, CA_BONUS) and (old <= 0 or new <= 0):
        raise InvestmentsError("BAD_RATIO", "Both numbers of the ratio must be more than zero.")
    if kind == CA_SPLIT and old == new:
        raise InvestmentsError("BAD_RATIO", "A split changes the number of shares, so the two numbers must differ.")
    return old, new


def adjust_pins(action):
    """A split or bonus on a split-adjusted instrument restates its earlier prices, so earlier pins are divided by the factor (exact, plan 17.2).
    Pins of a raw instrument do not change. Done once per action, whichever profile records it."""
    if action.pins_adjusted or action.kind == CA_OTHER or action.instrument.price_basis != "split_adjusted":
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
def record(profile, user, *, instrument, ex_date, kind, ratio_old=1, ratio_new=1, notes="", detected=False):
    """Record a shared corporate action. The recording profile still has to confirm it (it may record it and apply it at once)."""
    if instrument.profile_id not in (None, profile.pk if profile else None):
        raise not_found("investment")
    if kind not in (CA_SPLIT, CA_BONUS, CA_OTHER):
        raise InvestmentsError("BAD_KIND", "Choose a split, a bonus or other.")
    old, new = _check_ratio(kind, ratio_old, ratio_new)
    existing = CorporateAction.objects.filter(instrument=instrument, ex_date=ex_date, kind=kind).first()
    if existing:
        return existing
    near = CorporateAction.objects.filter(instrument=instrument, kind=kind, ex_date__range=(ex_date - timedelta(days=5), ex_date + timedelta(days=5))).first()
    if near:
        raise InvestmentsError("NEAR_DUPLICATE", f"A {near.get_kind_display().lower()} on {near.ex_date:%-d %b %Y} is already recorded. Confirm that one instead.", 409)
    action = CorporateAction.objects.create(instrument=instrument, ex_date=ex_date, kind=kind, ratio_old=old, ratio_new=new, notes=(notes or "")[:300],
                                            detected=detected, recorded_by=user if getattr(user, "pk", None) else None)
    adjust_pins(action)
    if profile is not None:
        core.touch(profile)
    from investments.services import fetch

    fetch.bump_version()
    return action


def _events_without(profile, instrument_id, skip_action_id):
    events = core.events_for(profile, instrument_id)
    return [e for e in events if e.ref != ("ca", skip_action_id)]


@transaction.atomic
def respond(profile, user, action_id, status):
    """Apply an action to this profile, or mark it not applicable (logged in the edit history; restorable)."""
    if status not in (STATUS_APPLIED, STATUS_NA, STATUS_PENDING):
        raise InvestmentsError("BAD_CHOICE", "Choose applied or not applicable.")
    action = CorporateAction.objects.filter(pk=action_id).select_related("instrument").first()
    if action is None or action.instrument_id not in held_instrument_ids(profile):
        raise not_found("corporate action")
    response, created = CorporateActionResponse.objects.get_or_create(profile=profile, action=action)
    was = response.status
    if status != STATUS_APPLIED and was == STATUS_APPLIED:
        violations = lots.check_history(_events_without(profile, action.instrument_id, action.pk))
        if violations:
            from investments.services.transactions import _refuse

            _refuse(violations, "Taking this action off")
    response.status = status
    response.decided_at = timezone.now()
    response.decided_by = user if getattr(user, "pk", None) else None
    if not created:
        response.version += 1
    response.save()
    history.record(profile, user, response, "edit" if not created else "create", summary=f"{action.describe()} for {action.instrument.name}: {status.replace('_', ' ')}")
    core.touch(profile)
    return response


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
    """All actions on this profile's investments, with this profile's answer."""
    ids = held_instrument_ids(profile)
    answers = dict(CorporateActionResponse.objects.filter(profile=profile).values_list("action_id", "status"))
    rows = []
    for a in CorporateAction.objects.filter(instrument_id__in=ids).select_related("instrument").order_by("-ex_date"):
        a.my_status = answers.get(a.pk, STATUS_PENDING)
        rows.append(a)
    return rows


__all__ = ["record", "respond", "applied", "pending", "pending_instrument_ids", "large_moves_without_action", "for_profile", "Q"]
