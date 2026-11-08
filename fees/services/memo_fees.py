"""The single memo fee rule and derived values (R-MEMO-1, R-MEMO-7, brief 5.2 to 5.5).

Pure Python: only ``fees.services.money`` and the standard library (``decimal``,
``datetime``). No Django model import, so this module imports cheaply and is unit
tested as plain logic. It accepts either a Django ``Memo`` instance (attribute
access) or a plain ``dict`` / ``namedtuple`` (the real model exposes these as
attributes; staying attribute/dict-flexible keeps the module model-free).

``resolve_memo_fees`` is the ONE implementation of the "effective fees" rule
(R-MEMO-1). Every list, report, export and statistic must read the stored
``total_fees`` or call this, never re-derive ``num_appearances *
fees_per_appearance`` itself. ``fees/tests/test_memo_fees.py`` has a grep-style
guard test that fails if another ``fees`` module computes a line fee directly.

D3 asymmetry (deliberate, documented here and on ``resolve_memo_fees``):

* LINE customs (``custom_fees_appearances``, ``custom_fees_conferences``,
  ``custom_fees_misc``) follow the original TypeScript ``?? `` semantics: only
  ``None`` falls through to the computed value, so a line custom of exactly 0 IS
  a real override and yields 0 for that line.
* The TOTAL custom (``custom_total_fees``) follows the D3 fix (R-MEMO-1, brief
  15 Q1): 0 OR ``None`` means "no override", so the computed sum is used. The
  original TypeScript used ``!== null`` here (0 was an override); we deliberately
  deviate because the memo form can post ``custom_total_fees = 0`` meaning "no
  override".

Derived values (brief 5.3 to 5.5) are kept here too: ``net_of_tds`` (the memo's
informational net, distinct from the payment auto-TDS gross-up which is a
separate Phase T2.6 concern), ``status_and_due`` from a stored gross paid
amount, and ``compute_is_overdue``.

No module-level mutable state; all rounding goes through ``money.round2`` so
every amount is a two-decimal ``Decimal``.
"""
from __future__ import annotations

import datetime
from decimal import Decimal, InvalidOperation
from typing import NamedTuple, Optional, Union

from fees.services.money import round2

__all__ = [
    "MemoFees",
    "compute_fees_appearances",
    "compute_fees_conferences",
    "compute_total_fees",
    "compute_less_tds",
    "resolve_memo_fees",
    "effective_total_fees",
    "net_of_tds",
    "status_and_due",
    "compute_is_overdue",
]

Number = Union[Decimal, int, float, str]


class MemoFees(NamedTuple):
    """The resolved fees for a memo row, each a two-decimal ``Decimal``."""

    fees_appearances: Decimal
    fees_conferences: Decimal
    fees_misc: Decimal
    total_fees: Decimal


def _read(row, name: str):
    """Reads field ``name`` from an attribute or a dict key, so a Memo or a dict works."""
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name)


# ---------------------------------------------------------------------------
# Line and total computations (brief 5.2). All via money.round2 (Decimal).
# ---------------------------------------------------------------------------

def compute_fees_appearances(num: Number, rate: Number) -> Decimal:
    """``round2(num * rate)`` for the appearances line."""
    return round2(Decimal(str(num)) * Decimal(str(rate)))


def compute_fees_conferences(num: Number, rate: Number) -> Decimal:
    """``round2(num * rate)`` for the conferences line."""
    return round2(Decimal(str(num)) * Decimal(str(rate)))


def compute_total_fees(app: Number, conf: Number, misc: Number) -> Decimal:
    """``round2(app + conf + misc)``: the sum of the three fee lines."""
    return round2(Decimal(str(app)) + Decimal(str(conf)) + Decimal(str(misc)))


def compute_less_tds(total: Number, rate: Number) -> Decimal:
    """``round2(total * rate / 100)``: the TDS portion of ``total`` at ``rate`` percent."""
    return round2(Decimal(str(total)) * Decimal(str(rate)) / Decimal(100))


# ---------------------------------------------------------------------------
# The single fee rule (R-MEMO-1, brief 5.2, D3).
# ---------------------------------------------------------------------------

def _line_override(value) -> Optional[Decimal]:
    """A LINE custom is an override only when it is not None (TS ``??``: 0 is kept)."""
    if value is None:
        return None
    return Decimal(str(value))


def _total_override(value) -> Optional[Decimal]:
    """A TOTAL custom is an override only when it is not None AND not zero (D3)."""
    if value is None:
        return None
    dec = Decimal(str(value))
    if dec == 0:
        return None
    return dec


