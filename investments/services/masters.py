"""Portfolios, brokers, folios, investments (instruments), per-profile investment details and settings (plan sections 4, 6, 10, 23)."""
import re

from django.db import transaction
from django.db.models import Q

from investments.errors import InvestmentsError, forbidden, not_found
from investments.models import (
    HOLDABLE_KINDS, KIND_ALTERNATIVE, KIND_INDEX, AltValue, Broker, Folio, Instrument,
    InvestmentsUserPrefs, Portfolio, ProfileInvestment, Transaction, Transfer,
)
from investments.services import core, history
from investments.services import fetch_defaults

BUILTIN_INDICES = [
    # Owner round (2026-11): Nifty 50 is the only built-in index; any other is added in Settings > Indices (migration 0016).
    ("Nifty 50", "^NSEI"),
]


def _clean_name(value, what, maxlen=80):
    name = " ".join((value or "").split())
    if not name:
        raise InvestmentsError("REQUIRED", f"{what} is required.")
    if len(name) > maxlen:
        raise InvestmentsError("TOO_LONG", f"{what} is too long.")
    return name


# ---------------------------------------------------------------- built-in indices

def ensure_builtin_indices():
    """Create the common indices as shared Instruments (idempotent). They have no prices until the price phase."""
    made = []
    for name, code in BUILTIN_INDICES:
        obj, created = Instrument.objects.get_or_create(
            profile=None, kind=KIND_INDEX, code=code,
            defaults={"name": name, "currency": "INR", "asset_class": "equity", "price_source": "yahoo", "price_basis": "split_adjusted"})
        if created:
            made.append(obj)
    return made


def default_index_for(profile):
    """The Default Index instrument (Nifty 50 until the profile chooses another)."""
    settings = core.get_settings(profile, create=False)
    if settings.default_index_id:
        return settings.default_index
    return Instrument.objects.filter(profile=None, kind=KIND_INDEX, code="^NSEI").first()


# ---------------------------------------------------------------- portfolios and brokers

@transaction.atomic
def ensure_default_portfolio(profile):
    """A new profile gets one portfolio named after it so a first purchase needs no set-up (plan 4: every transaction has one)."""
    if not Portfolio.objects.filter(profile=profile).exists():
        Portfolio.objects.create(profile=profile, name=profile.name[:80], owner_name="")
        core.touch(profile)


@transaction.atomic
def add_portfolio(profile, user, name, owner_name=""):
    name = _clean_name(name, "Portfolio name")
    if Portfolio.objects.filter(profile=profile, name__iexact=name).exists():
        raise InvestmentsError("DUPLICATE", "A portfolio with that name already exists.", 409)
    obj = Portfolio.objects.create(profile=profile, name=name, owner_name=" ".join((owner_name or "").split())[:80])
    core.touch(profile)
    return obj


@transaction.atomic
def rename_portfolio(profile, user, pk, name, owner_name=None):
    obj = Portfolio.objects.filter(pk=pk, profile=profile).first()
    if obj is None:
        raise not_found("portfolio")
    name = _clean_name(name, "Portfolio name")
    if Portfolio.objects.filter(profile=profile, name__iexact=name).exclude(pk=pk).exists():
        raise InvestmentsError("DUPLICATE", "A portfolio with that name already exists.", 409)
    obj.name = name
    if owner_name is not None:
        obj.owner_name = " ".join(owner_name.split())[:80]
    obj.save()
    core.touch(profile)
    return obj


@transaction.atomic
def delete_portfolio(profile, user, pk):
    obj = Portfolio.objects.filter(pk=pk, profile=profile).first()
    if obj is None:
        raise not_found("portfolio")
    if Transaction.objects.filter(portfolio=obj).exists() or Transfer.objects.filter(Q(from_portfolio=obj) | Q(to_portfolio=obj)).exists() \
            or Folio.objects.filter(portfolio=obj).exists():
        raise InvestmentsError("IN_USE", "This portfolio has records, so it cannot be deleted.", 409)
    obj.delete()
    core.touch(profile)


@transaction.atomic
def add_broker(profile, user, name):
    name = _clean_name(name, "Broker name")
    if Broker.objects.filter(profile=profile, name__iexact=name).exists():
        raise InvestmentsError("DUPLICATE", "A broker with that name already exists.", 409)
    obj = Broker.objects.create(profile=profile, name=name)
    core.touch(profile)
    return obj


