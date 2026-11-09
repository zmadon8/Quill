"""The local helper's server side (plan 28.3): what is wanted, and the ingest of prices fetched from the owner's own computer."""
import hashlib
import secrets
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from investments.errors import InvestmentsError
from investments.models import PriceHelperToken, SourceRun, SourceSetting
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


def ingest(rows, token=None):
    """Write helper rows (``[{source, symbol_or_code, date, close, basis}]``) with source ``helper``, using the history upload's validation.
    Never overwrites hand-entered or uploaded prices. Returns ``{"written", "unknown", "rejected"}``."""
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
            added, changed, _kept = fetch.upsert_prices(inst, sorted(days.items()), "helper", inst.price_basis)
            written += added + changed
    if written:
        fetch.bump_version()
    SourceRun.objects.create(source="helper", trigger="helper", started=started, finished=timezone.now(), tried=len(rows), updated=written,
                             failures=[{"id": 0, "name": f"row {n}", "error": e} for n, e in rejected[:50]],
                             message=f"token {token.label}" if token else "")
    return {"written": written, "unknown": sorted(unknown)[:100], "rejected": [{"row": n, "error": e} for n, e in rejected[:100]]}


__all__ = ["enabled", "create_token", "revoke", "authenticate", "wanted", "ingest", "Decimal"]
