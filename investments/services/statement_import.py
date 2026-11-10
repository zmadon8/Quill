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

How the units were acquired (owner round 2026-11): a row may say it is a purchase, bonus shares, units from a split, shares received on a
demerger or another no-cost entry, in an Origin column or in the Transaction type cell (the word "Bonus"), and the person can set it for
any row on the review page ("Treated as"). A purchase still needs a price. The others are saved at no cost and may belong to a corporate
action recorded on the Corporate actions page, which is found by the investment and date: a bonus or split that action adds automatically
is skipped (it would be counted twice); a split or demerger with no recorded action is a problem to fix first. A row with units but no
price and no origin is never imported as a purchase: it waits for the person to say what it is.
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
    CA_BONUS, CA_DEMERGER, CA_SPLIT, HOLDABLE_KINDS, KIND_ALTERNATIVE, KIND_FOREIGN, KIND_FUND, KIND_SHARE, METHOD_EVENTS, ORIGIN_BONUS,
    ORIGIN_DEMERGER, ORIGIN_OTHER, ORIGIN_PURCHASE, ORIGIN_SPLIT, ORIGINS, STATUS_AWAITING, ZERO_PRICE_ORIGINS, AmfiScheme, Broker,
    CorporateAction, CorporateActionResponse, Folio, Instrument, Portfolio, Transaction,
)
from investments.services import masters, transactions as tx

#: Each key's possible headings, tried in order (an exact heading first, then a heading containing it). Order matters: "Transaction
#: type" is the buy or sell column and plain "Type" the investment's type when a file has both.
COLUMNS = {
    "date": ("date", "trade date", "transaction date", "date of transaction", "order date", "nav date"),
    # Claimed before "side" so a heading like "Acquisition type" is not taken for the buy or sell column. Exact headings only.
    "origin": ("origin", "how acquired", "acquired as", "acquisition type", "acquisition", "transaction origin"),
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
EXACT_ONLY = {"portfolio", "broker", "origin"}
SELL_WORDS = ("sell", "sale", "redeem", "redemption", "s", "switch out", "switch-out")
AWAITING_DAYS = 10
#: The types a missing investment can be added as from a file. An alternative investment needs no code (it has no price feed).
ADDABLE_KINDS = ((KIND_SHARE, "Share or ETF"), (KIND_FUND, "Mutual fund"), (KIND_FOREIGN, "Foreign share"), (KIND_ALTERNATIVE, "Alternative"))
#: Words in a Type cell, and the type they mean.
KIND_WORDS = ((KIND_FUND, ("mutual fund", "fund", "mf", "scheme", "sip")), (KIND_FOREIGN, ("foreign", "us share", "us stock", "international")),
              (KIND_ALTERNATIVE, ("alternative", "ppf", "fd", "fixed deposit", "bond", "gold", "property", "real estate", "nps", "epf", "other")),
              (KIND_SHARE, ("share", "equity", "stock", "etf", "shares")))
#: Words in an Origin cell (or in the Transaction type cell), and how the units were acquired.
ORIGIN_WORDS = (
    (ORIGIN_BONUS, ("bonus", "bonus shares", "bonus share", "bonus issue", "bonus allotment")),
    (ORIGIN_SPLIT, ("split", "stock split", "share split", "sub division", "subdivision")),
    (ORIGIN_DEMERGER, ("demerger", "demerged", "de merger", "demerger shares", "spin off", "spinoff")),
    (ORIGIN_OTHER, ("gift", "gifted", "transfer in", "inheritance", "inherited", "free", "no cost", "nil cost", "other")),
    (ORIGIN_PURCHASE, ("purchase", "buy", "bought", "sip")),
)
#: How close (in days) a row's date must be to a corporate action's ex-date for the row to be taken as belonging to it.
ACTION_DAYS = 5
ISIN_RE = re.compile(r"^IN[A-Z0-9]{10}$")
SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9&\-.^]{0,24}$")