@transaction.atomic
def rename_broker(profile, user, pk, name):
    obj = Broker.objects.filter(pk=pk, profile=profile).first()
    if obj is None:
        raise not_found("broker")
    name = _clean_name(name, "Broker name")
    if Broker.objects.filter(profile=profile, name__iexact=name).exclude(pk=pk).exists():
        raise InvestmentsError("DUPLICATE", "A broker with that name already exists.", 409)
    obj.name = name
    obj.save()
    core.touch(profile)
    return obj


@transaction.atomic
def set_broker_hidden(profile, user, pk, hidden):
    obj = Broker.objects.filter(pk=pk, profile=profile).first()
    if obj is None:
        raise not_found("broker")
    obj.hidden = bool(hidden)
    obj.save(update_fields=["hidden"])
    core.touch(profile)
    return obj


@transaction.atomic
def delete_broker(profile, user, pk):
    obj = Broker.objects.filter(pk=pk, profile=profile).first()
    if obj is None:
        raise not_found("broker")
    if Transaction.objects.filter(broker=obj).exists() or Transfer.objects.filter(Q(from_broker=obj) | Q(to_broker=obj)).exists():
        raise InvestmentsError("IN_USE", "This broker has records, so it cannot be deleted. Hide it instead.", 409)
    obj.delete()
    core.touch(profile)


# ---------------------------------------------------------------- settings

SETTINGS_FIELDS = {
    "default_broker_share", "default_broker_fund", "default_broker_alternative", "default_broker_foreign", "sip_mode",
    "awaiting_treatment", "awaiting_reminder_days", "corporate_action_mode", "long_term_days", "default_index",
    "sectoral_enabled", "include_dividends", "alt_treatment", "money_default", "hidden_pages", "default_exchange",
    "show_status_dots", "rule_a_enabled", "rule_a_fall_pct", "rule_a_rise_pct", "rule_a_window_days", "rule_a_window_fall_pct", "rule_b_enabled",
    "rule_b_loss_pct", "rule_b_gain_pct", "guardrail_replaces_global", "alert_email", "maturity_alert_days", "year_cutoffs", "insights_off", "concentration_limit", "compact_tables",
    "column_picker", "overview", "units_decimals", "rupee_decimals",
}


@transaction.atomic
def update_settings(profile, user, **values):
    unknown = set(values) - SETTINGS_FIELDS
    if unknown:
        raise InvestmentsError("BAD_FIELD", f"Unknown setting: {', '.join(sorted(unknown))}.")
    row = core.get_settings(profile)
    for key, value in values.items():
        if key.startswith("default_broker_") and value is not None and value.profile_id != profile.pk:
            raise not_found("broker")
        if key == "default_index" and value is not None and value.kind != KIND_INDEX:
            raise InvestmentsError("BAD_INDEX", "The Default Index must be an index.")
        if key == "awaiting_reminder_days" and not 1 <= int(value) <= 60:
            raise InvestmentsError("BAD_NUMBER", "Reminder days must be between 1 and 60.")
        setattr(row, key, value)
    row.save()
    core.touch(profile)
    return row


def set_money_preference(user, mode):
    """The person's own Auto / Full choice (plan 23)."""
    if mode not in ("auto", "full"):
        raise InvestmentsError("BAD_CHOICE", "Choose Auto or Full.")
    obj, _ = InvestmentsUserPrefs.objects.update_or_create(user=user, defaults={"money_mode": mode})
    return obj


def money_preference(user, profile=None):
    """The person's Auto / Full choice, else the profile's starting choice, else Auto."""
    pref = InvestmentsUserPrefs.objects.filter(user=user).first() if getattr(user, "pk", None) else None
    if pref:
        return pref.money_mode
    if profile is not None:
        return core.get_settings(profile, create=False).money_default
    return "auto"


# ---------------------------------------------------------------- investments (instruments)

def _norm(text):
    return re.sub(r"\s+", "", (text or "")).casefold()


def find_similar(profile, name="", code="", kind=None):
    """Shared instruments (and the profile's own) that look like the one being added: same code, or same name apart from case and spaces."""
    visible = Instrument.objects.filter(Q(profile=None) | Q(profile=profile)).exclude(kind=KIND_INDEX)
    found = []
    code_n, name_n = _norm(code), _norm(name)
    for inst in visible.iterator(chunk_size=500):
        if kind and inst.kind != kind and not (kind in HOLDABLE_KINDS and inst.kind in HOLDABLE_KINDS and (code_n and _norm(inst.code) == code_n)):
            continue
        if (code_n and _norm(inst.code) == code_n) or (name_n and _norm(inst.name) == name_n):
            found.append(inst)
    return found


