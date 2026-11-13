"""One search over the stored NSE and AMFI lists, for the picker on the Add investment page."""
from investments.models import KIND_FUND, KIND_SHARE, Instrument
from investments.services import schemes, nse_list
from investments.adapters.base import FetchError
from django.core.cache import cache
from django.db.models import Q
import logging

log = logging.getLogger(__name__)
RETRY_AFTER_SECONDS = 15 * 60   # after a failed fetch of an empty list, do not try again for this long
LAST_ERROR_SECONDS = 30 * 24 * 3600   # how long the last error stays on the Settings status line
ADMIN_FETCH_TIMEOUT = 20   # seconds per read for the admin Refresh button; two lists must finish inside the 60s gunicorn timeout


LOOKUP_KEY = "lookup"   # the SourceSetting row that holds the switch; its fetch_mode is "off" when the lookup is switched off


def lookup_enabled():
    """Admin-wide: is searching and downloading the NSE and AMFI lists on? On unless an Admin switched it off."""
    from investments.models import SourceSetting

    return SourceSetting.objects.filter(source=LOOKUP_KEY).values_list("fetch_mode", flat=True).first() != "off"


def set_lookup_enabled(on):
    from investments.models import SourceSetting

    SourceSetting.objects.update_or_create(source=LOOKUP_KEY, defaults={"fetch_mode": "server" if on else "off"})


def _existing(profile, codes, isins):
    """``{code: id}`` and ``{isin: id}`` of the shared (and the profile's own) investments matching, in two queries at most."""
    by_code, by_isin = {}, {}
    cond = Q()
    if codes:
        cond |= Q(code__in=codes)
    if isins:
        cond |= Q(isin__in=isins)
    if not cond:
        return by_code, by_isin
    for pk, code, isin in Instrument.objects.filter(cond).filter(Q(profile=None) | Q(profile=profile)).values_list("pk", "code", "isin"):
        by_code.setdefault(code.upper(), pk)
        if isin:
            by_isin.setdefault(isin.upper(), pk)
    return by_code, by_isin


def search(profile, query, kind=None, limit=30):
    """``{"results": [...], "message": str}``. Each result has source (nse|amfi), kind (share|fund), code (NSE: SYMBOL.NS; AMFI: scheme code),
    name (a fund's is the standardised "Base Fund Regular Plan Growth Option"), isin, plan, option, raw_name (the AMFI name as listed), extra and existing_id (the investment already there, or None). A list that is empty and cannot be fetched gives a message."""
    q = (query or "").strip()
    message = ""
    found = []
    if not lookup_enabled():
        return {"results": [], "message": "Lookup is switched off"}
    if len(q) >= 2:
        if kind in (None, "", "share"):
            rows = nse_list.find(q, limit)
            if not rows and not _nse_has_rows():
                message = _try_refresh(nse_list, "NSE")
                rows = nse_list.find(q, limit) if not message else []
            found += [{"source": "nse", "kind": KIND_SHARE, "code": f"{r.symbol}.NS", "name": r.name, "isin": r.isin, "plan": "", "option": "", "raw_name": "", "extra": f"NSE {r.series}"} for r in rows]
        if kind in (None, "", "fund"):
            rows = schemes.find(q, limit)
            if not rows and not _amfi_has_rows():
                message = message or _try_refresh(schemes, "AMFI")
                rows = schemes.find(q, limit) if not message else []
            found += [{"source": "amfi", "kind": KIND_FUND, "code": s.code, "name": s.display_name, "isin": s.isin,
                       "plan": s.plan, "option": s.option, "raw_name": s.name,
                       "extra": f"NAV {s.nav} on {s.nav_date:%-d %b}" if s.nav and s.nav_date else "AMFI"} for s in rows]
    found = found[:limit]
    by_code, by_isin = _existing(profile, {r["code"].upper() for r in found}, {r["isin"].upper() for r in found if r["isin"]})
    for r in found:
        r["existing_id"] = by_code.get(r["code"].upper()) or (by_isin.get(r["isin"].upper()) if r["isin"] else None)
    if not found and not message and len(q) >= 2:
        message = "Nothing matched in the stored NSE and AMFI lists. You can still type the details yourself."
    return {"results": found, "message": message}


