"""Import trades from a broker or fund house statement (plan 6), reusing the Fee Register's streaming reader and its date and number parsers.

One general adapter: the columns are found by name (date, buy or sell, investment by ISIN / code / scheme code / name, units, price or NAV,
amount, charges, folio). Each broker's own layout would need its own small adapter once sample files are available. The person reviews the
rows first; nothing is saved until they confirm, and the whole file is then saved in one transaction (a row that would break a selling limit
stops the lot). A purchase line that matches an entry awaiting allotment (same investment, amount within tolerance, date within 10 days)
completes that entry instead of making a duplicate; a line identical to a stored trade is skipped as a duplicate.

An investment the program does not have yet is proposed for adding (owner round 2026-11): the review lists each one once, with a type,
name, code and ISIN guessed from the file and from the stored AMFI scheme list; the person checks or corrects them and confirms, the
investments are created, and the lines are matched to them through ``aliases`` (the file's text -> the new investment) so a corrected
name still matches. Nothing is guessed from the internet: prices come with the next Update Prices or the nightly fetch.
"""
import contextlib
import datetime
import re
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.db.models import Q

from investments.errors import InvestmentsError
from investments.models import (
    HOLDABLE_KINDS, KIND_FOREIGN, KIND_FUND, KIND_SHARE, STATUS_AWAITING, AmfiScheme, Folio, Instrument, Transaction,
)
from investments.services import masters, transactions as tx

COLUMNS = {
    "date": ("date", "trade date", "transaction date", "order date", "nav date"),
    "side": ("type", "buy/sell", "transaction type", "trade type", "side", "action"),
    "investment": ("isin", "scheme code", "symbol", "scrip", "scheme", "scheme name", "instrument", "security", "stock", "fund", "name"),
    # A second column naming the investment, when the one above is a code: used only to propose the name of a missing investment.
    "label": ("scheme name", "security name", "scrip name", "stock name", "fund name", "instrument name", "company name", "name"),
    "units": ("units", "quantity", "qty"),
    "price": ("price", "nav", "rate", "trade price", "avg price"),
    "amount": ("amount", "value", "net amount", "trade value"),
    "charges": ("charges", "brokerage", "stamp duty", "fees"),
    "folio": ("folio", "folio number", "folio no"),
}
SELL_WORDS = ("sell", "sale", "redeem", "redemption", "s", "switch out", "switch-out")
AWAITING_DAYS = 10
#: The types a missing investment can be added as from a statement (alternative investments have no units or price feed).
ADDABLE_KINDS = ((KIND_SHARE, "Share or ETF"), (KIND_FUND, "Mutual fund"), (KIND_FOREIGN, "Foreign share"))
ISIN_RE = re.compile(r"^IN[A-Z0-9]{10}$")
SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9&\-.^]{0,24}$")


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
    text: str = ""          # what the file says the investment is
    completes: object = None
    duplicate: bool = False
    problem: str = ""


@dataclass
class Review:
    lines: list = field(default_factory=list)
    mapping: dict = field(default_factory=dict)
    missing: list = field(default_factory=list)   # one proposal per investment the program does not have yet

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


def _match(profile, text, cache, aliases=None):
    key = (text or "").strip()
    if key in cache:
        return cache[key]
    if aliases and key in aliases:
        cache[key] = Instrument.objects.filter(Q(profile=None) | Q(profile=profile), pk=aliases[key]).first()
        if cache[key] is not None:
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


