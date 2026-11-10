"""Indices (owner round 2026-11): add an index by its Yahoo symbol, delete one that was added, and choose a sector index for each
investment.

Indices are shared by every profile, like the catalogue. The eight built-in ones (``masters.BUILTIN_INDICES``) cannot be deleted.
Adding asks Yahoo for the index's history first, so a symbol Yahoo does not know is refused and nothing is created. Deleting an
index that some profile uses (as its Default Index or as an investment's sector index) needs its name typed; those choices then
fall back (the Default Index to Nifty 50, a sector index to none). The nightly fetch keeps the prices of every index in use up to date
(one chosen for the first time gets its history that night); an added index gets 10 years of history when it is added.
"""
import datetime

from django.db import transaction

from investments.errors import InvestmentsError, not_found
from investments.models import KIND_INDEX, Instrument, InvestmentSettings, Price, ProfileInvestment, Transaction
from investments.services import core, fetch, pins

#: Sector indices of the NSE as Yahoo lists them, offered as suggestions when adding (each is checked with Yahoo when added).
SUGGESTED = (
    ("Nifty Auto", "^CNXAUTO"), ("Nifty Pharma", "^CNXPHARMA"), ("Nifty FMCG", "^CNXFMCG"), ("Nifty Metal", "^CNXMETAL"),
    ("Nifty Realty", "^CNXREALTY"), ("Nifty Energy", "^CNXENERGY"), ("Nifty Infrastructure", "^CNXINFRA"), ("Nifty PSU Bank", "^CNXPSUBANK"),
    ("Nifty Media", "^CNXMEDIA"), ("Nifty Financial Services", "NIFTY_FIN_SERVICE.NS"),
)
HISTORY_YEARS = 10


def _builtin_codes():
    from investments.services.masters import BUILTIN_INDICES

    return {code for _name, code in BUILTIN_INDICES}


def is_builtin(instrument):
    return instrument.kind == KIND_INDEX and instrument.code in _builtin_codes()


def listing(profile):
    """Every index with what uses it: ``[(instrument, built_in, default_here, sector_here, used_elsewhere, last_price_date, rows)]``."""
    from django.db.models import Count, Max

    indices = list(Instrument.objects.filter(profile=None, kind=KIND_INDEX).annotate(last=Max("prices__date"), rows=Count("prices")).order_by("name"))
    settings_row = core.get_settings(profile, create=False)
    default_id = settings_row.default_index_id if settings_row else None
    if default_id is None:
        default_id = next((i.pk for i in indices if i.code == "^NSEI"), None)
    sector_here = dict(ProfileInvestment.objects.filter(profile=profile).exclude(sectoral_index=None).values_list("sectoral_index_id")
                       .annotate(n=Count("pk")).order_by())
    elsewhere = set(InvestmentSettings.objects.exclude(profile=profile).exclude(default_index=None).values_list("default_index_id", flat=True))
    elsewhere |= set(ProfileInvestment.objects.exclude(profile=profile).exclude(sectoral_index=None).values_list("sectoral_index_id", flat=True))
    return [(i, is_builtin(i), i.pk == default_id, sector_here.get(i.pk, 0), i.pk in elsewhere, i.last, i.rows) for i in indices]


def require_editor(user):
    from investments.services.catalogue import require_editor as check

    check(user)


