"""The local helper's server side (plan 28.3): what is wanted, and the ingest of prices fetched from the owner's own computer."""
import hashlib
import secrets
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from investments.errors import InvestmentsError
from investments.models import KIND_ALTERNATIVE, KIND_FUND, KIND_INDEX, Price, PriceHelperToken, SourceRun, SourceSetting, SourceSymbol
from investments.services import fetch, locks, price_import

MAX_ROWS = 5000
MAX_BYTES = 2 * 1024 * 1024
CALLS_PER_HOUR = 120


def enabled():
    return bool(getattr(settings, "PRICE_HELPER_ENABLED", False))


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_token(user, label):
    """Make a token; return ``(row, plain token)``. The plain token is never stored and is shown once."""
    plain = secrets.token_urlsafe(32)
    row = PriceHelperToken.objects.create(label=(label or "Helper")[:80], token_hash=_hash(plain), created_by=user if getattr(user, "pk", None) else None)
    return row, plain


def revoke(pk):
    PriceHelperToken.objects.filter(pk=pk, revoked_at__isnull=True).update(revoked_at=timezone.now())


def authenticate(header):
    """The token row for an ``Authorization: Bearer ...`` header, or None. Counts the call against the hourly limit."""
    if not header or not header.startswith("Bearer "):
        return None
    row = PriceHelperToken.objects.filter(token_hash=_hash(header[7:].strip()), revoked_at__isnull=True).first()
    if row is None:
        return None
    now = timezone.now()
    if row.window_start is None or now - row.window_start > timedelta(hours=1):
        row.window_start, row.window_calls = now, 0
    row.window_calls += 1
    row.last_used_at = now
    row.save(update_fields=["window_start", "window_calls", "last_used_at"])
    if row.window_calls > CALLS_PER_HOUR:
        raise InvestmentsError("RATE_LIMIT", "Too many calls this hour.", 429)
    return row


def mode(source):
    return SourceSetting.objects.filter(source=source).values_list("fetch_mode", flat=True).first() or "server"


def set_mode(source, value):
    if value not in ("server", "helper", "either"):
        raise InvestmentsError("BAD_CHOICE", "Choose server, helper or either.")
    SourceSetting.objects.update_or_create(source=source, defaults={"fetch_mode": value})


def server_skips(source):
    """True when the server must not fetch this source itself (helper only)."""
    return enabled() and mode(source) == "helper"


def wanted(today=None):
    """``[{symbol, source, last, expected, basis}]`` for the symbols the helper should fetch. With ``either`` only stale symbols are listed."""
    today = today or date.today()
    expected = today - timedelta(days=1)
    while expected.weekday() >= 5:
        expected -= timedelta(days=1)
    stale = fetch.stale_ids(fetch.tracked_instruments(), today)
    out = []
    for inst in fetch.tracked_instruments():
        source = inst.price_source
        m = mode(source)
        if m == "server" or (m == "either" and inst.pk not in stale and fetch.last_api_date(inst)):
            continue
        out.append({"symbol": fetch.symbol_for(inst, source), "source": source, "last": (fetch.last_api_date(inst) or None) and fetch.last_api_date(inst).isoformat(),
                    "expected": expected.isoformat(), "basis": inst.price_basis})
    return out