def origin_of(text):
    """How the units were acquired, from an Origin or Transaction type cell: bonus, split, demerger, other or purchase; "" when blank or
    not recognised (a plain "Buy" or "Sell" says nothing the file did not already say, so it counts as purchase only when spelled out)."""
    t = " ".join((text or "").lower().replace("_", " ").replace("-", " ").split())
    if not t:
        return ""
    for origin, words in ORIGIN_WORDS:
        if t in words or any(t.startswith(w + " ") for w in words if len(w) > 3):
            return origin
    return ""


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
    origin: str = ORIGIN_PURCHASE   # how the units were acquired (the file's word, or the person's choice on the review page)
    origin_stated: bool = False     # the file or the person said so; otherwise a missing price is a problem, not a bonus
    action: object = None           # the corporate action a bonus, split or demerger row belongs to
    covered: str = ""               # why the row is skipped: the program already adds these units itself

    @property
    def get_origin_label(self):
        return dict(ORIGINS).get(self.origin, self.origin).lower()


@dataclass
class Review:
    lines: list = field(default_factory=list)
    mapping: dict = field(default_factory=dict)
    missing: list = field(default_factory=list)   # one proposal per investment the program does not have yet
    new_portfolios: list = field(default_factory=list)   # names the profile does not have yet (added when saving)
    new_brokers: list = field(default_factory=list)

    @property
    def usable(self):
        return [l for l in self.lines if not l.problem and not l.duplicate and not l.covered]

    @property
    def covered(self):
        return [l for l in self.lines if l.covered and not l.problem]

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


def _load_actions(profile):
    """The bonuses, splits and demergers on investments the profile can see, each with ``response`` (this profile's answer, or None)."""
    answers = {r.action_id: r for r in CorporateActionResponse.objects.filter(profile=profile)}
    rows = list(CorporateAction.objects.filter(Q(instrument__profile=None) | Q(instrument__profile=profile), kind__in=(CA_BONUS, CA_SPLIT, CA_DEMERGER))
                .select_related("instrument", "target_instrument"))
    for a in rows:
        a.response = answers.get(a.pk)
    return rows


def _find_action(actions, instrument, origin, day):
    """The recorded action a row of this origin belongs to: a bonus or split of the investment, or a demerger into it, whose ex-date is within
    ``ACTION_DAYS`` of the row's date (the nearest one)."""
    kind = {ORIGIN_BONUS: CA_BONUS, ORIGIN_SPLIT: CA_SPLIT, ORIGIN_DEMERGER: CA_DEMERGER}.get(origin)
    best = None
    for a in actions:
        target = a.target_instrument_id if origin == ORIGIN_DEMERGER else a.instrument_id
        if a.kind != kind or instrument is None or target != instrument.pk:
            continue
        gap = abs((day - a.ex_date).days)
        if gap <= ACTION_DAYS and (best is None or gap < best[0]):
            best = (gap, a)
    return best[1] if best else None


def _judge_origin(line, actions):
    """Decide what the row needs given how its units were acquired: set ``line.problem``, ``line.covered`` and ``line.action``.
    Only called for a row whose date, investment, units, portfolio and broker are in order."""
    if line.side == "sell" and line.origin != ORIGIN_PURCHASE:
        line.problem = "a sale cannot be bonus shares, a split, a demerger or a no-cost entry: choose Purchase in the Treated as column"
        return
    if line.origin == ORIGIN_PURCHASE:
        return
    if line.origin == ORIGIN_OTHER:
        return
    line.action = _find_action(actions, line.instrument, line.origin, line.day)
    response = getattr(line.action, "response", None)
    applied = response is not None and response.status == "applied"
    if line.origin == ORIGIN_DEMERGER:
        if line.instrument is None:
            line.problem = "shares received on a demerger: add the new company first, then record the demerger on the Corporate actions page"
        elif line.action is None:
            line.problem = f"no demerger into {line.instrument.name} is recorded near {line.day:%-d %b %Y}: record it on the Corporate actions page first"
        elif not applied:
            line.problem = "apply the demerger on the Corporate actions page first: these shares take their cost from the parent's shares"
    elif line.origin == ORIGIN_SPLIT:
        if line.action is None:
            line.problem = f"no split of this investment is recorded near {line.day:%-d %b %Y}: record it on the Corporate actions page first"
    if line.problem:
        return
    if line.origin in (ORIGIN_BONUS, ORIGIN_SPLIT) and line.action is not None and applied and response.method == METHOD_EVENTS:
        line.covered = (f"the program already adds the units of the {line.origin} of {line.action.ex_date:%-d %b %Y} itself, so this row would count "
                        "them twice. To record them as transactions instead, change that on the Corporate actions page")


