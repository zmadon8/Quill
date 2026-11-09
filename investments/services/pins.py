"""Pinned prices (plan 17.2): copies of the prices that reports depend on, kept outside the prunable table and inside the suite backup.

What is pinned: the Default Index (and the sectoral index of an investment while that switch is on) on the date of every
transaction, and, on every 31 March, the Default Index, the sectoral indices in use and the price of every investment held on that
date (the last trading day on or before 31 March). Dividend dates are not pinned (owner decision). Everything else comes from the
stored prices. A pin is made from stored prices only; it never invents a value. If a needed day is missing, the nightly step fetches it.
"""
import datetime
from datetime import date, timedelta

from django.db.models import Count

from investments.models import (
    KIND_INDEX, STATUS_FINAL, Instrument, InvestmentSettings, ManualPrice, PinnedPrice, Price, ProfileInvestment, Transaction,
)
from investments.services import prices

NEAR_DAYS = 5          # a stored close this close before the asked date is the "last trading day"; older is approximate


def index_ids_for(profile, txn_instrument_id=None):
    """The index instrument ids to pin for a transaction in ``profile``: the Default Index and, if switched on, the investment's sectoral index."""
    settings_row = InvestmentSettings.objects.filter(profile=profile).first()
    ids = set()
    default = settings_row.default_index_id if settings_row and settings_row.default_index_id else None
    if default is None:
        default = Instrument.objects.filter(profile=None, kind=KIND_INDEX, code="^NSEI").values_list("pk", flat=True).first()
    if default:
        ids.add(default)
    if settings_row and settings_row.sectoral_enabled and txn_instrument_id:
        sect = ProfileInvestment.objects.filter(profile=profile, instrument_id=txn_instrument_id).values_list("sectoral_index_id", flat=True).first()
        if sect:
            ids.add(sect)
    return ids


def _stored_before(instrument, day):
    """``(date, close, source)`` of the stored close on or before ``day`` (hand-entered wins a tie), without looking at pins."""
    found = prices.latest_prices([instrument.pk], day).get(instrument.pk)
    if not found:
        return None
    manual = ManualPrice.objects.filter(instrument=instrument, date=found[0]).exists()
    return found[0], found[1], "manual" if manual else Price.objects.filter(instrument=instrument, date=found[0]).values_list("source", flat=True).first()


def pin(instrument, asked, reason):
    """Make (or keep) the pin for ``asked``. Returns the PinnedPrice, or None when no stored price is early enough to use."""
    existing = PinnedPrice.objects.filter(instrument=instrument, asked_date=asked, reason=reason).first()
    found = _stored_before(instrument, asked)
    if found is None:
        return existing
    trading, close, source = found
    approximate = (asked - trading).days > NEAR_DAYS
    if existing and not existing.approximate:
        return existing
    if existing and existing.approximate and approximate and existing.trading_date >= trading:
        return existing
    obj, _ = PinnedPrice.objects.update_or_create(
        instrument=instrument, asked_date=asked, reason=reason,
        defaults={"trading_date": trading, "close": close, "basis": instrument.price_basis, "source": source or "api", "approximate": approximate})
    return obj


def pin_transaction(profile, txn):
    """Pin the index values on a transaction's date (called when a transaction is saved, edited or restored)."""
    made = []
    for iid in index_ids_for(profile, txn.instrument_id):
        inst = Instrument.objects.filter(pk=iid).first()
        if inst:
            made.append(pin(inst, txn.date, "transaction"))
    return made


def financial_year_ends(first, today):
    """Every 31 March from the first year containing ``first`` up to ``today`` (only dates that have passed)."""
    out, year = [], first.year if first.month >= 4 else first.year - 1
    year += 1                                    # the 31 March that ends the first financial year
    while date(year, 3, 31) <= today:
        out.append(date(year, 3, 31))
        year += 1
    return out


