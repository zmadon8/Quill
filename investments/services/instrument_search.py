"""One search over the stored NSE and AMFI lists, for the picker on the Add investment page."""
from investments.models import KIND_FUND, KIND_SHARE, Instrument
from investments.services import schemes, nse_list
from investments.adapters.base import FetchError
from django.core.cache import cache
from django.db.models import Q
import logging

log = logging.getLogger(__name__)
RETRY_AFTER_SECONDS = 15 * 60   # after a failed fetch of an empty list, do not try again for this long


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
    name, isin, extra and existing_id (the investment already there, or None). A list that is empty and cannot be fetched gives a message."""
    q = (query or "").strip()
    message = ""
    found = []
    if len(q) >= 2:
        if kind in (None, "", "share"):
            rows = nse_list.find(q, limit)
            if not rows and not _nse_has_rows():
                message = _try_refresh(nse_list, "NSE")
                rows = nse_list.find(q, limit) if not message else []
            found += [{"source": "nse", "kind": KIND_SHARE, "code": f"{r.symbol}.NS", "name": r.name, "isin": r.isin, "extra": f"NSE {r.series}"} for r in rows]
        if kind in (None, "", "fund"):
            rows = schemes.find(q, limit)
            if not rows and not _amfi_has_rows():
                message = message or _try_refresh(schemes, "AMFI")
                rows = schemes.find(q, limit) if not message else []
            found += [{"source": "amfi", "kind": KIND_FUND, "code": s.code, "name": s.name, "isin": s.isin,
                       "extra": f"NAV {s.nav} on {s.nav_date:%-d %b}" if s.nav and s.nav_date else "AMFI"} for s in rows]
    found = found[:limit]
    by_code, by_isin = _existing(profile, {r["code"].upper() for r in found}, {r["isin"].upper() for r in found if r["isin"]})
    for r in found:
        r["existing_id"] = by_code.get(r["code"].upper()) or (by_isin.get(r["isin"].upper()) if r["isin"] else None)
    if not found and not message and len(q) >= 2:
        message = "Nothing matched in the stored NSE and AMFI lists. You can still type the details yourself."
    return {"results": found, "message": message}


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
        return f"The {label} list could not be fetched ({exc}). You can type the details yourself."
    except Exception:  # a bad file must not break the page
        log.exception("%s list refresh failed", label)
        cache.set(key, True, RETRY_AFTER_SECONDS)
        return f"The {label} list could not be read. You can type the details yourself."
    return ""
