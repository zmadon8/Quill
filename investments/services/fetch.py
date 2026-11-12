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
from django.db.models import F, Min
from django.utils import timezone

from investments.adapters import amfi, http, mfapi, yahoo
from investments.adapters.base import FetchError, FormatError
from investments.errors import InvestmentsError
from investments.models import (
    KIND_ALTERNATIVE, KIND_FUND, KIND_INDEX, BASIS_ADJ, Instrument, InvestmentSettings, Price, PriceStatus,
    ProfileInvestment, SourceRun, SourceSymbol, SplitSignal, STATUS_FINAL, Transaction, Transfer,
)
from investments.services import prices as price_service
from investments.services import source_formats

BATCH = 500
STALE_DAYS = 5
UPDATE_BATCH = 10
#: Days kept after the last unit is sold (the sale-date valuation needs a price) and fetched before the first purchase (a purchase on a
#: non-trading day is valued at the previous close).
WINDOW_BUFFER_DAYS = 7
WINDOW_LEAD_DAYS = 7


from investments.services.fetch_defaults import default_basis, default_source  # noqa: E402,F401


def symbol_for(instrument, source):
    row = SourceSymbol.objects.filter(instrument=instrument, source=source).values_list("symbol", flat=True).first()
    return row or instrument.code


def bump_version():
    status, _ = PriceStatus.objects.get_or_create(pk=1)
    PriceStatus.objects.filter(pk=status.pk).update(version=F("version") + 1)


def price_version():
    return PriceStatus.objects.values_list("version", flat=True).first() or 0


def portfolio_start():
    """The earliest transaction or transfer date across every profile (None when there are none): where the indices are fetched from."""
    days = [Transaction.objects.aggregate(m=Min("date"))["m"], Transfer.objects.aggregate(m=Min("date"))["m"]]
    days = [d for d in days if d]
    return min(days) if days else None


def fetch_window(instrument_ids=None, today=None):
    """``{instrument id: (start, end)}`` for the investments someone has bought, across ALL profiles. ``start`` is the earliest transaction
    or transfer date (a purchase, an opening balance, a transfer in, or one awaiting allotment); ``end`` is None while units (or a purchase
    awaiting allotment, a SIP to confirm or a future-dated row) remain in any profile, else the date of the last row plus
    ``WINDOW_BUFFER_DAYS``. Units are replayed as ``holdings.compute`` does (bonus, split and demerger units, applied corporate actions).
    An investment with no transactions at all (merely listed) has no entry, so no price history is fetched for it."""
    from accounts.models import Profile
    from investments.services import holdings

    today = today or date.today()
    spans, per_profile = {}, {}

    def note(iid, pid, day, is_open):
        span = spans.setdefault(iid, [day, day, False])
        span[0], span[1] = min(span[0], day), max(span[1], day)
        span[2] = span[2] or is_open or day > today
        per_profile.setdefault(pid, set()).add(iid)

    txns = Transaction.objects.all()
    transfers = Transfer.objects.all()
    if instrument_ids is not None:
        txns, transfers = txns.filter(instrument_id__in=list(instrument_ids)), transfers.filter(instrument_id__in=list(instrument_ids))
    for iid, pid, day, status in txns.values_list("instrument_id", "profile_id", "date", "status").iterator():
        note(iid, pid, day, status != STATUS_FINAL)
    for iid, pid, day in transfers.values_list("instrument_id", "profile_id", "date").iterator():
        note(iid, pid, day, False)
    profiles = Profile.objects.in_bulk(per_profile)
    for pid, iids in per_profile.items():
        rows, _totals = holdings.compute(profiles[pid], as_of=today, instrument_ids=iids, with_xirr=False, include_dividends=False)
        for h in rows:
            if h.units != 0 or h.awaiting:
                spans[h.instrument.pk][2] = True
    return {iid: (first, None if is_open else last + timedelta(days=WINDOW_BUFFER_DAYS)) for iid, (first, last, is_open) in spans.items()}


