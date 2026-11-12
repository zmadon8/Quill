"""Bhavcopy as a price source for Indian shares, ETFs and NSE indices (owner request, November 2026).

The nightly job (and the Update Prices button) can use the exchanges' daily files in one of two ways, chosen on Catalogue > Price sources:

* **After Yahoo** (``after``): Yahoo runs as before; then every NSE/BSE share and NSE index whose newest stored price is older than the
  newest bhavcopy is filled from the files. Yahoo's prices are never replaced.
* **Before Yahoo** (``first``): the files are read first and Yahoo is asked only for what they did not cover. Fewer Yahoo requests, but
  Yahoo's split and dividend reports are then seen only for those investments.

Bhavcopy closes are as traded. For the newest days that is the same figure as a split-adjusted close, so the files only ever fill recent
days (``LOOKBACK_DAYS``) of an investment that already has a price history, and never an investment with none (its history must come from
Yahoo or an upload first, or Yahoo would afterwards fetch only from the last bhavcopy day). A row from the Google Sheet (source ``helper``)
is replaced by the exchange's official close; any other stored row is left alone.

Codes: ``RELIANCE.NS`` is ``RELIANCE`` in NSE's file, ``500325.BO`` is scrip code 500325 in BSE's (``RELIANCE.BO``, symbol RELIANCE), and
the ISIN is a second key. An index is matched by its NSE name (``INDEX_NAMES``, else the investment's own name). A symbol set for the
source ``bhavcopy`` on the catalogue page replaces the code (for an index: the exact name in NSE's file, for example ``Nifty 50``).
"""
from datetime import timedelta

from django.db.models import Max
from django.utils import timezone

from investments.adapters import bhavcopy
from investments.adapters.base import FetchError
from investments.models import KIND_INDEX, KIND_SHARE, Price, SourceRun, SourceSetting, SourceSymbol

SETTING_KEY = "bhavcopy"
MODE_OFF, MODE_AFTER, MODE_FIRST = "off", "after", "first"
MODES = [
    (MODE_OFF, "Off"),
    (MODE_AFTER, "After Yahoo: fill what Yahoo missed"),
    (MODE_FIRST, "Before Yahoo: daily prices from bhavcopy, Yahoo for the rest"),
]
#: How far back the files fill (calendar days), and the most files of one kind read in one run.
LOOKBACK_DAYS = 14
MAX_FILES = 10
#: Weekdays tried without finding any file before the run says so (holidays alone never reach this).
NO_FILE_WARNING = 4

#: Yahoo codes of the built-in indices and their names in NSE's ``ind_close_all`` file. Sensex is a BSE index and is not in it.
INDEX_NAMES = {
    "^NSEI": "Nifty 50", "^NSMIDCP": "Nifty Next 50", "^NSEBANK": "Nifty Bank", "NIFTYMIDCAP150.NS": "Nifty Midcap 150",
    "NIFTYSMLCAP250.NS": "Nifty Smallcap 250", "^CNXIT": "Nifty IT", "^CNX100": "Nifty 100", "^CRSLDX": "Nifty 500",
    "^NSEMDCP50": "Nifty Midcap 50", "^CNXAUTO": "Nifty Auto", "^CNXFMCG": "Nifty FMCG", "^CNXPHARMA": "Nifty Pharma",
    "^CNXMETAL": "Nifty Metal", "^CNXREALTY": "Nifty Realty", "^CNXENERGY": "Nifty Energy", "^INDIAVIX": "India VIX",
}


def mode():
    value = SourceSetting.objects.filter(source=SETTING_KEY).values_list("fetch_mode", flat=True).first()
    return value if value in dict(MODES) else MODE_OFF


def set_mode(value):
    from investments.errors import InvestmentsError

    if value not in dict(MODES):
        raise InvestmentsError("BAD_CHOICE", "Choose off, after Yahoo or before Yahoo.")
    SourceSetting.objects.update_or_create(source=SETTING_KEY, defaults={"fetch_mode": value})


