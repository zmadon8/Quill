"""The Admin investment catalogue (plan section 21.1): shared investments and their price histories, for every profile.

Transaction details are never part of it. What an Admin sees about holders is profile *names* only. Every change is written to the
permanent `CatalogueHistory`. A price an Admin edits or adds becomes a hand-entered (`ManualPrice`) row, which the nightly fetch never
overwrites; a deleted price can be put back from the log. Structural operations (merge, change of price basis, delete) take a
"Before changing the catalogue" backup first and are refused if that backup cannot be made.
"""
import datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Max, Q

from investments.errors import InvestmentsError, forbidden, not_found
from investments.models import (
    AltValue, CatalogueHistory, Folio, Instrument, InvestmentSettings, ManualPrice, PinnedPrice, Price, ProfileInvestment, SourceSymbol,
    SplitSignal, Transaction, Transfer,
)
from investments.services import fetch, prices

PAGE = 50
EDITABLE = ("name", "code", "isin", "exchange", "currency", "asset_class", "sector", "price_source", "fallback_source", "fetch_enabled", "latest_pe",
            "next_results_date")


def require_admin(user):
    if not getattr(user, "is_admin", False):
        raise forbidden("Only an Admin can use the catalogue.")


def log(user, instrument, record_type, record_id=None, field="", old="", new="", reason=""):
    return CatalogueHistory.objects.create(
        by=user if getattr(user, "pk", None) else None, instrument_id_ref=instrument.pk if instrument else None,
        instrument_name=instrument.name if instrument else "", record_type=record_type, record_id=record_id, field=field,
        old="" if old is None else str(old), new="" if new is None else str(new), reason=(reason or "")[:300])


# ---------------------------------------------------------------- reading

def holder_profiles(instrument):
    """Names of the profiles that hold or have held ``instrument``. No units, costs, dates or values (plan 21.1)."""
    from accounts.models import Profile

    ids = set(ProfileInvestment.objects.filter(instrument=instrument).values_list("profile_id", flat=True))
    ids |= set(Transaction.objects.filter(instrument=instrument).values_list("profile_id", flat=True))
    ids |= set(Transfer.objects.filter(instrument=instrument).values_list("profile_id", flat=True))
    return list(Profile.objects.filter(pk__in=ids).order_by("name").values_list("name", flat=True))


def holder_count(instrument):
    return len(holder_profiles(instrument))


def affected_profiles(instrument):
    """How many profiles a change to this shared investment affects (shown before saving)."""
    return holder_count(instrument)


def listing(*, q="", kind="", source="", flag="", today=None):
    """Shared investments with the counts the list shows. Flags: stale, failing, split, move, duplicate."""
    today = today or datetime.date.today()
    qs = Instrument.objects.filter(profile=None).annotate(rows=Count("prices", distinct=True), last=Max("prices__date"))
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q) | Q(isin__icontains=q))
    if kind:
        qs = qs.filter(kind=kind)
    if source:
        qs = qs.filter(price_source=source)
    items = list(qs.order_by("name", "id"))
    ids = [i.pk for i in items]
    holders = {}
    for iid, pid in ProfileInvestment.objects.filter(instrument_id__in=ids).values_list("instrument_id", "profile_id"):
        holders.setdefault(iid, set()).add(pid)
    for iid, pid in Transaction.objects.filter(instrument_id__in=ids).values_list("instrument_id", "profile_id").distinct():
        holders.setdefault(iid, set()).add(pid)
    split_ids = set(SplitSignal.objects.filter(instrument_id__in=ids).values_list("instrument_id", flat=True))
    failing = set()
    from investments.models import SourceRun
    latest = {}
    for run in SourceRun.objects.exclude(finished=None).order_by("-finished")[:100]:
        latest.setdefault(run.source, run)
    for run in latest.values():
        failing |= {f.get("id") for f in run.failures if f.get("id")}
    seen_codes = {}
    for inst in items:
        key = (inst.kind, (inst.code or "").upper())
        if inst.code:
            seen_codes.setdefault(key, []).append(inst.pk)
    out = []
    for inst in items:
        inst.holders = len(holders.get(inst.pk, ()))
        inst.flags = []
        last = inst.last
        if inst.rows and last and (today - last).days > fetch.STALE_DAYS and inst.price_source not in ("manual",):
            inst.flags.append("stale")
        if inst.pk in failing:
            inst.flags.append("failing")
        if inst.pk in split_ids:
            inst.flags.append("split")
        if inst.code and len(seen_codes.get((inst.kind, inst.code.upper()), ())) > 1:
            inst.flags.append("duplicate")
        if flag and flag not in inst.flags:
            continue
        out.append(inst)
    return out


