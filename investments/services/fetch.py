"""Fetching prices (plan sections 15.2 to 15.5 and 24.5). One module for the nightly job, the Update Prices button and the
re-fetch buttons, so they cannot disagree. Everything that talks to the internet goes through ``investments.adapters``.

Rules (plan 15.2): fetch only the days since the last stored date; retry a refused request a few times with growing delay,
then give up on that symbol for this run, keep the last price, record the failure; never overwrite `upload` rows or hand-entered
prices; reject prices of zero or below; space requests; respect a per-run cap on symbols and a maximum run time.
"""
import random
import time
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from investments.adapters import amfi, http, mfapi, yahoo
from investments.adapters.base import FetchError
from investments.errors import InvestmentsError
from investments.models import (
    KIND_ALTERNATIVE, KIND_FUND, KIND_INDEX, BASIS_ADJ, Instrument, InvestmentSettings, Price, PriceStatus,
    ProfileInvestment, SourceRun, SourceSymbol, SplitSignal,
)
from investments.services import prices as price_service

BATCH = 500
STALE_DAYS = 5
UPDATE_BATCH = 10


from investments.services.fetch_defaults import default_basis, default_source  # noqa: E402,F401


def symbol_for(instrument, source):
    row = SourceSymbol.objects.filter(instrument=instrument, source=source).values_list("symbol", flat=True).first()
    return row or instrument.code


def bump_version():
    status, _ = PriceStatus.objects.get_or_create(pk=1)
    PriceStatus.objects.filter(pk=status.pk).update(version=F("version") + 1)


def price_version():
    return PriceStatus.objects.values_list("version", flat=True).first() or 0


def tracked_instruments(profile=None, ids=None):
    """Instruments worth fetching: those someone listed or holds (plus the indices in use), with a fetch source and fetching switched on."""
    wanted = set(ProfileInvestment.objects.filter(**({"profile": profile} if profile else {})).values_list("instrument_id", flat=True))
    index_ids = set(InvestmentSettings.objects.exclude(default_index=None).values_list("default_index_id", flat=True))
    index_ids |= set(ProfileInvestment.objects.exclude(sectoral_index=None).values_list("sectoral_index_id", flat=True))
    index_ids |= set(Instrument.objects.filter(kind=KIND_INDEX, code="^NSEI").values_list("id", flat=True))
    qs = Instrument.objects.filter(id__in=wanted | index_ids, fetch_enabled=True).exclude(kind=KIND_ALTERNATIVE).exclude(price_source__in=["manual", "upload"])
    if ids is not None:
        qs = qs.filter(id__in=list(ids))
    return list(qs.order_by("kind", "name", "id"))


# ---------------------------------------------------------------- writing prices

def upsert_prices(instrument, rows, source="api", basis=None):
    """Store ``rows`` (``[(date, close)]``). A row whose basis differs from the instrument's is refused (plan 16.2); an uploaded
    price is never replaced by a fetched one. Returns ``(added, changed, kept_uploads)``."""
    if basis is None:
        basis = instrument.price_basis
    if instrument.price_basis and basis and basis != instrument.price_basis:
        raise InvestmentsError("BASIS_MISMATCH", f"{instrument.name}: the rows are on a '{basis}' basis but the investment is '{instrument.price_basis}'.", 409)
    rows = [(d, c) for d, c in rows if c is not None and c > 0]
    if not rows:
        return 0, 0, 0
    existing = {p.date: p for p in Price.objects.filter(instrument=instrument, date__gte=min(d for d, _ in rows), date__lte=max(d for d, _ in rows))}
    new, changed, kept = [], [], 0
    for day, close in rows:
        old = existing.get(day)
        if old is None:
            new.append(Price(instrument=instrument, date=day, close=close, source=source, basis=basis or ""))
        elif old.source == "upload" and source != "upload":
            kept += 1
        elif old.close != close or old.source != source:
            old.close, old.source, old.basis = close, source, basis or ""
            changed.append(old)
    with transaction.atomic():
        for start in range(0, len(new), BATCH):
            Price.objects.bulk_create(new[start:start + BATCH])
        for start in range(0, len(changed), BATCH):
            Price.objects.bulk_update(changed[start:start + BATCH], ["close", "source", "basis", "fetched_at"])
    return len(new), len(changed), kept


def last_api_date(instrument):
    return Price.objects.filter(instrument=instrument).order_by("-date").values_list("date", flat=True).first()


def refetch_full(instrument, years=10, today=None):
    """Re-fetch a split-adjusted instrument's whole history and replace its fetched rows (the vendor restates the past after a split;
    plan 16.2). Uploaded rows are kept and counted so the person can be told they need re-uploading on the new basis."""
    uploads = Price.objects.filter(instrument=instrument, source="upload").count()
    result = yahoo.fetch(symbol_for(instrument, "yahoo"), None, years=years, today=today)
    with transaction.atomic():
        Price.objects.filter(instrument=instrument, source__in=["api", "helper"]).delete()
        upsert_prices(instrument, result.rows, "api", default_basis("yahoo"))
    return len(result.rows), uploads


