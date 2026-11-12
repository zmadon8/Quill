"""Dividends (plan 7): recorded by the user, with a suggestion from the price source's dividend history and reminders when one is due.
Never part of Total Portfolio Value. Counted in XIRR only while Include Dividends is on."""
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction

from investments import lots
from investments.errors import InvestmentsError, not_found
from investments.models import Dividend, DividendSignal
from investments.services import core, history

REMIND_DAYS = 60
PAID_WITHIN_DAYS = 30


def _dec(value, name, minimum=Decimal(0), allow_none=False):
    if value in (None, ""):
        if allow_none:
            return None
        raise InvestmentsError("REQUIRED", f"{name} is required.")
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except Exception:
        raise InvestmentsError("BAD_NUMBER", f"{name} is not a number.")
    if number < minimum:
        raise InvestmentsError("BAD_NUMBER", f"{name} cannot be negative.")
    return number


def units_on(profile, instrument, day, portfolio=None, broker=None):
    """Units held at the end of ``day`` (for the suggestion: amount per unit times units held on the ex-date)."""
    result = lots.replay(core.events_for(profile, instrument.pk), as_of=day)
    return sum((lot.units for lot in result.all_lots() if (portfolio is None or lot.bucket.portfolio == portfolio)
                and (broker is None or lot.bucket.broker == broker)), Decimal(0))


def suggestion(profile, instrument, received_on, portfolio=None, broker=None):
    """``{"ex_date", "per_unit", "units", "amount"}`` from the latest reported dividend in the 60 days before ``received_on``, or None."""
    signal = DividendSignal.objects.filter(instrument=instrument, ex_date__lte=received_on, ex_date__gte=received_on - timedelta(days=REMIND_DAYS)).order_by("-ex_date").first()
    if signal is None:
        return None
    units = units_on(profile, instrument, signal.ex_date - timedelta(days=1), portfolio, broker)
    return {"ex_date": signal.ex_date, "per_unit": signal.per_unit, "units": units, "amount": (signal.per_unit * units).quantize(Decimal("0.01"))}


def due(profile, today=None):
    """Reported dividends on investments held on the ex-date with nothing recorded in the 60 days after it: reminders (plan 7)."""
    from investments.services.corporate import held_instrument_ids

    today = today or date.today()
    out = []
    ids = held_instrument_ids(profile)
    for signal in DividendSignal.objects.filter(instrument_id__in=ids, ex_date__gte=today - timedelta(days=REMIND_DAYS)).select_related("instrument"):
        if Dividend.objects.filter(profile=profile, instrument=signal.instrument, date__gte=signal.ex_date - timedelta(days=3),
                                   date__lte=signal.ex_date + timedelta(days=REMIND_DAYS)).exists():
            continue
        units = units_on(profile, signal.instrument, signal.ex_date - timedelta(days=1))
        if units > 0:
            out.append({"instrument": signal.instrument, "ex_date": signal.ex_date, "per_unit": signal.per_unit, "units": units,
                        "amount": (signal.per_unit * units).quantize(Decimal("0.01"))})
    return sorted(out, key=lambda r: r["ex_date"])


AUTO_NOTE = "Logged automatically from the price source's dividend history"


def _holders_on(profile, instrument, day):
    """``{(portfolio id, broker id, folio id): units}`` held at the end of ``day``."""
    result = lots.replay(core.events_for(profile, instrument.pk), as_of=day)
    held = {}
    for lot in result.all_lots():
        key = (lot.bucket.portfolio, lot.bucket.broker, lot.bucket.folio)
        held[key] = held.get(key, Decimal(0)) + lot.units
    return {k: v for k, v in held.items() if v > 0}


def auto_log(profile, signals=None, today=None):
    """Log the reported dividends for a profile that has chosen ``Log automatically`` for Dividends: one dividend dated the ex-date for each
    portfolio and broker (and folio) that held units the day before, amount per unit times units. Each signal is logged once for a profile
    (a dividend the person deletes is not logged again), only for the last 60 days, and not where the person already recorded a dividend
    within 30 days after the ex-date (or 3 before). Dividends of foreign investments stay as suggestions because the rupee amount is not known. Returns the dividends made."""
    from investments.models import Broker, Folio, Portfolio
    from investments.services.corporate import auto_apply, held_instrument_ids

    if not auto_apply(profile, "dividend"):
        return []
    today = today or date.today()
    if signals is None:
        signals = DividendSignal.objects.filter(instrument_id__in=held_instrument_ids(profile), ex_date__gte=today - timedelta(days=REMIND_DAYS))
    made = []
    for signal in signals.select_related("instrument"):
        if signal.ex_date > today or signal.ex_date < today - timedelta(days=REMIND_DAYS) or profile.pk in (signal.logged_for or []):
            continue
        if signal.instrument.currency != "INR" or signal.instrument.profile_id not in (None, profile.pk):
            continue
        held = _holders_on(profile, signal.instrument, signal.ex_date - timedelta(days=1))
        if not held:
            continue
        window = Dividend.objects.filter(profile=profile, instrument=signal.instrument, date__gte=signal.ex_date - timedelta(days=3),
                                         date__lte=signal.ex_date + timedelta(days=PAID_WITHIN_DAYS))
        failed = False
        if not window.exists():
            for (portfolio_id, broker_id, folio_id), units in sorted(held.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or 0)):
                amount = (signal.per_unit * units).quantize(Decimal("0.01"))
                if amount < Decimal("0.01"):
                    continue
                try:
                    made.append(add(profile, None, date=signal.ex_date, instrument=signal.instrument, portfolio=Portfolio.objects.get(pk=portfolio_id),
                                    broker=Broker.objects.get(pk=broker_id), folio=Folio.objects.filter(pk=folio_id).first() if folio_id else None,
                                    amount=amount, note=AUTO_NOTE))
                except InvestmentsError:
                    failed = True        # one bad row does not stop the others; the signal is tried again next time
        if failed:
            continue
        signal.logged_for = list(signal.logged_for or []) + [profile.pk]
        signal.save(update_fields=["logged_for"])
    return made


