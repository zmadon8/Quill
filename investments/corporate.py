"""Corporate actions in the units arithmetic (plan 8 and 16.2). Pure Python, no Django imports.

* ``events(actions)`` turns applied actions into lot events: a split multiplies every lot's units (cost and purchase dates unchanged);
  a bonus adds a lot at zero cost dated the ex-date, with its own holding period (CA to confirm the treatment).
* ``basis_factor(actions, day)``: for a split-adjusted price series, the factor that expresses the units held on ``day`` on the
  series' basis, i.e. the product of every applied action after ``day``. A raw series needs no factor.
"""
from decimal import Decimal

from investments import lots

ONE = Decimal(1)


def events(actions):
    """``actions`` is ``[(id, kind, ex_date, factor_or_ratio)]`` where a split gives its factor (new/old) and a bonus its ratio (new/old)."""
    out = []
    for pk, kind, ex_date, value in actions:
        if kind == "split":
            out.append(lots.Event(lots.SPLIT, ex_date, Decimal(value), None, ("ca", pk), order=pk))
        elif kind == "bonus":
            out.append(lots.Event(lots.BONUS, ex_date, Decimal(value), None, ("ca", pk), order=pk))
    return out


def basis_factor(actions, day, basis):
    """Units-on-basis multiplier for a valuation on ``day`` (plan 16.2)."""
    if basis != "split_adjusted":
        return ONE
    factor = ONE
    for _pk, kind, ex_date, value in actions:
        if ex_date > day:
            factor *= Decimal(value) if kind == "split" else (ONE + Decimal(value))
    return factor