def tracked_with_windows(profile=None, ids=None, today=None):
    """``([Instrument], {id: (start, end)})``. An investment is tracked while it is inside its window: from its first purchase until
    ``WINDOW_BUFFER_DAYS`` after the last unit was sold in every profile. A listed investment nobody has bought is not tracked. The indices
    in use (default, sectoral, ^NSEI) are always tracked, from the earliest purchase of any profile (``start`` None when there is none)."""
    today = today or date.today()
    wanted = set(ProfileInvestment.objects.filter(**({"profile": profile} if profile else {})).values_list("instrument_id", flat=True))
    index_ids = set(InvestmentSettings.objects.exclude(default_index=None).values_list("default_index_id", flat=True))
    index_ids |= set(ProfileInvestment.objects.exclude(sectoral_index=None).values_list("sectoral_index_id", flat=True))
    index_ids |= set(Instrument.objects.filter(kind=KIND_INDEX, code="^NSEI").values_list("id", flat=True))
    qs = Instrument.objects.filter(id__in=wanted | index_ids, fetch_enabled=True).exclude(kind=KIND_ALTERNATIVE).exclude(price_source__in=["manual", "upload"])
    if ids is not None:
        qs = qs.filter(id__in=list(ids))
    candidates = list(qs.order_by("kind", "name", "id"))
    spans = fetch_window([i.pk for i in candidates if i.kind != KIND_INDEX], today)
    index_start = portfolio_start() if any(i.kind == KIND_INDEX for i in candidates) else None
    out, windows = [], {}
    for inst in candidates:
        if inst.kind == KIND_INDEX:
            windows[inst.pk] = (index_start, None)
        elif inst.pk in spans and (spans[inst.pk][1] is None or today <= spans[inst.pk][1]):
            windows[inst.pk] = spans[inst.pk]
        else:
            continue
        out.append(inst)
    return out, windows


def tracked_instruments(profile=None, ids=None, today=None):
    """Instruments worth fetching: those someone holds or held within their window (see ``tracked_with_windows``), plus the indices in use,
    with a fetch source and fetching switched on."""
    return tracked_with_windows(profile, ids, today)[0]


def clip(rows, window):
    """``rows`` (``[(date, close)]``) inside the window (its start less ``WINDOW_LEAD_DAYS``, up to its end)."""
    start, end = window if window else (None, None)
    lo = start - timedelta(days=WINDOW_LEAD_DAYS) if start else None
    return [(d, c) for d, c in rows if (lo is None or d >= lo) and (end is None or d <= end)]


def fetch_from(window, since, oldest=None):
    """The date to ask a source from: the day after what is stored, but never before the window opens (None: no limit, the default years).
    When the window opens more than ``WINDOW_LEAD_DAYS`` before the oldest stored price (a purchase back-dated before the history),
    the request goes back to the window's start to fill the older prices."""
    start = window[0] - timedelta(days=WINDOW_LEAD_DAYS) if window and window[0] else None
    if since is None:
        return start
    if start and oldest and start < oldest - timedelta(days=WINDOW_LEAD_DAYS):
        return start
    return max(since, start) if start else since


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


def first_api_date(instrument):
    return Price.objects.filter(instrument=instrument).order_by("date").values_list("date", flat=True).first()


def refetch_full(instrument, years=10, today=None, start=None):
    """Re-fetch a split-adjusted instrument's whole history and replace its fetched rows (the vendor restates the past after a split;
    plan 16.2). Uploaded rows are kept and counted so the person can be told they need re-uploading on the new basis.
    ``start`` (the window's start) limits the new history to the first purchase instead of ``years`` back; with none given the window is worked out."""
    uploads = Price.objects.filter(instrument=instrument, source="upload").count()
    window = None
    if start is None:
        window = fetch_window([instrument.pk], today).get(instrument.pk)
        start = fetch_from(window, None)
    result = yahoo.fetch(symbol_for(instrument, "yahoo"), start, years=years, today=today)
    if window:
        result.rows = clip(result.rows, window)
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
    # Profiles that log dividends automatically get theirs now; the others see them as suggestions to approve.
    try:
        from investments.services import dividends

        dividends.auto_log_for_instrument(instrument)
    except InvestmentsError:
        pass