def ingest(rows, token=None, fill_only=False, via="helper"):
    """Write helper rows (``[{source, symbol_or_code, date, close, basis}]``) with source ``helper``, using the history upload's validation.
    Never overwrites hand-entered or uploaded prices. With ``fill_only`` (the Google Sheet) a day that already has a stored price is left
    alone, so a fetched close is never replaced by the sheet's. Returns ``{"written", "unknown", "rejected"}``."""
    if len(rows) > MAX_ROWS:
        raise InvestmentsError("TOO_MANY", f"At most {MAX_ROWS} rows in one request.", 413)
    lookup = price_import.build_lookup()
    today = date.today()
    per = {}
    unknown, rejected = set(), []
    for n, row in enumerate(rows, start=1):
        inst = lookup.get(str(row.get("symbol_or_code", "")).strip().upper())
        if inst is None:
            unknown.add(str(row.get("symbol_or_code", "")))
            continue
        day = price_import._parse_date(str(row.get("date", "")))
        close = price_import._number(row.get("close"))
        basis = str(row.get("basis") or "").strip().lower()
        if day is None or day > today or close is None or close <= 0:
            rejected.append((n, "bad date or price"))
            continue
        if basis and inst.price_basis and basis != inst.price_basis:
            rejected.append((n, f"basis '{basis}' differs from the investment's '{inst.price_basis}'"))
            continue
        per.setdefault(inst.pk, (inst, {}))[1][day] = close
    written = 0
    started = timezone.now()
    with locks.heavy("price_ingest"), transaction.atomic():
        for inst, days in per.values():
            if fill_only:
                stored = set(Price.objects.filter(instrument=inst, date__in=list(days)).values_list("date", flat=True))
                days = {day: close for day, close in days.items() if day not in stored}
                if not days:
                    continue
            added, changed, _kept = fetch.upsert_prices(inst, sorted(days.items()), "helper", inst.price_basis)
            written += added + changed
    if written:
        fetch.bump_version()
    sheet = via == "sheet"
    SourceRun.objects.create(source="google_sheet" if sheet else "helper", trigger="sheet" if sheet else "helper", started=started, finished=timezone.now(),
                             tried=len(rows), updated=written,
                             failures=[{"id": 0, "name": f"row {n}", "error": e} for n, e in rejected[:50]],
                             message=f"token {token.label}" if token else "")
    return {"written": written, "unknown": sorted(unknown)[:100], "rejected": [{"row": n, "error": e} for n, e in rejected[:100]]}


# ---------------------------------------------------------------- the Google Sheet (owner request, November 2026)

#: Google Finance tickers of the built-in indices (a guess for the less common ones: the sheet's ticker column can be corrected by hand,
#: or a symbol set for the source ``google`` on the catalogue page).
GOOGLE_INDEX = {
    "^NSEI": "INDEXNSE:NIFTY_50", "^BSESN": "INDEXBOM:SENSEX", "^NSEBANK": "INDEXNSE:NIFTY_BANK", "^CNXIT": "INDEXNSE:NIFTY_IT",
    "^NSMIDCP": "INDEXNSE:NIFTY_NEXT_50", "NIFTYMIDCAP150.NS": "INDEXNSE:NIFTY_MIDCAP_150", "NIFTYSMLCAP250.NS": "INDEXNSE:NIFTY_SMLCAP_250",
    "^CNX100": "INDEXNSE:NIFTY_100", "^CRSLDX": "INDEXNSE:NIFTY_500", "^GSPC": "INDEXSP:.INX",
}


def google_ticker(instrument, override=""):
    """The GOOGLEFINANCE ticker for an investment: ``RELIANCE.NS`` is ``NSE:RELIANCE``, ``500325.BO`` is ``BOM:500325``; "" when unknown."""
    if override:
        return override.strip()
    code = (instrument.code or "").strip()
    upper = code.upper()
    if instrument.kind == KIND_INDEX:
        return GOOGLE_INDEX.get(upper, "")
    if upper.endswith(".NS"):
        return "NSE:" + code[:-3]
    if upper.endswith(".BO"):
        return "BOM:" + code[:-3]
    return code if code and "." not in code else ""


def sheet_list():
    """``[{code, name, kind, google, last}]`` for the Google Sheet: every tracked share, index and foreign investment with a code. Funds
    are left out (Google has no reliable Indian fund NAVs; AMFI's file is used for them). Only codes and names, never holdings."""
    tracked = [i for i in fetch.tracked_instruments() if i.kind not in (KIND_FUND, KIND_ALTERNATIVE) and (i.code or "").strip()]
    overrides = dict(SourceSymbol.objects.filter(instrument__in=tracked, source="google").values_list("instrument_id", "symbol"))
    from investments.services import prices as price_service

    last = price_service.last_price_date([i.pk for i in tracked])
    return [{"code": i.code.strip(), "name": i.name, "kind": i.kind, "google": google_ticker(i, overrides.get(i.pk, "")),
             "last": last[i.pk].isoformat() if i.pk in last else None} for i in tracked]


def sheet_script(site):
    """The Apps Script for the sheet (``tools/google_sheet_prices.gs``) with this site's address filled in."""
    from pathlib import Path

    path = Path(settings.BASE_DIR) / "tools" / "google_sheet_prices.gs"
    return path.read_text(encoding="utf-8").replace("https://YOUR-SITE.onrender.com", site.rstrip("/"))


__all__ = ["enabled", "create_token", "revoke", "authenticate", "wanted", "ingest", "sheet_list", "google_ticker", "sheet_script", "Decimal"]