@transaction.atomic
def create_instrument(profile, user, *, kind, name, code="", isin="", currency="INR", asset_class="equity", sector="",
                      exchange="", price_source="manual", interest_rate=None, maturity_date=None, allow_duplicate=False, interest_type="compound"):
    """Add an investment. Alternative investments are private to the profile; the rest are shared (plan 16.1). A look-alike is refused
    unless ``allow_duplicate`` (the page offers "use the existing one" instead)."""
    if kind not in HOLDABLE_KINDS:
        raise InvestmentsError("BAD_KIND", "Choose a share, mutual fund, alternative or foreign investment.")
    name = _clean_name(name, "Name", 200)
    code = (code or "").strip()
    private = kind == KIND_ALTERNATIVE
    if not allow_duplicate:
        similar = find_similar(profile, name, code, kind)
        if similar:
            raise InvestmentsError("SIMILAR", f"'{similar[0].name}' already exists. Use it instead of adding a copy.", 409,
                                   {"existing_id": similar[0].pk})
    obj = Instrument.objects.create(
        profile=profile if private else None, name=name, kind=kind, code=code, isin=(isin or "").strip().upper(),
        currency=(currency or "INR").upper()[:3], asset_class=asset_class, sector=(sector or "").strip(), exchange=exchange,
        price_source="manual" if private else (price_source if price_source != "manual" else fetch_defaults.default_source(kind)),
        price_basis=fetch_defaults.default_basis(fetch_defaults.default_source(kind)) if not private else "",
        interest_rate=interest_rate, interest_type=interest_type if interest_type in ("simple", "compound") else "compound", maturity_date=maturity_date)
    ProfileInvestment.objects.get_or_create(profile=profile, instrument=obj)
    core.touch(profile)
    return obj


def records_of(profile, instrument):
    """Counts of what this profile has recorded against ``instrument`` (what deleting it would remove)."""
    from investments.models import Dividend, SipSchedule

    return {
        "transactions": Transaction.objects.filter(profile=profile, instrument=instrument).count(),
        "transfers": Transfer.objects.filter(profile=profile, instrument=instrument).count(),
        "folios": Folio.objects.filter(profile=profile, instrument=instrument).count(),
        "values": AltValue.objects.filter(profile=profile, instrument=instrument).count(),
        "dividends": Dividend.objects.filter(profile=profile, instrument=instrument).count(),
        "sips": SipSchedule.objects.filter(profile=profile, instrument=instrument).count(),
    }


def _in_use_anywhere(instrument):
    """True while any profile still has a record, a schedule or its own row for this shared investment."""
    from investments.models import Dividend, SipSchedule

    return any(m.objects.filter(instrument=instrument).exists() for m in (Transaction, Transfer, Dividend, SipSchedule, ProfileInvestment))


def alert_states_of(instrument):
    """The saved alert dismissals and snoozes about ``instrument`` (their keys are ``kind:<instrument id>:...``)."""
    from investments.models import AlertState

    return AlertState.objects.filter(key__regex=rf"^[a-z_]+:{int(instrument.pk)}(:|$)")


def delete_profile_records(profile, user, instrument, group, summary):
    """Delete everything ``profile`` recorded against ``instrument``, writing each logged record (transactions,
    transfers, dividends, folio numbers, dated values, corporate action confirmations) to the permanent history first.

    The order follows the protected links: switch links, then transactions, transfers, dividends and SIP schedules
    (they point at folios), then folios, dated values, guardrails, alert states and the profile's own row."""
    from investments.models import CorporateActionResponse, Dividend, Guardrail, SipSchedule

    logged = (Transaction, Transfer, Dividend, Folio, AltValue)
    for model in logged:
        for obj in model.objects.filter(profile=profile, instrument=instrument).iterator():
            history.record(profile, user, obj, "delete", group=group, summary=summary)
    for obj in CorporateActionResponse.objects.filter(profile=profile, action__instrument=instrument).select_related("action"):
        history.record(profile, user, obj, "delete", group=group, summary=summary)
    Transaction.objects.filter(profile=profile, instrument=instrument).update(switch=None)
    for model in (Transaction, Transfer, Dividend, SipSchedule, Folio, AltValue, Guardrail):
        model.objects.filter(profile=profile, instrument=instrument).delete()
    CorporateActionResponse.objects.filter(profile=profile, action__instrument=instrument).delete()
    alert_states_of(instrument).filter(profile=profile).delete()
    ProfileInvestment.objects.filter(profile=profile, instrument=instrument).delete()