def keys_for(instrument, override=""):
    """``[(file kind, key)]`` to look the instrument up by, best first; empty when bhavcopy cannot price it."""
    code = (override or instrument.code or "").strip()
    isin = (instrument.isin or "").strip().upper()
    if instrument.kind == KIND_INDEX:
        names = [override, INDEX_NAMES.get((instrument.code or "").strip().upper()), instrument.name]
        out = []
        for name in names:
            key = ("nse_idx", ("name", name.strip().lower())) if name and name.strip() else None
            if key and key not in out:
                out.append(key)
        return out
    if instrument.kind != KIND_SHARE or (instrument.currency or "INR") != "INR":
        return []
    upper = code.upper()
    if upper.endswith(".BO"):
        base = upper[:-3]
        out = [("bse_eq", ("code", base)) if base.isdigit() else ("bse_eq", ("sym", base))]
        return out + ([("bse_eq", ("isin", isin))] if isin else [])
    if upper.endswith(".NS"):
        return [("nse_eq", ("sym", upper[:-3]))] + ([("nse_eq", ("isin", isin))] if isin else [])
    if isin.startswith("IN"):
        return [("nse_eq", ("isin", isin))]
    return []


def eligible(instruments):
    """``[(instrument, keys)]`` for the instruments bhavcopy can price."""
    ids = [i.pk for i in instruments]
    overrides = dict(SourceSymbol.objects.filter(instrument_id__in=ids, source=SETTING_KEY).values_list("instrument_id", "symbol"))
    out = []
    for inst in instruments:
        keys = keys_for(inst, overrides.get(inst.pk, ""))
        if keys:
            out.append((inst, keys))
    return out


def _weekdays(newest, oldest):
    day = newest
    while day >= oldest:
        if day.weekday() < 5:
            yield day
        day -= timedelta(days=1)


def _read(kind, body, wanted):
    lines = bhavcopy.lines_of(kind, body)
    if kind == "nse_idx":
        return {("name", name): value for name, value in bhavcopy.read_indices(lines, [k[1] for k in wanted]).items()}
    return bhavcopy.read_equity(lines, symbols=[k[1] for k in wanted if k[0] == "sym"], isins=[k[1] for k in wanted if k[0] == "isin"],
                                codes=[k[1] for k in wanted if k[0] == "code"], nse=kind != "bse_eq")