def add_index(user, name, code, currency="INR", today=None):
    """Add an index by its Yahoo symbol, with its price history. Returns ``(instrument, prices stored)``."""
    from investments.adapters import yahoo
    from investments.adapters.base import FetchError
    from investments.services.catalogue import log

    require_editor(user)
    name, code = (name or "").strip(), (code or "").strip().upper()
    currency = (currency or "INR").strip().upper()[:3] or "INR"
    if not name or not code:
        raise InvestmentsError("REQUIRED", "Give the index a name and its Yahoo symbol, for example ^CNXAUTO.")
    existing = Instrument.objects.filter(profile=None, code__iexact=code).first()
    if existing is not None:
        raise InvestmentsError("EXISTS", f"{existing.name} already uses the symbol {code}.", 409, {"existing_id": existing.pk})
    today = today or datetime.date.today()
    try:   # ask Yahoo first: an unknown symbol is refused before anything is created
        result = yahoo.fetch(code, None, years=HISTORY_YEARS, today=today)
    except FetchError as exc:
        raise InvestmentsError("FETCH_FAILED", f"Yahoo has no prices for {code} ({exc}). Check the symbol; nothing was added.", 409)
    if not result.rows:
        raise InvestmentsError("NO_ROWS", f"Yahoo sent no prices for {code}. Check the symbol; nothing was added.", 409)
    with transaction.atomic():
        inst = Instrument.objects.create(profile=None, kind=KIND_INDEX, name=name[:200], code=code, currency=currency, asset_class="equity",
                                         price_source="yahoo", price_basis=fetch.default_basis("yahoo"))
        added, _changed, _kept = fetch.upsert_prices(inst, result.rows, "api", fetch.default_basis("yahoo"))
        log(user, inst, "index_added", inst.pk, "code", "", code, f"{added} prices")
    fetch.bump_version()
    return inst, added


def delete_preview(instrument):
    """Who uses this index: ``{"default": [profile names], "sector": n investments, "problem": text}``."""
    from accounts.models import Profile

    out = {"default": [], "sector": 0, "problem": ""}
    if instrument.kind != KIND_INDEX or instrument.profile_id is not None:
        out["problem"] = "This is not an index."
    elif is_builtin(instrument):
        out["problem"] = "The built-in indices cannot be deleted."
    out["default"] = list(Profile.objects.filter(pk__in=InvestmentSettings.objects.filter(default_index=instrument).values("profile_id"))
                          .order_by("name").values_list("name", flat=True))
    out["sector"] = ProfileInvestment.objects.filter(sectoral_index=instrument).count()
    return out


def delete_index(user, instrument, confirm_name=None):
    """Delete an added index with its prices and pins. While anyone uses it the name must be typed; their choices fall back."""
    from investments.services.catalogue import log

    require_editor(user)
    preview = delete_preview(instrument)
    if preview["problem"]:
        raise InvestmentsError("NOT_APPLICABLE", preview["problem"], 409)
    if (preview["default"] or preview["sector"]) and (confirm_name or "").strip() != instrument.name:
        raise InvestmentsError("CONFIRM_NAME", "This index is in use. Type its name exactly to delete it.", 400)
    from accounts.models import Profile

    affected = set(InvestmentSettings.objects.filter(default_index=instrument).values_list("profile_id", flat=True))
    affected |= set(ProfileInvestment.objects.filter(sectoral_index=instrument).values_list("profile_id", flat=True))
    with transaction.atomic():
        log(user, instrument, "index_deleted", instrument.pk, "name", instrument.name, "", f"used by {len(affected)} profile(s)")
        instrument.delete()   # Default Index and sector index choices are cleared (SET_NULL); prices and pins go with it
        for p in Profile.objects.filter(pk__in=affected):
            core.touch(p)
    fetch.bump_version()
    return len(affected)


def set_sector_index(profile, user, instrument, index):
    """Choose (or clear, with None) the sector index of one investment in this profile, and pin it on the dates of its transactions."""
    from investments.services.masters import update_profile_details

    if index is not None and (index.kind != KIND_INDEX or index.profile_id is not None):
        raise not_found("index")
    update_profile_details(profile, user, instrument, sectoral_index=index, sectoral_set=True)
    if index is not None:
        pin_sector(profile, instrument, index)


def pin_sector(profile, instrument, index):
    """Pin the sector index on the dates of this profile's transactions in the investment (from stored prices; no network)."""
    days = set(Transaction.objects.filter(profile=profile, instrument=instrument).values_list("date", flat=True))
    if not Price.objects.filter(instrument=index).exists():
        return 0
    return sum(1 for d in days if pins.pin(index, d, "transaction") is not None)