def get_profile_investment(profile, instrument):
    obj, _ = ProfileInvestment.objects.get_or_create(profile=profile, instrument=instrument)
    return obj


@transaction.atomic
def update_profile_details(profile, user, instrument, *, notes=None, links=None, hidden=None, sectoral_index=None, sectoral_set=False):
    """The profile's own details of an investment: notes, links, hidden flag, sectoral index (editable by an Editor; plan 10)."""
    obj = get_profile_investment(profile, instrument)
    if notes is not None:
        obj.notes = notes
    if links is not None:
        clean = []
        for link in links:
            url = (link.get("url") or "").strip()
            if not url:
                continue
            if not re.match(r"^https?://", url, re.I):
                raise InvestmentsError("BAD_LINK", "A link must start with http:// or https://.")
            clean.append({"label": (link.get("label") or url)[:80], "url": url[:500]})
        obj.links = clean
    if hidden is not None:
        if hidden:
            from investments.services import holdings

            h, _t = holdings.compute(profile, instrument_ids=[instrument.pk], with_xirr=False)
            if any(not x.sold_out for x in h):
                raise InvestmentsError("STILL_HELD", "Only a sold-out investment can be hidden.", 409)
        obj.hidden = bool(hidden)
    if sectoral_set:
        if sectoral_index is not None and sectoral_index.kind != KIND_INDEX:
            raise InvestmentsError("BAD_INDEX", "The sectoral index must be an index.")
        obj.sectoral_index = sectoral_index
    obj.save()
    core.touch(profile)
    return obj


@transaction.atomic
def update_alt_interest(profile, user, instrument, *, interest_rate, interest_type, maturity_date):
    """Change the interest rate, interest type and maturity date of an alternative investment (private to the profile, so an Editor may).
    Each change is written to the permanent catalogue history and the profile's cached figures are refreshed."""
    if instrument.kind != KIND_ALTERNATIVE or instrument.profile_id != profile.pk:
        raise not_found("investment")
    if interest_type not in ("simple", "compound"):
        interest_type = "compound"
    if interest_rate is not None and (interest_rate < 0 or interest_rate > 1000):
        raise InvestmentsError("BAD_RATE", "The interest rate must be between 0 and 1000 percent.")
    from investments.services import catalogue

    new = {"interest_rate": interest_rate, "interest_type": interest_type, "maturity_date": maturity_date}
    changed = False
    for key, value in new.items():
        old = getattr(instrument, key)
        if old != value:
            catalogue.log(user, instrument, "instrument", instrument.pk, key, old, value, "Edited on the investment page")
            setattr(instrument, key, value)
            changed = True
    if changed:
        instrument.save(update_fields=list(new))
        core.touch(profile)
    return instrument


@transaction.atomic
def update_shared_details(profile, user, instrument, **values):
    """Change the shared details of an investment. Admin only (plan 10); an Editor's profile details are separate."""
    if not getattr(user, "is_admin", False):
        raise forbidden("Only an Admin can change the shared details of an investment.")
    if instrument.profile_id not in (None, profile.pk):
        raise not_found("investment")
    allowed = {"name", "code", "isin", "exchange", "currency", "asset_class", "sector", "price_source", "fallback_source", "fetch_enabled"}
    unknown = set(values) - allowed
    if unknown:
        raise InvestmentsError("BAD_FIELD", f"Cannot change: {', '.join(sorted(unknown))}.")
    for key, value in values.items():
        setattr(instrument, key, value)
    instrument.save()
    core.touch(profile)
    return instrument


