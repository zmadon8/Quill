"""Pruning of old daily prices (plan 17.3): automatic, on by default, with the cutoff 5 years back; an Admin can change or switch it off.

Daily prices older than the cutoff become one figure per month, the last trading day of the month, for every instrument and index and
every source. Pinned prices are never touched (they live in their own table, and a stored price on a pinned date is kept too).
Safeguards: a preview on the Admin page; `prune_prices` declines any instrument for which a required pin is missing; it runs only after
a good backup (last link of the cron `&&` chain, and it checks today's backup itself); deletes are done in chunks of about 5,000 with a
time limit. The first-run "download a full archive and tick that you keep it" confirmation was dropped for the automatic mode: pruning is
the requested default, the nightly backup runs first, and the full archive stays one click away on the Admin page.
"""
import time
from datetime import date

from django.db.models import Max
from django.utils import timezone

from investments.errors import InvestmentsError
from investments.models import PinnedPrice, Price, PriceHistorySettings, PriceMaintenanceLog
from investments.services import pins

CHUNK = 5000
MIN_YEARS = 2
BYTES_PER_ROW = 110         # rough size of one price row with its index, for the "space freed" figure


def get_settings():
    obj, _ = PriceHistorySettings.objects.get_or_create(pk=1)
    return obj


def cutoff_date(years, today=None):
    today = today or date.today()
    try:
        return today.replace(year=today.year - years)
    except ValueError:                  # 29 February
        return today.replace(year=today.year - years, day=28)


def keepers(before, instrument_id=None):
    """The ``(instrument id, date)`` pairs that stay: the last stored day of each month before ``before``."""
    qs = Price.objects.filter(date__lt=before)
    if instrument_id:
        qs = qs.filter(instrument_id=instrument_id)
    rows = qs.values("instrument_id", "date__year", "date__month").annotate(last=Max("date")).order_by()
    return {(r["instrument_id"], r["last"]) for r in rows}


def preview(years=None, today=None):
    """What pruning would do now: rows to remove, rows left, approximate space freed, date range affected (plan 17.3 safeguard 1)."""
    cfg = get_settings()
    years = years or cfg.years_kept
    before = cutoff_date(years, today)
    old = Price.objects.filter(date__lt=before)
    old_count = old.count()
    month_ends = keepers(before)
    pinned = set(PinnedPrice.objects.values_list("instrument_id", "trading_date"))
    pinned_kept = Price.objects.filter(date__lt=before).values_list("instrument_id", "date")
    kept = len(month_ends | {pair for pair in pinned_kept if pair in pinned})
    total = Price.objects.count()
    first = old.order_by("date").values_list("date", flat=True).first()
    remove = max(0, old_count - kept)
    return {"cutoff": before, "remove": remove, "remain": total - remove, "freed_bytes": remove * BYTES_PER_ROW, "first": first, "years": years}


def configure(user, *, prune_live, prune_archive, years, full_archive_confirmed=False):
    """Change the switches. No confirmation is needed to turn pruning on (it is on by default); the tick is only recorded."""
    if years < MIN_YEARS:
        raise InvestmentsError("BAD_NUMBER", f"Keep at least {MIN_YEARS} years in full daily detail (alerts, the 52-week range and short charts need it).")
    cfg = get_settings()
    cfg.prune_live = bool(prune_live)
    cfg.prune_archive = bool(prune_archive or prune_live)     # if the live database is pruned the archive necessarily is too
    cfg.years_kept = years
    cfg.full_archive_confirmed = cfg.full_archive_confirmed or bool(full_archive_confirmed)
    cfg.save()
    return cfg


def _log(ok, message, counts=None):
    PriceMaintenanceLog.objects.create(kind="prune", ok=ok, message=message[:300], counts=counts or {})


def prune_prices(*, today=None, max_seconds=300, clock=time.monotonic, require_backup=True):
    """The `prune_prices` step. Returns ``(status, removed)`` where status is "off", "declined", "nothing", "done" or "time"; never raises
    for a normal refusal (the command then exits 0)."""
    cfg = get_settings()
    if not cfg.prune_live:
        return "off", 0
    if require_backup:
        from accounts.purge import todays_backup_ok

        if not todays_backup_ok():
            _log(False, "Pruning declined: no successful backup was taken today.")
            return "declined", 0
    before = cutoff_date(cfg.years_kept, today)
    blocked = pins.blocked_instrument_ids(before)
    started = clock()
    removed = 0
    status = "nothing"
    instrument_ids = list(Price.objects.filter(date__lt=before).values_list("instrument_id", flat=True).distinct())
    declined = [i for i in instrument_ids if i in blocked]
    for iid in instrument_ids:
        if iid in blocked:
            continue
        keep = {d for (_i, d) in keepers(before, iid)}
        keep |= set(PinnedPrice.objects.filter(instrument_id=iid).values_list("trading_date", flat=True))     # a pinned day is never thinned
        doomed = list(Price.objects.filter(instrument_id=iid, date__lt=before).exclude(date__in=keep).values_list("pk", flat=True))
        for start in range(0, len(doomed), CHUNK):
            Price.objects.filter(pk__in=doomed[start:start + CHUNK]).delete()
            removed += len(doomed[start:start + CHUNK])
            if clock() - started > max_seconds:
                status = "time"
                break
        if status == "time":
            break
    if status != "time":
        status = "done" if removed else ("declined" if declined else "nothing")
    cfg.last_prune_at = timezone.now()
    cfg.save(update_fields=["last_prune_at"])
    _log(True, f"Pruning {status}: {removed} rows removed" + (f"; {len(declined)} instrument(s) left alone because a required pin is missing" if declined else ""),
         {"removed": removed, "declined": len(declined)})
    if removed:
        from investments.services import fetch

        fetch.bump_version()
    return status, removed


def apply_to_rows(rows, cutoff):
    """For the archive: of ``rows`` (``[(date, close, ...)]`` oldest first, one instrument) keep recent days and one per month before ``cutoff``."""
    out, last_in_month = [], {}
    for row in rows:
        if row[0] >= cutoff:
            out.append(row)
        else:
            last_in_month[(row[0].year, row[0].month)] = row
    pruned = sorted(last_in_month.values(), key=lambda r: r[0])
    return pruned + out