def auto_log_for_instrument(instrument, today=None):
    """After a price update: log this investment's recent reported dividends for every profile that logs them automatically."""
    from accounts.models import Profile
    from investments.models import InvestmentSettings, ProfileInvestment, Transaction

    ids = set(ProfileInvestment.objects.filter(instrument=instrument).values_list("profile_id", flat=True))
    ids |= set(Transaction.objects.filter(instrument=instrument).order_by().values_list("profile_id", flat=True).distinct())
    on = [row.profile_id for row in InvestmentSettings.objects.filter(profile_id__in=ids) if (row.corporate_auto or {}).get("dividend")]
    made = []
    for profile in Profile.objects.filter(pk__in=on):
        made += auto_log(profile, DividendSignal.objects.filter(instrument=instrument), today)
    return made


def _validate(profile, instrument, portfolio, broker, folio):
    if instrument.profile_id not in (None, profile.pk):
        raise not_found("investment")
    if portfolio.profile_id != profile.pk or broker.profile_id != profile.pk:
        raise not_found("portfolio or broker")
    if folio is not None and (folio.profile_id != profile.pk or folio.instrument_id != instrument.pk):
        raise InvestmentsError("BAD_FOLIO", "That folio does not belong to this investment.")


@transaction.atomic
def add(profile, user, *, date, instrument, portfolio, broker, amount, tax_deducted=0, folio=None, note="", local_amount=None, foreign_tax=None):
    _validate(profile, instrument, portfolio, broker, folio)
    if date > __import__("datetime").date.today():
        raise InvestmentsError("FUTURE_DATE", "The date received cannot be in the future.")
    obj = Dividend.objects.create(
        profile=profile, date=date, instrument=instrument, portfolio=portfolio, broker=broker, folio=folio,
        amount=_dec(amount, "Amount received", Decimal("0.01")), tax_deducted=_dec(tax_deducted or 0, "Tax deducted"),
        currency=instrument.currency, local_amount=_dec(local_amount, "Amount in the investment's currency", allow_none=True),
        foreign_tax=_dec(foreign_tax, "Tax withheld abroad", allow_none=True), note=(note or "")[:200],
        created_by=user if getattr(user, "pk", None) else None)
    history.record(profile, user, obj, "create", summary=f"Dividend from {instrument.name}")
    core.touch(profile)
    return obj


@transaction.atomic
def edit(profile, user, pk, expected_version=None, **fields):
    obj = Dividend.objects.select_for_update().filter(pk=pk, profile=profile).first()
    if obj is None:
        raise not_found("dividend")
    if expected_version is not None and int(expected_version) != obj.version:
        raise InvestmentsError("CLASH", "Someone else changed this dividend after you opened it. Reload and try again.", 409)
    for key in ("date", "instrument", "portfolio", "broker", "folio", "note"):
        if key in fields:
            setattr(obj, key, fields[key])
    if "amount" in fields:
        obj.amount = _dec(fields["amount"], "Amount received", Decimal("0.01"))
    if "tax_deducted" in fields:
        obj.tax_deducted = _dec(fields["tax_deducted"] or 0, "Tax deducted")
    _validate(profile, obj.instrument, obj.portfolio, obj.broker, obj.folio)
    obj.version += 1
    obj.save()
    history.record(profile, user, obj, "edit", summary=f"Dividend from {obj.instrument.name}")
    core.touch(profile)
    return obj


@transaction.atomic
def delete(profile, user, pk):
    obj = Dividend.objects.filter(pk=pk, profile=profile).first()
    if obj is None:
        raise not_found("dividend")
    history.record(profile, user, obj, "delete", summary=f"Deleted dividend from {obj.instrument.name}")
    obj.delete()
    core.touch(profile)


def by_year(profile, portfolio=None, broker=None):
    """``[(financial year label, received, tax deducted)]`` newest first."""
    from fees.services.financial_year import derive_financial_year

    qs = Dividend.objects.filter(profile=profile)
    if portfolio:
        qs = qs.filter(portfolio_id=portfolio)
    if broker:
        qs = qs.filter(broker_id=broker)
    years = {}
    for day, amount, tax in qs.values_list("date", "amount", "tax_deducted"):
        fy = derive_financial_year(day)
        received, deducted = years.get(fy, (Decimal(0), Decimal(0)))
        years[fy] = (received + amount, deducted + tax)
    return [(fy, r, t) for fy, (r, t) in sorted(years.items(), reverse=True)]