def lookup_record(source, code):
    """The stored NSE or AMFI record a posted pick names, as ``{source, kind, code, name, isin, plan, option}``, or None when the code is not
    in the stored list or the lookup is switched off. Name, ISIN and kind come from the stored record, never from what the page posted."""
    from investments.models import AmfiScheme, NseSecurity

    source, code = (source or "").strip().lower(), (code or "").strip()
    if not code or source not in ("nse", "amfi") or not lookup_enabled():
        return None
    if source == "nse":
        symbol = code[:-3] if code.upper().endswith(".NS") else ""
        row = NseSecurity.objects.filter(symbol=symbol).first() if symbol else None
        if row is None:
            return None
        return {"source": "nse", "kind": KIND_SHARE, "code": f"{row.symbol}.NS", "name": row.name, "isin": row.isin, "plan": "", "option": "",
                "asset_class": "equity"}
    row = AmfiScheme.objects.filter(code=code).first()
    if row is None:
        return None
    return {"source": "amfi", "kind": KIND_FUND, "code": row.code, "name": row.display_name, "isin": row.isin, "plan": row.plan, "option": row.option,
            "asset_class": row.asset_class}


def resolve_pick(profile, user, record, made=None):
    """The Instrument for a ``lookup_record``: the one already there (same code or ISIN), else a new one made now. ``made`` is a dict shared by
    the cards of one save so two cards picking the same new investment get one. Call inside the save's atomic block."""
    from investments.errors import InvestmentsError
    from investments.services import fetch_defaults, masters

    made = made if made is not None else {}
    key = record["code"].upper()
    if key in made:
        return made[key]
    by_code, by_isin = _existing(profile, {key}, {record["isin"].upper()} if record["isin"] else set())
    pk = by_code.get(key) or (by_isin.get(record["isin"].upper()) if record["isin"] else None)
    if pk:
        obj = Instrument.objects.get(pk=pk)
    else:
        try:
            obj = masters.create_instrument(profile, user, kind=record["kind"], name=record["name"], code=record["code"], isin=record["isin"],
                                            asset_class=record.get("asset_class", "equity"), price_source=fetch_defaults.default_source(record["kind"]))
        except InvestmentsError as err:
            if err.code != "SIMILAR":
                raise
            obj = Instrument.objects.get(pk=err.details["existing_id"])
    made[key] = obj
    return obj


def _nse_has_rows():
    from investments.models import NseSecurity

    return NseSecurity.objects.exists()


def _amfi_has_rows():
    from investments.models import AmfiScheme

    return AmfiScheme.objects.exists()


def _try_refresh(service, label):
    """Fetch an empty list once, when searching finds it empty. Never raises."""
    key = f"instrument_search:refresh_failed:{label}"
    if cache.get(key):
        return f"The {label} list could not be fetched just now. You can type the details yourself."
    try:
        if service.due():
            service.refresh()
    except FetchError as exc:
        cache.set(key, True, RETRY_AFTER_SECONDS)
        cache.set(_error_key(label), str(exc)[:200], LAST_ERROR_SECONDS)
        return f"The {label} list could not be fetched ({exc}). You can type the details yourself."
    except Exception:  # a bad file must not break the page
        log.exception("%s list refresh failed", label)
        cache.set(key, True, RETRY_AFTER_SECONDS)
        cache.set(_error_key(label), "the file could not be read", LAST_ERROR_SECONDS)
        return f"The {label} list could not be read. You can type the details yourself."
    return ""


def _error_key(label):
    return f"instrument_search:last_error:{label}"


def status():
    """For the Admin Settings page: per list the entry count, when it was last refreshed (None if never) and the last error ("" if none)."""
    from django.db.models import Count, Max

    from investments.models import AmfiScheme, NseSecurity

    out = []
    for label, model in (("NSE", NseSecurity), ("AMFI", AmfiScheme)):
        agg = model.objects.aggregate(n=Count("pk"), last=Max("updated_at"))
        out.append({"label": label, "count": agg["n"], "last": agg["last"], "error": cache.get(_error_key(label)) or ""})
    return out


def refresh_now():
    """Admin button: clear the retry throttle, then fetch both lists now (each fetch is capped well under the 60s worker timeout: one try, short socket timeout). Returns ``[(label, count or None, error)]``; never raises."""
    results = []
    for label, service in (("NSE", nse_list), ("AMFI", schemes)):
        cache.delete(f"instrument_search:refresh_failed:{label}")
        try:
            results.append((label, service.refresh(force=True, timeout=ADMIN_FETCH_TIMEOUT, tries=1), ""))
            cache.delete(_error_key(label))
        except FetchError as exc:
            cache.set(_error_key(label), str(exc)[:200], LAST_ERROR_SECONDS)
            results.append((label, None, str(exc)))
        except Exception:  # a bad file must not break the page
            log.exception("%s list refresh failed", label)
            cache.set(_error_key(label), "the file could not be read", LAST_ERROR_SECONDS)
            results.append((label, None, "the file could not be read"))
    return results
