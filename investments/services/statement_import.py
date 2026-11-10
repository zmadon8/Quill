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

Holdings sheet (owner round 2026-11): a file may also give, on every row, the investment's name and code separately, its type (Share,
Mutual Fund, ...), the portfolio and the broker. A code that matches an investment uses it; otherwise the investment is added from the
row's name, code and type when the file is saved (no separate step), and a portfolio or broker the profile does not have is added too.
The portfolio and broker chosen on the page are used only for rows that leave those cells blank.
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
    HOLDABLE_KINDS, KIND_ALTERNATIVE, KIND_FOREIGN, KIND_FUND, KIND_SHARE, STATUS_AWAITING, AmfiScheme, Broker, Folio, Instrument, Portfolio,
    Transaction,
)
from investments.services import masters, transactions as tx

#: Each key's possible headings, tried in order (an exact heading first, then a heading containing it). Order matters: "Transaction
#: type" is the buy or sell column and plain "Type" the investment's type when a file has both.
COLUMNS = {
    "date": ("date", "trade date", "transaction date", "date of transaction", "order date", "nav date"),
    "side": ("transaction type", "buy/sell", "buy or sell", "trade type", "side", "action", "type"),
    "kind": ("investment type", "asset type", "instrument type", "security type", "type"),
    "investment": ("isin", "investment code", "code", "scheme code", "symbol", "ticker", "scrip code", "scrip", "scheme", "scheme name",
                   "instrument", "security", "stock", "fund", "name"),
    # A second column naming the investment, when the one above is a code: its name when it has to be added.
    "label": ("investment name", "name of investment", "security name", "scheme name", "scrip name", "stock name", "fund name",
              "instrument name", "company name", "name"),
    "portfolio": ("portfolio", "portfolio name"),
    "broker": ("broker", "broker name", "platform"),
    "units": ("units", "quantity", "qty"),
    "price": ("price", "nav", "rate", "trade price", "avg price"),
    "amount": ("amount", "value", "net amount", "trade value"),
    "charges": ("charges", "brokerage", "stamp duty", "fees"),
    "folio": ("folio", "folio number", "folio no"),
}
#: Keys matched only by an exact heading ("Brokerage" is charges, not the broker).
EXACT_ONLY = {"portfolio", "broker"}
SELL_WORDS = ("sell", "sale", "redeem", "redemption", "s", "switch out", "switch-out")
AWAITING_DAYS = 10
#: The types a missing investment can be added as from a file. An alternative investment needs no code (it has no price feed).
ADDABLE_KINDS = ((KIND_SHARE, "Share or ETF"), (KIND_FUND, "Mutual fund"), (KIND_FOREIGN, "Foreign share"), (KIND_ALTERNATIVE, "Alternative"))
#: Words in a Type cell, and the type they mean.
KIND_WORDS = ((KIND_FUND, ("mutual fund", "fund", "mf", "scheme", "sip")), (KIND_FOREIGN, ("foreign", "us share", "us stock", "international")),
              (KIND_ALTERNATIVE, ("alternative", "ppf", "fd", "fixed deposit", "bond", "gold", "property", "real estate", "nps", "epf", "other")),
              (KIND_SHARE, ("share", "equity", "stock", "etf", "shares")))
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
    name: str = ""          # the file's name for it, when it gives one beside the code
    kind: str = ""          # the type the file gives (share, fund, ...), or blank
    portfolio_name: str = ""
    broker_name: str = ""
    new_investment: bool = False   # added from the row when the file is saved
    completes: object = None
    duplicate: bool = False
    problem: str = ""


@dataclass
class Review:
    lines: list = field(default_factory=list)
    mapping: dict = field(default_factory=dict)
    missing: list = field(default_factory=list)   # one proposal per investment the program does not have yet
    new_portfolios: list = field(default_factory=list)   # names the profile does not have yet (added when saving)
    new_brokers: list = field(default_factory=list)

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
            if hit is None and key not in EXACT_ONLY:
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


def kind_of(text):
    """The investment type a Type cell means (share, fund, foreign, alternative), or "" when it is blank or not recognised."""
    t = " ".join((text or "").lower().replace("_", " ").replace("-", " ").split())
    if not t:
        return ""
    for kind, words in KIND_WORDS:
        if t in words or any(t.startswith(w + " ") or t.endswith(" " + w) for w in words if len(w) > 2):
            return kind
    return ""


def _ready(spec):
    """True when a proposal has what adding it needs: a name, and a code unless it is an alternative investment."""
    return bool(spec.get("name")) and (bool(spec.get("code")) or spec.get("kind") == KIND_ALTERNATIVE)


def propose(text, label="", kind=""):
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
    if kind and scheme is None:
        # The file's Type wins over the guess: a fund's code is its AMFI scheme code, an alternative needs none.
        out["kind"] = kind
        if kind == KIND_FUND and key.isdigit():
            out["code"] = key
        elif kind == KIND_FOREIGN and key and not ISIN_RE.match(upper):
            out.update(code=upper, currency="USD", note="Foreign share: check its Yahoo code and currency.")
        elif kind == KIND_ALTERNATIVE:
            out.update(code="", name=label or key, note="Alternative investment: no code needed; add its values on its page.")
    out["ready"] = _ready(out)
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
            if not name or (not code and kind != KIND_ALTERNATIVE):
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