def propose(text, label=""):
    """A guess at a missing investment from the file's text (and a name column, if the file has one), from stored data only:
    ``{text, kind, name, code, isin, currency, note}``. Funds are looked up in the stored AMFI scheme list by ISIN, scheme code or name."""
    key = (text or "").strip()
    upper = key.upper()
    label = (label or "").strip()
    out = {"text": key, "kind": KIND_SHARE, "name": label or key, "code": "", "isin": "", "currency": "INR", "note": ""}
    scheme = None
    if ISIN_RE.match(upper):
        scheme = AmfiScheme.objects.filter(isin__iexact=upper).first()
        out["isin"] = upper
    elif key.isdigit():
        scheme = AmfiScheme.objects.filter(code=key).first()
    if scheme is None:
        scheme = (AmfiScheme.objects.filter(name__iexact=key).first() if key else None) or (AmfiScheme.objects.filter(name__iexact=label).first() if label else None)
    if scheme is not None:
        out.update(kind=KIND_FUND, name=scheme.name, code=scheme.code, isin=scheme.isin or out["isin"], note="Found in the AMFI scheme list.")
    elif out["isin"]:
        if upper.startswith("INF"):
            out.update(kind=KIND_FUND, name=label, note="A fund ISIN not in the stored AMFI list: type its AMFI scheme code.")
        else:
            out.update(name=label, note="Type the share's code, for example RELIANCE.NS (NSE) or 500325.BO (BSE).")
    elif key.isdigit():
        out.update(kind=KIND_FUND, code=key, name=label, note="Not in the stored AMFI list: check the scheme code.")
    elif SYMBOL_RE.match(upper) and " " not in key:
        out.update(code=upper if "." in upper or upper.startswith("^") else f"{upper}.NS", name=label or upper,
                   note="Taken as an NSE code; change it for BSE (.BO) or a foreign exchange.")
    else:
        out["note"] = "Type the share's code, for example RELIANCE.NS, or choose Mutual fund and type its AMFI scheme code."
    return out


def create_missing(profile, user, specs):
    """Add the confirmed investments. ``specs`` are dicts like :func:`propose` returns (as corrected by the person). An investment that
    is already in the program under another spelling is used instead of a duplicate. Returns ``{file text: instrument id}``; all or
    nothing."""
    from investments.models import ProfileInvestment

    kinds = {k for k, _l in ADDABLE_KINDS}
    aliases = {}
    with transaction.atomic():
        for spec in specs:
            text, name, code = spec.get("text", "").strip(), (spec.get("name") or "").strip(), (spec.get("code") or "").strip()
            kind = spec.get("kind") or KIND_SHARE
            if kind not in kinds:
                raise InvestmentsError("BAD_KIND", f"{text}: choose a type.")
            if not name or not code:
                raise InvestmentsError("REQUIRED", f"{text}: a name and a code are needed (the code is how its prices are fetched).")
            similar = masters.find_similar(profile, name, code, kind)
            if similar:
                inst = similar[0]
                ProfileInvestment.objects.get_or_create(profile=profile, instrument=inst)
            else:
                inst = masters.create_instrument(profile, user, kind=kind, name=name, code=code, isin=(spec.get("isin") or "").strip(),
                                                 currency=(spec.get("currency") or ("USD" if kind == KIND_FOREIGN else "INR")).strip() or "INR")
            aliases[text] = inst.pk
    return aliases


def review(profile, source, aliases=None):
    """Read the file and return a :class:`Review`; nothing is written. ``aliases`` maps the file's text to investments just added."""
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
            line.text = get("investment").strip()
            line.instrument = _match(profile, line.text, cache, aliases)
            line.units, line.price, line.amount = _number(get("units")), _number(get("price")), _number(get("amount"))
            line.charges = _number(get("charges")) or Decimal(0)
            line.folio = get("folio").strip()
            if line.price is None and line.units and line.amount:
                line.price = (line.amount / line.units).quantize(Decimal("0.0001"))
            if line.day is None:
                line.problem = "unreadable date"
            elif line.instrument is None:
                line.problem = f"{line.text!r} is not in the program yet (add it below)" if line.text else "no investment given"
                if line.text and all(m["text"] != line.text for m in out.missing):
                    out.missing.append(propose(line.text, get("label") if out.mapping.get("label") != out.mapping.get("investment") else ""))
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
def apply(profile, user, source, *, portfolio, broker, aliases=None):
    """Save every usable line in date order, all or nothing. Returns ``(made, completed, skipped)``."""
    result = review(profile, source, aliases)
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
