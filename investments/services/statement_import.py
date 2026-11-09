"""Import trades from a broker or fund house statement (plan 6), reusing the Fee Register's streaming reader and its date and number parsers.

One general adapter: the columns are found by name (date, buy or sell, investment by ISIN / code / scheme code / name, units, price or NAV,
amount, charges, folio). Each broker's own layout would need its own small adapter once sample files are available. The person reviews the
rows first; nothing is saved until they confirm, and the whole file is then saved in one transaction (a row that would break a selling limit
stops the lot). A purchase line that matches an entry awaiting allotment (same investment, amount within tolerance, date within 10 days)
completes that entry instead of making a duplicate; a line identical to a stored trade is skipped as a duplicate.
"""
import contextlib
import datetime
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.db.models import Q

from investments.errors import InvestmentsError
from investments.models import HOLDABLE_KINDS, STATUS_AWAITING, Folio, Instrument, Transaction
from investments.services import masters, transactions as tx

COLUMNS = {
    "date": ("date", "trade date", "transaction date", "order date", "nav date"),
    "side": ("type", "buy/sell", "transaction type", "trade type", "side", "action"),
    "investment": ("isin", "scheme code", "symbol", "scrip", "scheme", "scheme name", "instrument", "security", "stock", "fund", "name"),
    "units": ("units", "quantity", "qty"),
    "price": ("price", "nav", "rate", "trade price", "avg price"),
    "amount": ("amount", "value", "net amount", "trade value"),
    "charges": ("charges", "brokerage", "stamp duty", "fees"),
    "folio": ("folio", "folio number", "folio no"),
}
SELL_WORDS = ("sell", "sale", "redeem", "redemption", "s", "switch out", "switch-out")
AWAITING_DAYS = 10


@dataclass
class Line:
    number: int
    raw: dict
    day: datetime.date = None
    side: str = ""
    instrument: object = None
    units: Decimal = None
    price: Decimal = None
    amount: Decimal = None
    charges: Decimal = Decimal(0)
    folio: str = ""
    completes: object = None
    duplicate: bool = False
    problem: str = ""


@dataclass
class Review:
    lines: list = field(default_factory=list)
    mapping: dict = field(default_factory=dict)

    @property
    def usable(self):
        return [l for l in self.lines if not l.problem and not l.duplicate]

    @property
    def problems(self):
        return [l for l in self.lines if l.problem]


def _guess(headers):
    lowered = [h.strip().lower() for h in headers]
    mapping = {}
    for key, needles in COLUMNS.items():
        for needle in needles:
            hit = next((i for i, h in enumerate(lowered) if h == needle), None)
            if hit is None:
                hit = next((i for i, h in enumerate(lowered) if needle in h and i not in mapping.values()), None) if len(needle) > 2 else None
            if hit is not None and hit not in mapping.values():
                mapping[key] = hit
                break
    return mapping


def _match(profile, text, cache):
    key = (text or "").strip()
    if key in cache:
        return cache[key]
    upper, folded = key.upper(), key.casefold()
    qs = Instrument.objects.filter(Q(profile=None) | Q(profile=profile), kind__in=HOLDABLE_KINDS)
    found = list(qs.filter(Q(isin__iexact=key) | Q(code__iexact=key) | Q(code__iexact=f"{upper}.NS")))
    if not found:
        found = [i for i in qs.filter(name__iexact=key)] or [i for i in qs if i.name.casefold() == folded]
    cache[key] = found[0] if len(found) == 1 else None
    return cache[key]


def _number(text):
    from fees.services.imports import parse_number

    if text in (None, ""):
        return None
    value = parse_number(text)
    return abs(value) if value else None


def review(profile, source):
    """Read the file and return a :class:`Review`; nothing is written."""
    from fees.services import imports

    out = Review()
    try:
        rows = imports.iter_rows(source)
    except Exception as exc:
        raise InvestmentsError("BAD_FILE", str(getattr(exc, "message", exc)) or "The file could not be read.") from exc
    cache = {}
    with contextlib.closing(rows):
        header = None
        for number, cells in enumerate(rows, start=1):
            if header is None:
                header = cells
                out.mapping = _guess(header)
                missing = [k for k in ("date", "investment", "units") if k not in out.mapping]
                if missing:
                    raise InvestmentsError("BAD_FILE", f"The header row needs these columns: {', '.join(missing)}.")
                continue
            cells = cells + [""] * (len(header) - len(cells))
            get = lambda k: cells[out.mapping[k]] if k in out.mapping else ""  # noqa: E731
            line = Line(number, dict(zip(header, cells)))
            iso, _bad = imports.parse_date(get("date"))
            line.day = datetime.date.fromisoformat(iso) if iso else None
            line.side = "sell" if get("side").strip().lower() in SELL_WORDS or get("side").strip().lower().startswith(("sell", "redem")) else "buy"
            line.instrument = _match(profile, get("investment"), cache)
            line.units, line.price, line.amount = _number(get("units")), _number(get("price")), _number(get("amount"))
            line.charges = _number(get("charges")) or Decimal(0)
            line.folio = get("folio").strip()
            if line.price is None and line.units and line.amount:
                line.price = (line.amount / line.units).quantize(Decimal("0.0001"))
            if line.day is None:
                line.problem = "unreadable date"
            elif line.instrument is None:
                line.problem = f"investment not found: {get('investment')!r} (add it first)"
            elif not line.units or not line.price:
                line.problem = "units or price missing"
            out.lines.append(line)
    _mark_matches(profile, out)
    return out


def _mark_matches(profile, out):
    awaiting = list(Transaction.objects.filter(profile=profile, status=STATUS_AWAITING, side="buy"))
    used = set()
    for line in out.lines:
        if line.problem:
            continue
        total = line.units * line.price + line.charges
        for a in awaiting:
            if a.pk in used or a.instrument_id != line.instrument.pk or not a.amount:
                continue
            if abs((line.day - a.date).days) <= AWAITING_DAYS and abs(total - a.amount) <= tx.tolerance_for(a.amount) * 10:
                line.completes = a
                used.add(a.pk)
                break
        if line.completes is None and Transaction.objects.filter(profile=profile, instrument=line.instrument, date=line.day, side=line.side,
                                                                  units=line.units).exists():
            line.duplicate = True


@transaction.atomic
def apply(profile, user, source, *, portfolio, broker):
    """Save every usable line in date order, all or nothing. Returns ``(made, completed, skipped)``."""
    result = review(profile, source)
    if result.problems:
        raise InvestmentsError("NOT_APPLICABLE", f"{len(result.problems)} line(s) have problems, so nothing was saved. Fix them and try again.", 409)
    made = completed = 0
    for line in sorted(result.usable, key=lambda l: (l.day, 0 if l.side == "buy" else 1, l.number)):
        folio = None
        if line.folio:
            folio = Folio.objects.filter(profile=profile, instrument=line.instrument, portfolio=portfolio, number=line.folio).first()
            if folio is None:
                folio = masters.add_folio(profile, user, instrument=line.instrument, portfolio=portfolio, number=line.folio, confirm_new=True)
        if line.completes is not None:
            tx.complete_transaction(profile, user, line.completes.pk, allotment_date=max(line.day, line.completes.date), units=line.units, nav=line.price,
                                    charges=line.charges, confirm_difference=True)
            completed += 1
            continue
        tx.add_transaction(profile, user, side=line.side, instrument=line.instrument, portfolio=portfolio, broker=broker, date=line.day, units=line.units,
                           price=line.price, charges=line.charges, folio=folio, reference=f"Imported line {line.number}")
        made += 1
    return made, completed, sum(1 for l in result.lines if l.duplicate)