def price_rows(instrument, start=None, end=None, page=1):
    """One page (50) of the merged price history with the source of each, newest first, plus the page count."""
    manual = {d: (c, n) for d, c, n in ManualPrice.objects.filter(instrument=instrument).values_list("date", "close", "note")}
    fetched = {d: (c, s) for d, c, s in Price.objects.filter(instrument=instrument).values_list("date", "close", "source")}
    days = sorted(set(manual) | set(fetched), reverse=True)
    if start:
        days = [d for d in days if d >= start]
    if end:
        days = [d for d in days if d <= end]
    pages = max(1, -(-len(days) // PAGE))
    page = min(max(1, page), pages)
    chunk = days[(page - 1) * PAGE:page * PAGE]
    pinned = set(PinnedPrice.objects.filter(instrument=instrument, trading_date__in=chunk).values_list("trading_date", flat=True))
    rows = []
    for d in chunk:
        if d in manual:
            close, source = manual[d][0], "manual"
        else:
            close, source = fetched[d]
        rows.append({"date": d, "close": close, "source": source, "pinned": d in pinned})
    # highlight a one-day move of more than 40 percent that then recovers (plan 21.1)
    ordered = sorted(rows, key=lambda r: r["date"])
    for i, row in enumerate(ordered):
        row["odd"] = False
        if 0 < i < len(ordered) - 1:
            before, after = ordered[i - 1]["close"], ordered[i + 1]["close"]
            if before and abs(row["close"] - before) / before > Decimal("0.4") and abs(after - before) / before < Decimal("0.2"):
                row["odd"] = True
    return rows, page, pages, len(days)


# ---------------------------------------------------------------- shared details

@transaction.atomic
def update_details(user, instrument, reason="", **values):
    require_admin(user)
    if instrument.profile_id is not None:
        raise not_found("shared investment")
    unknown = set(values) - set(EDITABLE)
    if unknown:
        raise InvestmentsError("BAD_FIELD", f"Cannot change: {', '.join(sorted(unknown))}.")
    changed = 0
    for key, value in values.items():
        old = getattr(instrument, key)
        if old != value:
            setattr(instrument, key, value)
            log(user, instrument, "instrument", instrument.pk, key, old, value, reason)
            changed += 1
    if changed:
        instrument.save()
        fetch.bump_version()
    return changed


@transaction.atomic
def set_source_symbol(user, instrument, source, symbol, reason=""):
    require_admin(user)
    symbol = (symbol or "").strip()
    row = SourceSymbol.objects.filter(instrument=instrument, source=source).first()
    old = row.symbol if row else ""
    if not symbol:
        if row:
            row.delete()
            log(user, instrument, "symbol", None, source, old, "", reason)
        return None
    if row is None:
        row = SourceSymbol(instrument=instrument, source=source)
    row.symbol = symbol
    row.verified_on = None
    row.save()
    if old != symbol:
        log(user, instrument, "symbol", row.pk, source, old, symbol, reason)
    return row


# ---------------------------------------------------------------- prices

def _pins_on(instrument, day):
    return PinnedPrice.objects.filter(instrument=instrument, trading_date=day)


@transaction.atomic
def set_price(user, instrument, day, close, reason=""):
    """Edit or add a price: it becomes a hand-entered row that the nightly update never overwrites; the original is kept in the log."""
    require_admin(user)
    close = Decimal(str(close).replace(",", "").strip()).quantize(Decimal("0.0001"))
    if close <= 0:
        raise InvestmentsError("BAD_NUMBER", "A price must be more than zero.")
    old = prices.series(instrument, day, day)
    old_value = old[0][1] if old else None
    ManualPrice.objects.update_or_create(instrument=instrument, date=day, defaults={"close": close, "note": "Admin", "entered_by": user})
    pins = _pins_on(instrument, day)
    pins_changed = pins.update(close=close, source="manual") if pins.exists() else 0
    log(user, instrument, "price", None, str(day), old_value, close, reason + (f" (updated {pins_changed} pinned price)" if pins_changed else ""))
    fetch.bump_version()
    return pins_changed


@transaction.atomic
def delete_price(user, instrument, day, reason=""):
    require_admin(user)
    old = prices.series(instrument, day, day)
    if not old:
        raise not_found("price")
    ManualPrice.objects.filter(instrument=instrument, date=day).delete()
    Price.objects.filter(instrument=instrument, date=day).delete()
    log(user, instrument, "price_deleted", None, str(day), old[0][1], "", reason)
    fetch.bump_version()


@transaction.atomic
def restore_price(user, log_id):
    """Put a deleted price back from the log."""
    require_admin(user)
    row = CatalogueHistory.objects.filter(pk=log_id, record_type="price_deleted").first()
    inst = Instrument.objects.filter(pk=row.instrument_id_ref).first() if row else None
    if row is None or inst is None:
        raise not_found("change")
    day = datetime.date.fromisoformat(row.field)
    if prices.series(inst, day, day):
        raise InvestmentsError("EXISTS", "There is a price for that day again, so nothing was restored.", 409)
    ManualPrice.objects.create(instrument=inst, date=day, close=Decimal(row.old), note="Restored", entered_by=user)
    log(user, inst, "price", None, str(day), "", row.old, f"restored from change {row.pk}")
    fetch.bump_version()


@transaction.atomic
def refetch_range(user, instrument, start, end):
    """Fetch a date range again from the source and replace the fetched rows in it (never uploaded or hand-entered ones)."""
    require_admin(user)
    from investments.adapters import mfapi, yahoo
    from investments.services import locks

    if instrument.price_source not in ("yahoo", "amfi", "mfapi"):
        raise InvestmentsError("NO_SOURCE", "This investment has no automatic price source.", 409)
    with locks.heavy("price_import"):
        if instrument.price_source == "yahoo":
            result = yahoo.fetch(fetch.symbol_for(instrument, "yahoo"), start, years=30)
        else:
            result = mfapi.fetch(fetch.symbol_for(instrument, "mfapi"), start)
        rows = [(d, c) for d, c in result.rows if start <= d <= end]
        Price.objects.filter(instrument=instrument, date__range=(start, end), source__in=["api", "helper"]).delete()
        added, _changed, kept = fetch.upsert_prices(instrument, rows, "api", fetch.default_basis(instrument.price_source))
    log(user, instrument, "refetch", None, f"{start}..{end}", "", f"{added} rows", f"{kept} uploaded rows kept")
    fetch.bump_version()
    return added


# ---------------------------------------------------------------- structural operations (each after a backup)

def _backup(user):
    from backups import services as backup_services

    try:
        return backup_services.create_backup("pre_catalogue", user)
    except Exception as exc:
        raise InvestmentsError("BACKUP_FAILED", f"The safety backup could not be made, so nothing was changed. ({exc})", 500)


def merge_preview(keep, drop):
    """Counts per profile only (plan 21.1), and the reason a merge is refused if it is."""
    problems = []
    if keep.pk == drop.pk:
        problems.append("Choose two different investments.")
    for inst in (keep, drop):
        if inst.profile_id is not None:
            problems.append(f"{inst.name} is a private alternative investment, which is not in the catalogue.")
    if keep.kind != drop.kind:
        problems.append("They are different types of investment.")
    if keep.currency != drop.currency:
        problems.append("They are priced in different currencies.")
    per_profile = {}
    from accounts.models import Profile
    names = dict(Profile.objects.values_list("pk", "name"))
    for pid, n in Transaction.objects.filter(instrument=drop).values_list("profile_id").annotate(n=Count("pk")).order_by():
        per_profile[names.get(pid, pid)] = per_profile.get(names.get(pid, pid), 0) + n
    prices_moved = Price.objects.filter(instrument=drop).exclude(date__in=Price.objects.filter(instrument=keep).values("date")).count()
    return {"problems": problems, "per_profile": per_profile, "prices_moved": prices_moved,
            "folios": Folio.objects.filter(instrument=drop).count()}


@transaction.atomic
def merge(user, keep, drop, reason=""):
    """Merge two entries for the same investment: every profile's records move to ``keep``; prices are combined with ``keep``'s rows
    winning a clash; pins and symbols carry over. Merging only adds units to buckets, so no selling limit can break."""
    require_admin(user)
    preview = merge_preview(keep, drop)
    if preview["problems"]:
        raise InvestmentsError("CANNOT_MERGE", " ".join(preview["problems"]), 409)
    _backup(user)
    # folios: same (profile, portfolio, number) on both sides become one
    for folio in Folio.objects.filter(instrument=drop):
        twin = Folio.objects.filter(profile=folio.profile, instrument=keep, portfolio=folio.portfolio, number=folio.number).first()
        if twin:
            Transaction.objects.filter(folio=folio).update(folio=twin)
            Transfer.objects.filter(from_folio=folio).update(from_folio=twin)
            Transfer.objects.filter(to_folio=folio).update(to_folio=twin)
            folio.delete()
        else:
            folio.instrument = keep
            folio.save(update_fields=["instrument"])
    Transaction.objects.filter(instrument=drop).update(instrument=keep)
    Transfer.objects.filter(instrument=drop).update(instrument=keep)
    for av in AltValue.objects.filter(instrument=drop):
        av.instrument = keep
        av.save(update_fields=["instrument"])
    for pi in ProfileInvestment.objects.filter(instrument=drop):
        twin = ProfileInvestment.objects.filter(profile=pi.profile, instrument=keep).first()
        if twin:
            twin.hidden = twin.hidden and pi.hidden
            twin.notes = "\n".join(x for x in (twin.notes, pi.notes) if x)
            twin.links = list({l["url"]: l for l in (twin.links + pi.links)}.values())
            twin.sectoral_index_id = twin.sectoral_index_id or pi.sectoral_index_id
            twin.save()
            pi.delete()
        else:
            pi.instrument = keep
            pi.save(update_fields=["instrument"])
    for model in (ManualPrice, Price, PinnedPrice):
        clash_field = {"ManualPrice": "date", "Price": "date", "PinnedPrice": "asked_date"}[model.__name__]
        for row in model.objects.filter(instrument=drop):
            exists = model.objects.filter(instrument=keep, **{clash_field: getattr(row, clash_field)}, **({"reason": row.reason} if model is PinnedPrice else {})).exists()
            if exists:
                row.delete()
            else:
                row.instrument = keep
                row.save(update_fields=["instrument"])
    for sym in SourceSymbol.objects.filter(instrument=drop):
        if SourceSymbol.objects.filter(instrument=keep, source=sym.source).exists():
            sym.delete()
        else:
            sym.instrument = keep
            sym.save(update_fields=["instrument"])
    SplitSignal.objects.filter(instrument=drop).exclude(ex_date__in=SplitSignal.objects.filter(instrument=keep).values("ex_date")).update(instrument=keep)
    InvestmentSettings.objects.filter(default_index=drop).update(default_index=keep)
    ProfileInvestment.objects.filter(sectoral_index=drop).update(sectoral_index=keep)
    log(user, keep, "merge", drop.pk, "instrument", drop.name, keep.name, reason)
    drop.delete()
    fetch.bump_version()
    return keep


def basis_preview(instrument):
    return {"fetched": Price.objects.filter(instrument=instrument, source__in=["api", "helper"]).count(),
            "uploaded": Price.objects.filter(instrument=instrument, source="upload").count()}


@transaction.atomic
def change_basis(user, instrument, new_basis, reason=""):
    """Change the price basis (raw / split-adjusted). Fetched rows are dropped and fetched again; uploaded rows stay and are counted so
    they can be re-uploaded on the new basis (plan 16.2)."""
    require_admin(user)
    if new_basis not in ("", "raw", "split_adjusted"):
        raise InvestmentsError("BAD_CHOICE", "Choose raw, split-adjusted or none.")
    if new_basis == instrument.price_basis:
        return {"refetched": 0, "uploaded": basis_preview(instrument)["uploaded"]}
    _backup(user)
    old = instrument.price_basis
    Price.objects.filter(instrument=instrument, source__in=["api", "helper"]).delete()
    instrument.price_basis = new_basis
    instrument.save(update_fields=["price_basis"])
    Price.objects.filter(instrument=instrument, source="upload").update(basis=new_basis)
    refetched = 0
    if instrument.price_source == "yahoo":
        try:
            fetch.refetch_full(instrument)
            refetched = Price.objects.filter(instrument=instrument).count()
        except Exception:
            refetched = 0          # the nightly job or the Update Prices button fetches it again
    log(user, instrument, "instrument", instrument.pk, "price_basis", old, new_basis, reason)
    fetch.bump_version()
    return {"refetched": refetched, "uploaded": Price.objects.filter(instrument=instrument, source="upload").count()}


def _is_builtin_index(instrument):
    from investments.models import KIND_INDEX
    from investments.services.masters import BUILTIN_INDICES

    return instrument.kind == KIND_INDEX and instrument.code in {code for _name, code in BUILTIN_INDICES}


def _profiles_using(instrument):
    """The ids of every profile with anything about this investment: records, schedules, its own row, guardrails,
    confirmations, saved alert states, or the investment chosen as its Default Index or a sectoral index."""
    from investments.models import CorporateActionResponse, Dividend, Guardrail, SipSchedule
    from investments.services.masters import alert_states_of

    ids = set()
    for model in (Transaction, Transfer, Dividend, SipSchedule, Folio, AltValue, Guardrail, ProfileInvestment):
        ids |= set(model.objects.filter(instrument=instrument).values_list("profile_id", flat=True))
    ids |= set(CorporateActionResponse.objects.filter(action__instrument=instrument).values_list("profile_id", flat=True))
    ids |= set(alert_states_of(instrument).values_list("profile_id", flat=True))
    ids |= set(InvestmentSettings.objects.filter(default_index=instrument).values_list("profile_id", flat=True))
    ids |= set(ProfileInvestment.objects.filter(sectoral_index=instrument).values_list("profile_id", flat=True))
    return ids


def delete_preview(instrument):
    """What deleting this shared investment removes: per profile, counts only (plan 21.1: no units, costs or dates), and the
    shared price history. ``problems`` says why it cannot be deleted at all."""
    from accounts.models import Profile
    from investments.services.masters import records_of

    problems = []
    if instrument.profile_id is not None:
        problems.append("This is a private alternative investment, which is not in the catalogue.")
    if _is_builtin_index(instrument):
        problems.append("This is one of the built-in indices, which the program needs (it would be put back at once). "
                        "It cannot be deleted.")
    per_profile = []
    for p in Profile.objects.filter(pk__in=_profiles_using(instrument)).order_by("name"):
        counts = records_of(p, instrument)
        per_profile.append({"name": p.name, "counts": counts, "records": sum(counts.values()),
                            "default_index": InvestmentSettings.objects.filter(profile=p, default_index=instrument).exists(),
                            "sectoral": ProfileInvestment.objects.filter(profile=p, sectoral_index=instrument).count()})
    return {
        "problems": problems,
        "per_profile": per_profile,
        "records": sum(row["records"] for row in per_profile),
        "prices": Price.objects.filter(instrument=instrument).count(),
        "manual_prices": ManualPrice.objects.filter(instrument=instrument).count(),
        "pins": PinnedPrice.objects.filter(instrument=instrument).count(),
    }


@transaction.atomic
def delete_instrument(user, instrument, reason="", confirm_name=None):
    """Delete a shared investment from the catalogue, with everything every profile recorded against it.

    Refused for a private investment and for the built-in indices. While any profile has anything about it, the Admin must
    type its name exactly. A "Before changing the catalogue" backup is taken first and nothing is deleted if it fails. Each
    profile's records are written to that profile's permanent history before they go, the change is logged in the
    catalogue history, a profile that used it as its Default Index falls back to the standard one, and every affected
    profile's figures are recomputed."""
    require_admin(user)
    if instrument.profile_id is not None:
        raise not_found("shared investment")
    if _is_builtin_index(instrument):
        raise InvestmentsError("BUILTIN", "The built-in indices cannot be deleted.", 409)
    from accounts.models import Profile
    from investments.models import new_group
    from investments.services import core
    from investments.services.masters import delete_profile_records

    profile_ids = _profiles_using(instrument)
    if profile_ids and (confirm_name or "").strip() != instrument.name:
        raise InvestmentsError("CONFIRM_NAME", "Type the investment's name exactly to confirm.", 400)
    _backup(user)
    profiles = list(Profile.objects.filter(pk__in=profile_ids))
    summary = f"Deleted with investment {instrument.name} (Settings > Catalogue)"
    for p in profiles:
        delete_profile_records(p, user, instrument, new_group(), summary)
    log(user, instrument, "instrument_deleted", instrument.pk, "name", instrument.name,
        f"{len(profiles)} profile(s) affected" if profiles else "", reason)
    instrument.delete()   # prices, pins, symbols, signals and corporate actions go with it; Default and sectoral index choices are cleared
    for p in profiles:
        core.touch(p)
    fetch.bump_version()
    return {"profiles": len(profiles)}


@transaction.atomic
def create_instrument(user, **values):
    """Add a shared investment from the catalogue."""
    require_admin(user)
    from investments.models import HOLDABLE_KINDS, KIND_INDEX

    kind = values.get("kind")
    if kind not in HOLDABLE_KINDS and kind != KIND_INDEX:
        raise InvestmentsError("BAD_KIND", "Choose a type.")
    if kind == "alternative":
        raise InvestmentsError("BAD_KIND", "Alternative investments are private to a profile, so they are added there.")
    name = " ".join((values.get("name") or "").split())
    if not name:
        raise InvestmentsError("REQUIRED", "Name is required.")
    source = values.get("price_source") or fetch.default_source(kind)
    inst = Instrument.objects.create(profile=None, name=name, kind=kind, code=(values.get("code") or "").strip(), isin=(values.get("isin") or "").strip().upper(),
                                     currency=(values.get("currency") or "INR").upper(), price_source=source, price_basis=fetch.default_basis(source))
    log(user, inst, "instrument_created", inst.pk, "name", "", inst.name)
    return inst