def _record_splits(instrument, result, today, years, failures, window=None):
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
                refetch_full(instrument, years, today, fetch_from(window, None))
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

    tracked, windows = tracked_with_windows(profile, ids, today)
    instruments = [i for i in tracked if not helper.server_skips(i.price_source)][:max_symbols]
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
        failures, updated, read = [], 0, set()
        wanted = {i.pk: symbol_for(i, "amfi") for i in funds}
        try:
            found = amfi.fetch(list(wanted.values()))
            read.add("amfi")
        except FetchError as exc:
            found = {}
            failures.append(source_formats.failure(0, "AMFI daily file", exc))
        for inst in funds:
            summary["tried"] += 1
            code = wanted[inst.pk]
            if out_of_time():
                summary["stopped"] = "run-time cap reached"
                break
            try:
                last = last_api_date(inst)
                window = windows.get(inst.pk)
                start = fetch_from(window, last)
                # the history from mfapi.in: the first time, or after a gap (re-opened position). Not whenever the stored prices start after the
                # window: a scheme's own history may begin later, and that would call mfapi.in on every run
                if last is None or last < today - timedelta(days=WINDOW_LEAD_DAYS):
                    pause()
                    result = mfapi.fetch(symbol_for(inst, "mfapi"), start)
                    read.add("mfapi")
                    added, changed, _ = upsert_prices(inst, clip(result.rows, windows.get(inst.pk)), "api", "")
                    updated += 1 if added or changed else 0
                if code in found:
                    day, nav, _name, _isin = found[code]
                    added, changed, _ = upsert_prices(inst, clip([(day, nav)], windows.get(inst.pk)), "api", "")
                    updated += 1 if added or changed else 0
                elif not failures:
                    failures.append({"id": inst.pk, "name": inst.name, "error": "not in AMFI's file today"})
            except (FetchError, InvestmentsError) as exc:
                failures.append(source_formats.failure(inst.pk, inst.name, exc))
        run.tried, run.updated, run.failures, run.finished = len(funds), updated, failures, timezone.now()
        run.formats = sorted(read)
        run.save()
        summary["updated"] += updated
        summary["failures"] += failures
        summary["runs"].append(run.pk)

    # --- bhavcopy (owner request, November 2026): before Yahoo, or after it to fill what Yahoo missed (services/bhav.py)
    from investments.services import bhav

    bhav_mode = bhav.mode() if others else bhav.MODE_OFF
    all_others = list(others)

    def run_bhav():
        got = bhav.run(all_others, today=today, trigger=trigger, out_of_time=out_of_time, windows=windows)
        summary["updated"] += got["updated"]
        summary["failures"] += got["failures"]
        if got["run"] is not None:
            summary["runs"].append(got["run"].pk)
        return got

    if bhav_mode == bhav.MODE_FIRST and not out_of_time():
        covered = run_bhav()["covered"]
        others = [i for i in others if i.pk not in covered]

    # --- stocks, indices, foreign: Yahoo, one symbol at a time, spaced
    yahoo_failures = []
    if others:
        run = SourceRun(source="yahoo", trigger=trigger, started=timezone.now())
        failures, updated, tried, read = [], 0, 0, set()
        for inst in others:
            if out_of_time():
                summary["stopped"] = "run-time cap reached"
                break
            tried += 1
            summary["tried"] += 1
            pause()
            try:
                window = windows.get(inst.pk)
                since = fetch_from(window, last_api_date(inst), first_api_date(inst))
                result = yahoo.fetch(symbol_for(inst, "yahoo"), since, years=years, today=today)
                read.add("yahoo")
                result.rows = clip(result.rows, window)
                result.splits = [s for s in result.splits if clip([(s[0], 1)], window)]
                result.dividends = [x for x in result.dividends if clip([(x[0], 1)], window)]
                added, changed, _ = upsert_prices(inst, result.rows, "api", default_basis("yahoo"))
                updated += 1 if added or changed else 0
                if not result.rows:
                    failures.append({"id": inst.pk, "name": inst.name, "error": "no prices returned"})
                _record_splits(inst, result, today, years, failures, window)
                _record_dividends(inst, result)
                if result.rejected:
                    failures.append({"id": inst.pk, "name": inst.name, "error": f"{result.rejected} price(s) of zero or below were rejected"})
            except (FetchError, InvestmentsError) as exc:
                failures.append(source_formats.failure(inst.pk, inst.name, exc))
        run.tried, run.updated, run.failures, run.finished = tried, updated, failures, timezone.now()
        run.formats = sorted(read)
        run.message = summary["stopped"]
        run.save()
        summary["updated"] += updated
        summary["failures"] += failures
        summary["runs"].append(run.pk)
        yahoo_failures, yahoo_run = failures, run
    if bhav_mode == bhav.MODE_AFTER and not out_of_time():
        filled = run_bhav()["filled"]
        if any(f["id"] in filled for f in yahoo_failures):
            for failure in yahoo_failures:
                if failure["id"] in filled:
                    failure["error"] += " (filled from bhavcopy)"
            SourceRun.objects.filter(pk=yahoo_run.pk).update(failures=yahoo_failures)
    # the list of fund schemes, once a week (plan 6)
    from investments.services.instrument_search import lookup_enabled

    if ids is None and not out_of_time() and lookup_enabled():   # off: neither list is downloaded (AMFI NAV prices are fetched above, separately)
        from investments.services import schemes

        try:
            if schemes.refresh():
                source_formats.clear_failure("amfi_list", trigger)
        except FetchError as exc:
            summary["failures"].append(source_formats.failure(0, "AMFI scheme list", exc))
            if isinstance(exc, FormatError):
                source_formats.record_failure("amfi_list", "AMFI scheme list", exc, trigger)
        from investments.services import nse_list

        try:
            if nse_list.refresh():
                source_formats.clear_failure("nse_list", trigger)
        except FetchError as exc:
            summary["failures"].append(source_formats.failure(0, "NSE equity list", exc))
            if isinstance(exc, FormatError):
                source_formats.record_failure("nse_list", "NSE equity list", exc, trigger)
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


__all__ = ["fetch_prices", "update_plan", "upsert_prices", "refetch_full", "tracked_instruments", "tracked_with_windows", "fetch_window", "status_summary", "timedelta"]