def run(instruments, *, today, trigger="cron", out_of_time=lambda: False, windows=None):
    """Fill recent days from the files. Returns ``{"tried", "updated", "failures", "covered", "filled", "run"}``: ``covered`` is the ids
    whose newest stored price is now the newest file's day, ``filled`` the ids that got at least one new price. ``windows`` is
    ``{id: (start, end)}`` from ``fetch.tracked_with_windows``: a price outside its window is not stored."""
    from investments.services import fetch

    result = {"tried": 0, "updated": 0, "failures": [], "covered": set(), "filled": set(), "run": None}
    targets = eligible(instruments)
    if not targets:
        return result
    ids = [i.pk for i, _ in targets]
    has_history = set(Price.objects.filter(instrument_id__in=ids).values_list("instrument_id", flat=True).distinct())
    oldest_allowed = today - timedelta(days=LOOKBACK_DAYS)
    # "up to date" is measured on the official prices only, so a day the Google Sheet filled is still replaced by the exchange's close
    official = dict(Price.objects.filter(instrument_id__in=ids).exclude(source="helper").values_list("instrument_id").annotate(m=Max("date")).order_by())
    last = {iid: official.get(iid, oldest_allowed - timedelta(days=1)) for iid in has_history}
    failures = result["failures"]
    needing = []
    for inst, keys in targets:
        if inst.pk not in has_history:
            failures.append({"id": inst.pk, "name": inst.name, "error": "bhavcopy: no price history yet (Yahoo or an upload must load it first)"})
        elif last[inst.pk] < today:
            needing.append((inst, keys))
    result["tried"] = len(needing)
    started = timezone.now()
    if not needing:
        if failures:
            result["run"] = SourceRun.objects.create(source="bhavcopy", trigger=trigger, started=started, finished=timezone.now(), failures=failures)
        return result
    oldest = max(oldest_allowed, min(last[i.pk] for i, _ in needing) + timedelta(days=1))
    days = list(_weekdays(today, oldest))

    # one pass per file kind, newest day first; each file is read once, keeping only the rows asked for
    files, newest = {}, {}
    for kind in bhavcopy.KINDS:
        wanted = {key for _inst, keys in needing for k, key in keys if k == kind}
        if not wanted:
            continue
        got, tried = {}, 0
        for day in days:
            if out_of_time() or len(got) >= MAX_FILES:
                break
            tried += 1
            try:
                body = bhavcopy.download(kind, day)
                if body is None:
                    continue
                got[day] = _read(kind, body, wanted)
            except FetchError as exc:
                failures.append({"id": 0, "name": bhavcopy.label(kind), "error": str(exc)})
                break
        if got:
            files[kind], newest[kind] = got, max(got)
        elif tried >= NO_FILE_WARNING and not any(f["name"] == bhavcopy.label(kind) for f in failures):
            failures.append({"id": 0, "name": bhavcopy.label(kind), "error": f"no file for any of the last {tried} weekdays (the address may have changed, "
                                                                            "or the exchange is refusing downloads from this server)"})

    existing = {}
    for iid, day, source in Price.objects.filter(instrument_id__in=[i.pk for i, _ in needing], date__gte=oldest).values_list("instrument_id", "date", "source"):
        existing[(iid, day)] = source
    for inst, keys in needing:
        rows = {}
        for kind, key in keys:                          # the first key that has a day wins for that day
            for found in files.get(kind, {}).values():
                if key in found:
                    day, close = found[key]
                    rows.setdefault(day, close)
        kinds = {kind for kind, _key in keys if kind in newest}
        if not kinds:
            continue                                    # no file of its kind was found; said once above
        latest_file = max(newest[k] for k in kinds)
        # an empty day or a Google Sheet day in the window; a fetched or uploaded price is never replaced
        fill = [(day, close) for day, close in fetch.clip(sorted(rows.items()), (windows or {}).get(inst.pk))
                if existing.get((inst.pk, day), "helper") == "helper"]
        if fill:
            try:
                added, changed, _kept = fetch.upsert_prices(inst, fill, "api", inst.price_basis)
            except Exception as exc:                    # a basis refusal or the like: report it, carry on with the others
                failures.append({"id": inst.pk, "name": inst.name, "error": f"bhavcopy: {getattr(exc, 'message', exc)}"})
                continue
            if added or changed:
                result["updated"] += 1
                result["filled"].add(inst.pk)
        if (rows and max(rows) >= latest_file) or last[inst.pk] >= latest_file:
            result["covered"].add(inst.pk)
        elif not rows:
            kind = next(k for k, _key in keys if k in newest)
            failures.append({"id": inst.pk, "name": inst.name,
                             "error": f"not in the {bhavcopy.label(kind)} of {latest_file:%d %b %Y} (check its code, or set a 'bhavcopy' symbol on its catalogue page)"})
    message = "newest file: " + ", ".join(f"{bhavcopy.label(k)} {d:%d %b %Y}" for k, d in sorted(newest.items())) if newest else "no file found"
    result["run"] = SourceRun.objects.create(source="bhavcopy", trigger=trigger, started=started, finished=timezone.now(), tried=len(needing),
                                             updated=result["updated"], failures=failures, message=message[:300])
    return result                                       # the caller bumps the price version


def eligible_count():
    from investments.services import fetch

    return len(eligible(fetch.tracked_instruments()))
