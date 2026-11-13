"""The asset class of a fund, from AMFI's scheme category line (``Open Ended Schemes(Debt Scheme - Liquid Fund)``), else from its name.
Pure: no database. Quill's classes are equity, debt, gold and other, so hybrid funds are "other"."""
import re

EQUITY, DEBT, GOLD, OTHER = "equity", "debt", "gold", "other"

_GOLD = re.compile(r"\bgold\b", re.I)
_HYBRID = re.compile(r"\b(hybrid|balanced|arbitrage|multi[ -]?asset|equity savings|dynamic asset allocation)\b", re.I)
_DEBT = re.compile(r"\b(liquid|overnight|money market|gilt|debt|bond|income|ultra short|low duration|short duration|medium duration|"
                   r"long duration|corporate bond|banking and psu|floater|credit risk|fixed maturity|fmp|treasury)\b", re.I)


def from_name(name):
    """A guess from the fund's name alone: Gold; Hybrid, Balanced, Arbitrage, Multi Asset (other); Liquid, Overnight, Money Market, Gilt, Debt,
    Bond, Income and the like (debt); otherwise equity."""
    name = name or ""
    if _GOLD.search(name):
        return GOLD
    if _HYBRID.search(name):
        return OTHER
    if _DEBT.search(name):
        return DEBT
    return EQUITY


def from_category(category):
    """The class named by a category line, or None when the line does not settle it (Index Funds, FoF, Solution Oriented ...)."""
    text = category or ""
    if _GOLD.search(text):
        return GOLD
    if re.search(r"\bdebt scheme\b", text, re.I):
        return DEBT
    if re.search(r"\bhybrid scheme\b", text, re.I):
        return OTHER
    if re.search(r"\bequity scheme\b", text, re.I):
        return EQUITY
    return None


def for_fund(category, name):
    """The asset class to give a new fund: the category when it settles it, else the name's guess."""
    return from_category(category) or from_name(name)