# ---------------------------------------------------------------- the run

def _record_dividends(instrument, result):
    from investments.models import DividendSignal

    for day, per_unit in result.dividends:
        if per_unit > 0:
            DividendSignal.objects.get_or_create(instrument=instrument, ex_date=day, defaults={"per_unit": per_unit})


def _record_splits(instrument, result, today, years, failures):
    from investments.services import corporate

    for day, num, den in result.splits:
        signal, created = SplitSignal.objects.get_or_create(instrument=instrument, ex_date=day, defaults={"numerator": num, "denominator": den})
        if created:
            # A possible split for every profile that holds it to confirm or mark not applicable (plan 8).
            try:
                corporate.record(None, None, instrument=instrument, ex_date=day, kind="split", ratio_old=den, ratio_new=num,
                                 notes="Found in the price source's split history", detected=True)
            except InvestmentsError:
                pass
        if created and instrument.price_basis == BASIS_ADJ:
            try:
                refetch_full(instrument, years, today)
                SplitSignal.objects.filter(pk=signal.pk).update(refetched=True)
            except (FetchError, InvestmentsError) as exc:
                failures.append({"id": instrument.pk, "name": instrument.name, "error": f"split re-fetch: {exc}"})


def fetch_prices(*, ids=None, profile=None, trigger="cron", max_seconds=600, max_symbols=200, spacing=1.0, today=None, years=10, clock=time.monotonic,
                 rng=random.random):
    """Fetch new prices for the tracked instruments. Returns a summary dict (also stored as ``SourceRun`` rows)."""
    today = today or date.today()
    started_at = clock()
    summary = {"tried": 0, "updated": 0, "failures": [], "stopped": "", "runs": []}
    from investments.services import helper

    instruments = [i for i in tracked_instruments(profile, ids) if not helper.server_skips(i.price_source)][:max_symbols]
    funds = [i for i in instruments if i.kind == KIND_FUND and i.price_source in ("amfi", "mfapi")]
    others = [i for i in instruments if i not in funds]
    first_request = [True]

    def pause():
        if not first_request[0]:
            http.sleep(spacing + rng())
        first_request[0] = False

    def out_of_time():
        return clock() - started_at > max_seconds

    # --- mutual funds: history by mfapi.in once, then the daily AMFI file (one download for all of them)
    if funds:
        run = SourceRun(source="amfi", trigger=trigger, started=timezone.now())
        failures, updated = [], 0
        wanted = {i.pk: symbol_for(i, "amfi") for i in funds}
        try:
            found = amfi.fetch(list(wanted.values()))
        except FetchError as exc:
            found = {}
            failures.append({"id": 0, "name": "AMFI daily file", "error": str(exc)})
        for inst in funds:
            summary["tried"] += 1
            code = wanted[inst.pk]
            if out_of_time():
                summary["stopped"] = "run-time cap reached"
                break
            try:
                if last_api_date(inst) is None:        # first time: the whole history from mfapi.in
                    pause()
                    result = mfapi.fetch(symbol_for(inst, "mfapi"))
                    added, changed, _ = upsert_prices(inst, result.rows, "api", "")
                    updated += 1 if added or changed else 0
                if code in found:
                    day, nav, _name, _isin = found[code]
                    added, changed, _ = upsert_prices(inst, [(day, nav)], "api", "")
                    updated += 1 if added or changed else 0
                elif not failures:
                    failures.append({"id": inst.pk, "name": inst.name, "error": "not in AMFI's file today"})
            except (FetchError, InvestmentsError) as exc:
                failures.append({"id": inst.pk, "name": inst.name, "error": str(exc)})
        run.tried, run.updated, run.failures, run.finished = len(funds), updated, failures, timezone.now()
        run.save()
        summary["updated"] += updated
        summary["failures"] += failures
        summary["runs"].append(run.pk)

    # --- stocks, indices, foreign: Yahoo, one symbol at a time, spaced
    if others:
        run = SourceRun(source="yahoo", trigger=trigger, started=timezone.now())
        failures, updated, tried = [], 0, 0
        for inst in others:
            if out_of_time():
                summary["stopped"] = "run-time cap reached"
                break
            tried += 1
            summary["tried"] += 1
            pause()
            try:
                since = last_api_date(inst)
                try:
                    result = yahoo.fetch(symbol_for(inst, "yahoo"), since, years=years, today=today)
                except FetchError as first_error:
                    # the fallback source, when one is set (plan 15.2); its basis must match, so only for raw-basis instruments or a basis-free source
                    if inst.fallback_source != "twelvedata":
                        raise
                    from investments.adapters import twelvedata

                    try:
                        result = twelvedata.fetch(symbol_for(inst, "twelvedata"), since, years=years, today=today)
                    except FetchError as second:
                        raise FetchError(f"{first_error}; fallback: {second}") from second
                added, changed, _ = upsert_prices(inst, result.rows, "api", default_basis("yahoo"))
                updated += 1 if added or changed else 0
                if not result.rows:
                    failures.append({"id": inst.pk, "name": inst.name, "error": "no prices returned"})
                _record_splits(inst, result, today, years, failures)
                _record_dividends(inst, result)
                if result.rejected:
                    failures.append({"id": inst.pk, "name": inst.name, "error": f"{result.rejected} price(s) of zero or below were rejected"})
            except (FetchError, InvestmentsError) as exc:
                failures.append({"id": inst.pk, "name": inst.name, "error": str(exc)})
        run.tried, run.updated, run.failures, run.finished = tried, updated, failures, timezone.now()
        run.message = summary["stopped"]
        run.save()
        summary["updated"] += updated
        summary["failures"] += failures
        summary["runs"].append(run.pk)
    # the list of fund schemes, once a week (plan 6)
    if ids is None and not out_of_time():
        from investments.services import schemes

        try:
            schemes.refresh()
        except FetchError as exc:
            summary["failures"].append({"id": 0, "name": "AMFI scheme list", "error": str(exc)})
    # exchange rates for the foreign investments in use (plan 22)
    if ids is None and not out_of_time():
        from investments.services import fx

        fx_updated, fx_failures = fx.fetch_all(today=today, spacing=spacing)
        summary["updated"] += fx_updated
        summary["failures"] += fx_failures
    if summary["updated"]:
        bump_version()
    return summary