def expected_pins(until=None, today=None):
    """Yield ``(instrument, asked date, reason)`` for every pin the rules ask for, up to ``until`` (default: today).

    Held-on-31-March needs each profile's positions on that date, so the profiles' holdings are replayed once per year end."""
    from accounts.models import Profile
    from accounts.suite import KEY_INVESTMENTS

    today = today or date.today()
    until = until or today
    instruments = {i.pk: i for i in Instrument.objects.filter(kind=KIND_INDEX)}
    year_end_indices = set()
    seen = set()
    for profile in Profile.objects.filter(program=KEY_INVESTMENTS, deleted_at__isnull=True):
        txns = Transaction.objects.filter(profile=profile, status=STATUS_FINAL, units__isnull=False, date__lte=until)
        dates = txns.values("instrument_id", "date").annotate(n=Count("pk")).order_by()
        first = None
        for row in dates:
            first = row["date"] if first is None or row["date"] < first else first
        for d in sorted({r["date"] for r in dates}):
            for iid in index_ids_for(profile, None):
                key = (iid, d, "transaction")
                if key not in seen:
                    seen.add(key)
                    yield instruments.get(iid) or Instrument.objects.get(pk=iid), d, "transaction"
        if txns.exists():
            sect = set(ProfileInvestment.objects.filter(profile=profile).exclude(sectoral_index=None).values_list("sectoral_index_id", flat=True))
            # Units held on a date need no FIFO: total units are purchases (from their effective date) less sales, and a transfer nets to nil.
            moves = [(iid, day if side == "sell" else (allot or day), side, units) for iid, day, allot, side, units in
                     txns.values_list("instrument_id", "date", "allotment_date", "side", "units").iterator(chunk_size=1000)]
            for d in financial_year_ends(first, min(until, today)):
                ids = index_ids_for(profile, None) | sect
                net = {}
                for iid, eff, side, units in moves:
                    if eff <= d:
                        net[iid] = net.get(iid, 0) + (units if side == "buy" else -units)
                ids |= {iid for iid, n in net.items() if n > 0}
                for iid in ids:
                    key = (iid, d, "year_end")
                    if key not in seen:
                        seen.add(key)
                        yield instruments.get(iid) or Instrument.objects.get(pk=iid), d, "year_end"
    year_end_indices.clear()


def pin_all(until=None, today=None):
    """The nightly `pin_prices` step: make every pin the rules ask for that can be made from stored prices.
    Returns ``{"made": n, "already": n, "missing": [(name, date, reason)], "approximate": n}``."""
    made = already = approx = 0
    missing = []
    for inst, asked, reason in expected_pins(until, today):
        had = PinnedPrice.objects.filter(instrument=inst, asked_date=asked, reason=reason, approximate=False).exists()
        obj = pin(inst, asked, reason)
        if obj is None:
            missing.append((inst.name, asked, reason))
        elif had:
            already += 1
        else:
            made += 1
            approx += 1 if obj.approximate else 0
    return {"made": made, "already": already, "missing": missing, "approximate": approx}


def summary():
    """For the Admin page: counts by reason, approximate pins, and any pin the rules ask for that does not exist yet."""
    by_reason = dict(PinnedPrice.objects.values_list("reason").annotate(n=Count("pk")).order_by())
    missing = []
    for inst, asked, reason in expected_pins():
        if not PinnedPrice.objects.filter(instrument=inst, asked_date=asked, reason=reason).exists():
            missing.append((inst.name, asked, reason))
            if len(missing) >= 50:
                break
    return {"by_reason": by_reason, "total": sum(by_reason.values()), "approximate": PinnedPrice.objects.filter(approximate=True).count(),
            "missing": missing}


def blocked_instrument_ids(before):
    """Instruments that have a required pin (dated before ``before``) which does not exist: pruning must leave their history alone (plan 17.3)."""
    blocked = set()
    for inst, asked, reason in expected_pins(until=before - timedelta(days=1)):
        if inst.pk in blocked:
            continue
        if not PinnedPrice.objects.filter(instrument=inst, asked_date=asked, reason=reason).exists():
            blocked.add(inst.pk)
    return blocked


__all__ = ["pin", "pin_all", "pin_transaction", "summary", "expected_pins", "blocked_instrument_ids", "datetime"]
