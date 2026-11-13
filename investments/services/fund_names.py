"""Split an AMFI scheme name into (base fund name, plan, option), and put them back as "Base Fund Regular Plan Growth Option".

Pure: no database, no network. AMFI's names are inconsistent: the plan and option may be separate " - " columns, run together with
or without hyphens, in either order, with or without the words "Plan" and "Option", and older lines say "Dividend" where newer
ones say "IDCW". The parser reads only the tail of the name, word by word from the end, as long as the words belong to a small
vocabulary, so a fund called "Reliance Growth Fund" keeps its "Growth".

The parser itself never guesses the plan: a line such as "HDFC Flexi Cap Fund - Growth Plan" does not say Direct or Regular, so
``parse`` returns a blank plan for it. The guess is made elsewhere, from the database: since SEBI's 2013 rule every open-ended scheme
offers both a Direct and a Regular plan, so a scheme whose plan is blank but which has a Direct sibling with the same ``base_key`` is
Regular (``schemes.infer_regular_plans``). With no Direct sibling (ETFs, closed-ended and interval schemes) the plan stays blank.
"""
import re

PLAN_DIRECT = "Direct"
PLAN_REGULAR = "Regular"

_SPLIT = re.compile(r"[^\s\-\u2013\u2014/,()]+")
_IDCW_PHRASE = re.compile(r"income\s+distribution\s+(?:cum|and|&|-)\s+capital\s+withdrawal", re.IGNORECASE)
_PLANS = {"direct": PLAN_DIRECT, "dir": PLAN_DIRECT, "regular": PLAN_REGULAR, "reg": PLAN_REGULAR}
_IDCW = {"idcw", "dividend", "div"}
_PAYOUT = {"payout", "pay-out"}
_REINVEST = {"reinvestment", "reinvest", "reinv"}
_FILLER = {"plan", "option", "scheme"}
_FREQUENCY = {"daily", "weekly", "fortnightly", "monthly", "quarterly", "half", "yearly", "annual", "annually", "semi"}
_TRIM = " \t-\u2013\u2014/,("


def parse(name):
    """``(base, plan, option)``. plan is "Direct", "Regular" or ""; option is "Growth", "Bonus", "IDCW", "IDCW Payout",
    "IDCW Reinvestment", "IDCW Transfer" (optionally prefixed by a frequency, e.g. "Monthly IDCW Payout") or "".
    A name with no recognisable plan or option comes back whole, with both blank."""
    text = _IDCW_PHRASE.sub("IDCW", (name or "").strip())
    tokens = [(m.group(0).lower(), m.start()) for m in _SPLIT.finditer(text)]
    taken = []          # tokens read from the end, last word first
    seen_idcw = False
    for word, _ in reversed(tokens[1:] if len(tokens) > 1 else []):
        if word in _PLANS or word in _FILLER or word in _PAYOUT or word in _REINVEST or word in ("growth", "bonus", "transfer"):
            pass
        elif word in _IDCW:
            seen_idcw = True
        elif word == "of" and taken and taken[-1] in _IDCW:
            pass
        elif word in _FREQUENCY and seen_idcw:
            pass
        else:
            break
        taken.append(word)
    consumed = taken[::-1]
    if not any(w in _PLANS or w in _IDCW or w in _PAYOUT or w in _REINVEST or w in ("growth", "bonus") for w in consumed):
        return (name or "").strip(), "", ""
    start = tokens[len(tokens) - len(taken)][1]
    base = text[:start].rstrip(_TRIM)
    plan = next((_PLANS[w] for w in consumed if w in _PLANS), "")
    return base, plan, _option(consumed)


def base_key(name):
    """The base fund name, lower-cased with whitespace squeezed, to match the Direct and Regular lines of one fund."""
    return " ".join(parse(name)[0].lower().split())


def _option(words):
    idcw = any(w in _IDCW for w in words)
    payout = any(w in _PAYOUT for w in words)
    reinvest = any(w in _REINVEST for w in words)
    if idcw or payout or reinvest:
        label = "IDCW Reinvestment" if reinvest else "IDCW Payout" if payout else "IDCW Transfer" if "transfer" in words else "IDCW"
        freq = " ".join(w.capitalize() for w in words if w in _FREQUENCY)
        return f"{freq} {label}".strip()
    if "growth" in words:
        return "Growth"
    if "bonus" in words:
        return "Bonus"
    return ""


def compose(base, plan="", option=""):
    """"Base Fund Regular Plan Growth Option"; a missing plan or option is left out."""
    parts = [base]
    if plan:
        parts.append(f"{plan} Plan")
    if option:
        parts.append(f"{option} Option")
    return " ".join(p for p in parts if p)


def standard_name(name, plan="", option=""):
    """The standardised name for a raw AMFI name. A stored plan or option wins over the one read from the name."""
    base, found_plan, found_option = parse(name)
    return compose(base, plan or found_plan, option or found_option)


def plan_option(name, plan="", option=""):
    """``(plan, option)`` for a scheme: the stored values, else the ones read from the raw name (blank when the name does not say)."""
    _, found_plan, found_option = parse(name)
    return plan or found_plan, option or found_option