# ---------------------------------------------------------------- Update Prices button

def update_plan(profile):
    """The batches the button walks through: all funds together (one AMFI download), then ten other symbols at a time."""
    tracked = tracked_instruments(profile)
    funds = [i.pk for i in tracked if i.kind == KIND_FUND]
    others = [i.pk for i in tracked if i.kind != KIND_FUND]
    batches = ([funds] if funds else []) + [others[i:i + UPDATE_BATCH] for i in range(0, len(others), UPDATE_BATCH)]
    return batches


def start_allowed(now=None, pause_seconds=60):
    """The button pauses for about a minute after use (plan 24.5)."""
    status, _ = PriceStatus.objects.get_or_create(pk=1)
    now = now or timezone.now()
    return not (status.last_button_update_at and (now - status.last_button_update_at).total_seconds() < pause_seconds)


def mark_button_used(now=None):
    status, _ = PriceStatus.objects.get_or_create(pk=1)
    PriceStatus.objects.filter(pk=status.pk).update(last_button_update_at=now or timezone.now())


# ---------------------------------------------------------------- status

def status_summary(profile=None, today=None):
    """For the status line (plan 24.5): when the last run finished, the newest price date, and how many tracked investments are stale."""
    today = today or date.today()
    last = SourceRun.objects.exclude(finished=None).order_by("-finished").first()
    tracked = tracked_instruments(profile)
    last_dates = price_service.last_price_date([i.pk for i in tracked])
    stale = [i for i in tracked if i.pk in last_dates and (today - last_dates[i.pk]).days > STALE_DAYS]
    never = [i for i in tracked if i.pk not in last_dates]
    newest = max(last_dates.values()) if last_dates else None
    return {"last_run": last.finished if last else None, "newest": newest, "stale": stale, "never": never, "tracked": len(tracked)}


def stale_ids(instruments, today=None):
    today = today or date.today()
    last = price_service.last_price_date([i.pk for i in instruments])
    return {i.pk for i in instruments if i.pk in last and (today - last[i.pk]).days > STALE_DAYS}


def one_day_moves(instrument, threshold=Decimal("0.40"), limit=5):
    """Dates where the close moved by more than ``threshold`` in a day (plan 21.1 highlights these; a recorded corporate action explains one)."""
    rows = list(Price.objects.filter(instrument=instrument).order_by("date").values_list("date", "close"))
    out = []
    for (d0, c0), (d1, c1) in zip(rows, rows[1:]):
        if c0 and abs(c1 - c0) / c0 > threshold:
            out.append((d1, c0, c1))
    return out[-limit:]


def stale_days(instrument, today=None):
    today = today or date.today()
    last = price_service.last_price_date([instrument.pk]).get(instrument.pk)
    return (today - last).days if last else None


__all__ = ["fetch_prices", "update_plan", "upsert_prices", "refetch_full", "tracked_instruments", "status_summary", "timedelta"]