def resolve_memo_fees(row) -> MemoFees:
    """Resolves a memo row to its effective fees: the ONE rule (R-MEMO-1, brief 5.2).

    ``row`` is any object or dict carrying: ``num_appearances``,
    ``fees_per_appearance``, ``num_conferences``, ``fees_per_conference``,
    ``fees_misc_drafting``, ``custom_fees_appearances``,
    ``custom_fees_conferences``, ``custom_fees_misc``, ``custom_total_fees``.
    Override fields accept ``Decimal`` / ``int`` / ``None``.

    Rules::

        fees_appearances = custom_fees_appearances if set else round2(num_appearances * rate)
        fees_conferences = custom_fees_conferences if set else round2(num_conferences * rate)
        fees_misc        = custom_fees_misc        if set else fees_misc_drafting
        total_fees       = round2(custom_total_fees) if the total is a REAL override
                           else round2(app + conf + misc)

    D3 asymmetry (see the module docstring): a LINE custom of exactly 0 IS an
    override (matches the original TypeScript ``?? `` where only null falls
    through); the TOTAL custom of 0 OR None is NOT an override (D3 / brief 15 Q1,
    a deliberate deviation from the original ``!== null``).
    """
    line_app = _line_override(_read(row, "custom_fees_appearances"))
    fees_appearances = (
        round2(line_app)
        if line_app is not None
        else compute_fees_appearances(
            _read(row, "num_appearances"), _read(row, "fees_per_appearance")
        )
    )

    line_conf = _line_override(_read(row, "custom_fees_conferences"))
    fees_conferences = (
        round2(line_conf)
        if line_conf is not None
        else compute_fees_conferences(
            _read(row, "num_conferences"), _read(row, "fees_per_conference")
        )
    )

    line_misc = _line_override(_read(row, "custom_fees_misc"))
    fees_misc = (
        round2(line_misc)
        if line_misc is not None
        else round2(_read(row, "fees_misc_drafting"))
    )

    total_override = _total_override(_read(row, "custom_total_fees"))
    total_fees = (
        round2(total_override)
        if total_override is not None
        else compute_total_fees(fees_appearances, fees_conferences, fees_misc)
    )

    return MemoFees(fees_appearances, fees_conferences, fees_misc, total_fees)


def effective_total_fees(row) -> Decimal:
    """Convenience: just the effective ``total_fees`` for a memo row."""
    return resolve_memo_fees(row).total_fees


# ---------------------------------------------------------------------------
# Derived values (brief 5.3 to 5.5, R-MEMO-7).
# ---------------------------------------------------------------------------

def net_of_tds(total: Number, default_tds_rate: Number) -> Decimal:
    """The memo's informational net of TDS (brief 5.3).

    ``round2(total - round2(total * default_tds_rate / 100))``. This is the memo
    net-of-tds and is distinct from the payment auto-TDS gross-up (Phase T2.6).
    """
    total_dec = Decimal(str(total))
    return round2(total_dec - compute_less_tds(total_dec, default_tds_rate))


class MemoDue(NamedTuple):
    """The paid-driven derived values for a memo (brief 5.4)."""

    amount_due: Decimal
    status: str


def status_and_due(total: Number, amount_paid: Number) -> MemoDue:
    """Derives ``amount_due`` and ``status`` from the stored GROSS ``amount_paid`` (brief 5.4).

    ``amount_due = round2(total - amount_paid)`` (may be negative when overpaid).
    ``status`` is ``"Paid"`` when ``amount_paid >= total`` else ``"Unpaid"``; a
    total of 0 is ``"Paid"``.
    """
    total_dec = round2(total)
    paid_dec = round2(amount_paid)
    amount_due = round2(total_dec - paid_dec)
    status = "Paid" if paid_dec >= total_dec else "Unpaid"
    return MemoDue(amount_due, status)


def _to_date(value) -> Optional[datetime.date]:
    """Coerces a ``date`` / ``datetime`` / ISO ``YYYY-MM-DD`` string to a ``date``, else None."""
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if value is None:
        return None
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def compute_is_overdue(
    date,
    status: str,
    written_off: bool,
    overdue_days: int,
    now=None,
) -> bool:
    """Whether a memo is overdue (brief 5.5, R-MEMO-7).

    False if ``overdue_days <= 0``, or ``status == "Paid"``, or ``written_off``,
    or ``date`` is invalid. Otherwise the memo is overdue when its whole-day age
    is STRICTLY greater than ``overdue_days``:
    ``floor((now - date) / 1 day) > overdue_days``.

    ``date`` accepts a ``date`` or an ISO string; ``now`` defaults to today and
    is injectable for deterministic tests.
    """
    try:
        if int(overdue_days) <= 0:
            return False
    except (ValueError, TypeError, InvalidOperation):
        return False
    if status == "Paid" or written_off:
        return False
    memo_date = _to_date(date)
    if memo_date is None:
        return False
    today = _to_date(now) if now is not None else datetime.date.today()
    if today is None:
        return False
    age_days = (today - memo_date).days
    return age_days > int(overdue_days)