def review(profile, source, aliases=None, portfolio=None, broker=None, origins=None):
    """Read the file and return a :class:`Review`; nothing is written. ``aliases`` maps the file's text to investments just added;
    ``portfolio`` and ``broker`` (chosen on the page) are used for rows that do not name their own. ``origins`` maps a line number (as text)
    to the origin the person chose for it on the review page, which wins over the file's own word."""
    from fees.services import imports

    out = Review()
    try:
        rows = imports.iter_rows(source)
    except Exception as exc:
        raise InvestmentsError("BAD_FILE", str(getattr(exc, "message", exc)) or "The file could not be read.") from exc
    cache = {}
    portfolios = {p.name.casefold(): p for p in Portfolio.objects.filter(profile=profile)}
    brokers = {b.name.casefold(): b for b in Broker.objects.filter(profile=profile)}
    actions = _load_actions(profile)
    origins = origins or {}
    valid_origins = {value for value, _label in ORIGINS}
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
            # How the units were acquired: the person's choice for this line, else the file's Origin cell, else a word such as "Bonus" in the
            # buy or sell cell. A plain purchase is never assumed for a row with no price (below).
            chosen = origins.get(str(number))
            stated = chosen if chosen in valid_origins else (origin_of(get("origin")) or origin_of(get("side")))
            line.origin = stated or ORIGIN_PURCHASE
            line.origin_stated = line.origin != ORIGIN_PURCHASE
            if line.origin in ZERO_PRICE_ORIGINS:
                line.price = Decimal(0)
            elif line.origin == ORIGIN_OTHER and not line.price:
                line.price = Decimal(0)
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
            elif not line.units or (line.origin == ORIGIN_PURCHASE and not line.price):
                line.problem = "units or price missing"
                if line.units and line.side == "buy":
                    line.problem += ": if these units came free (bonus shares, a split, shares received on a demerger), choose that in the Treated as column"
            elif not line.portfolio_name or not line.broker_name:
                line.problem = "no portfolio or broker: fill the column, or choose them above"
            else:
                _judge_origin(line, actions)
            line.new_investment = line.instrument is None and spec is not None and spec["ready"]
            out.lines.append(line)
    _mark_matches(profile, out)
    return out


def _mark_matches(profile, out):
    awaiting = list(Transaction.objects.filter(profile=profile, status=STATUS_AWAITING, side="buy"))
    used = set()
    for line in out.lines:
        if line.problem or line.covered or line.instrument is None:   # an investment added by this file has nothing to complete or duplicate
            continue
        total = line.units * line.price + line.charges
        for a in (awaiting if line.origin == ORIGIN_PURCHASE else []):
            if a.pk in used or a.instrument_id != line.instrument.pk or not a.amount:
                continue
            if abs((line.day - a.date).days) <= AWAITING_DAYS and abs(total - a.amount) <= tx.tolerance_for(a.amount) * 10:
                line.completes = a
                used.add(a.pk)
                break
        if line.completes is None and Transaction.objects.filter(profile=profile, instrument=line.instrument, date=line.day, side=line.side,
                                                                  units=line.units, origin=line.origin).exists():
            line.duplicate = True
        elif line.action is not None and Transaction.objects.filter(profile=profile, corporate_action=line.action, instrument=line.instrument,
                                                                    units=line.units, portfolio__name__iexact=line.portfolio_name,
                                                                    broker__name__iexact=line.broker_name).exists():
            # Units already recorded against the same action (for example created from the Corporate actions page, dated the ex-date).
            line.duplicate = True


@transaction.atomic
def apply(profile, user, source, *, portfolio=None, broker=None, aliases=None, origins=None):
    """Save every usable line in date order, all or nothing: first the investments, portfolios and brokers the file names that the
    profile does not have yet. Returns ``(made, completed, skipped)`` (skipped: duplicates, and rows whose units the program already adds)."""
    aliases = dict(aliases or {})
    result = review(profile, source, aliases, portfolio=portfolio, broker=broker, origins=origins)
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
        result = review(profile, source, aliases, portfolio=portfolio, broker=broker, origins=origins)
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
                           price=line.price, charges=line.charges, folio=folio, reference=f"Imported line {line.number}", origin=line.origin,
                           corporate_action=line.action)
        made += 1
    return made, completed, sum(1 for l in result.lines if l.duplicate or l.covered)