def review(profile, source, aliases=None, portfolio=None, broker=None):
    """Read the file and return a :class:`Review`; nothing is written. ``aliases`` maps the file's text to investments just added;
    ``portfolio`` and ``broker`` (chosen on the page) are used for rows that do not name their own."""
    from fees.services import imports

    out = Review()
    try:
        rows = imports.iter_rows(source)
    except Exception as exc:
        raise InvestmentsError("BAD_FILE", str(getattr(exc, "message", exc)) or "The file could not be read.") from exc
    cache = {}
    portfolios = {p.name.casefold(): p for p in Portfolio.objects.filter(profile=profile)}
    brokers = {b.name.casefold(): b for b in Broker.objects.filter(profile=profile)}
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
            line.name = get("label").strip() if out.mapping.get("label") != out.mapping.get("investment") else ""
            line.kind = kind_of(get("kind"))
            line.instrument = _match(profile, line.text, cache, aliases)
            if line.instrument is None and line.name:
                line.instrument = _match(profile, line.name, cache, aliases)
            if line.instrument is None and not line.text and line.name:
                line.text = line.name
            line.portfolio_name = " ".join(get("portfolio").split()) or (portfolio.name if portfolio else "")
            line.broker_name = " ".join(get("broker").split()) or (broker.name if broker else "")
            for name, known, new in ((line.portfolio_name, portfolios, out.new_portfolios), (line.broker_name, brokers, out.new_brokers)):
                if name and name.casefold() not in known and name.casefold() not in {n.casefold() for n in new}:
                    new.append(name)
            line.units, line.price, line.amount = _number(get("units")), _number(get("price")), _number(get("amount"))
            line.charges = _number(get("charges")) or Decimal(0)
            line.folio = get("folio").strip()
            if line.price is None and line.units and line.amount:
                line.price = (line.amount / line.units).quantize(Decimal("0.0001"))
            spec = None
            if line.instrument is None and line.text:
                spec = next((m for m in out.missing if m["text"] == line.text), None)
                if spec is None:
                    spec = propose(line.text, line.name, line.kind)
                    out.missing.append(spec)
            if line.day is None:
                line.problem = "unreadable date"
            elif line.instrument is None and not line.text:
                line.problem = "no investment given"
            elif line.instrument is None and not spec["ready"]:
                line.problem = f"{line.text!r} is not in the program yet: check its details below"
            elif not line.units or not line.price:
                line.problem = "units or price missing"
            elif not line.portfolio_name or not line.broker_name:
                line.problem = "no portfolio or broker: fill the column, or choose them above"
            line.new_investment = line.instrument is None and spec is not None and spec["ready"]
            out.lines.append(line)
    _mark_matches(profile, out)
    return out


def _mark_matches(profile, out):
    awaiting = list(Transaction.objects.filter(profile=profile, status=STATUS_AWAITING, side="buy"))
    used = set()
    for line in out.lines:
        if line.problem or line.instrument is None:   # an investment added by this file has nothing to complete or duplicate
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
def apply(profile, user, source, *, portfolio=None, broker=None, aliases=None):
    """Save every usable line in date order, all or nothing: first the investments, portfolios and brokers the file names that the
    profile does not have yet. Returns ``(made, completed, skipped)``."""
    aliases = dict(aliases or {})
    result = review(profile, source, aliases, portfolio=portfolio, broker=broker)
    if result.problems:
        raise InvestmentsError("NOT_APPLICABLE", f"{len(result.problems)} line(s) have problems, so nothing was saved. Fix them and try again.", 409)
    added = [m for m in result.missing if m["ready"] and any(l.new_investment and l.text == m["text"] for l in result.lines)]
    if added:
        aliases.update(create_missing(profile, user, added))
    for name in result.new_portfolios:
        masters.add_portfolio(profile, user, name)
    for name in result.new_brokers:
        masters.add_broker(profile, user, name)
    if added or result.new_portfolios or result.new_brokers:
        result = review(profile, source, aliases, portfolio=portfolio, broker=broker)
        if result.problems:
            raise InvestmentsError("NOT_APPLICABLE", f"{len(result.problems)} line(s) have problems, so nothing was saved.", 409)
    portfolios = {p.name.casefold(): p for p in Portfolio.objects.filter(profile=profile)}
    brokers = {b.name.casefold(): b for b in Broker.objects.filter(profile=profile)}
    made = completed = 0
    for line in sorted(result.usable, key=lambda l: (l.day, 0 if l.side == "buy" else 1, l.number)):
        portfolio = portfolios[line.portfolio_name.casefold()]
        broker = brokers[line.broker_name.casefold()]
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