@transaction.atomic
def delete_instrument(profile, user, instrument, confirm_name=None):
    """Delete an investment from this profile (plan 10).

    * Editor: only when the profile has no transactions, transfers, folios or dated values for it.
    * Admin: also when it has records, after typing the investment's name; a "Before deleting investment" backup is taken first
      and nothing is deleted if it cannot be made. The deletion is written to the permanent history.
    A shared instrument stays for other profiles; when nobody uses it any more it is removed with its prices.
    """
    
    if instrument.profile_id not in (None, profile.pk):
        raise not_found("investment")
    counts = records_of(profile, instrument)
    has_records = any(counts.values())
    if has_records:
        if not getattr(user, "is_admin", False):
            raise forbidden("This investment has records. Only an Admin can delete it; once it is sold out you can hide it instead.")
        if (confirm_name or "").strip() != instrument.name:
            raise InvestmentsError("CONFIRM_NAME", "Type the investment's name exactly to confirm.", 400, {"counts": counts})
        from backups import services as backup_services

        try:
            backup_services.create_backup("pre_inv_delete", user)
        except Exception as exc:
            raise InvestmentsError("BACKUP_FAILED", f"The safety backup could not be made, so nothing was deleted. ({exc})", 500)
        from investments.models import new_group

        delete_profile_records(profile, user, instrument, new_group(), f"Deleted with investment {instrument.name}")
    else:
        # Nothing is recorded, but this profile's guardrails and alert states may still point at it.
        from investments.models import Guardrail

        Guardrail.objects.filter(profile=profile, instrument=instrument).delete()
        alert_states_of(instrument).filter(profile=profile).delete()
    ProfileInvestment.objects.filter(profile=profile, instrument=instrument).delete()
    # This profile's sectoral-index choices only (another profile's choice is theirs to change).
    ProfileInvestment.objects.filter(profile=profile, sectoral_index=instrument).update(sectoral_index=None)
    removed_shared = False
    if instrument.profile_id is not None:
        instrument.delete()
        removed_shared = True
    elif not _in_use_anywhere(instrument):
        instrument.delete()
        removed_shared = True
    core.touch(profile)
    return {"counts": counts, "instrument_removed": removed_shared}


# ---------------------------------------------------------------- folios

def _folio_key(number):
    return re.sub(r"[\s]+", "", number or "").casefold()


@transaction.atomic
def add_folio(profile, user, *, instrument, portfolio, number, notes="", confirm_new=False):
    """A folio number is free text stored exactly as typed. A look-alike (same apart from capitals or spaces) asks first (plan 6)."""
    number = (number or "").strip()
    if not number:
        raise InvestmentsError("REQUIRED", "Folio number is required.")
    if portfolio.profile_id != profile.pk or instrument.profile_id not in (None, profile.pk):
        raise not_found("folio")
    existing = Folio.objects.filter(profile=profile, instrument=instrument, portfolio=portfolio)
    for f in existing:
        if f.number == number:
            raise InvestmentsError("DUPLICATE", "That folio already exists.", 409, {"existing_id": f.pk})
    for f in existing:
        if _folio_key(f.number) == _folio_key(number) and not confirm_new:
            raise InvestmentsError("SIMILAR_FOLIO", f"'{f.number}' looks the same as '{number}'. Is it the same folio?", 409,
                                   {"existing_id": f.pk, "existing": f.number})
    obj = Folio.objects.create(profile=profile, instrument=instrument, portfolio=portfolio, number=number, notes=(notes or "")[:200])
    history.record(profile, user, obj, "create", summary=f"Folio {number}")
    core.touch(profile)
    return obj


@transaction.atomic
def edit_folio(profile, user, pk, *, number=None, notes=None):
    obj = Folio.objects.filter(pk=pk, profile=profile).first()
    if obj is None:
        raise not_found("folio")
    if number is not None:
        number = number.strip()
        if not number:
            raise InvestmentsError("REQUIRED", "Folio number is required.")
        if Folio.objects.filter(profile=profile, instrument=obj.instrument, portfolio=obj.portfolio, number=number).exclude(pk=pk).exists():
            raise InvestmentsError("DUPLICATE", "That folio already exists.", 409)
        obj.number = number
    if notes is not None:
        obj.notes = notes[:200]
    obj.save()
    history.record(profile, user, obj, "edit", summary=f"Folio {obj.number}")
    core.touch(profile)
    return obj


@transaction.atomic
def delete_folio(profile, user, pk):
    obj = Folio.objects.filter(pk=pk, profile=profile).first()
    if obj is None:
        raise not_found("folio")
    if Transaction.objects.filter(folio=obj).exists() or Transfer.objects.filter(Q(from_folio=obj) | Q(to_folio=obj)).exists():
        raise InvestmentsError("IN_USE", "Transactions use this folio, so it cannot be deleted.", 409)
    history.record(profile, user, obj, "delete", summary=f"Folio {obj.number}")
    obj.delete()
    core.touch(profile)
