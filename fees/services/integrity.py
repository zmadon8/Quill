"""Read-only data-integrity checker for the Fee Register (R-DATA-4, design section 4).

``fees_check`` recomputes every stored memo total from first principles and
REPORTS any mismatch; it never writes or fixes anything (design section 4:
"recomputes every stored total from first principles and returns mismatches").
It is the safety net used after a restore or import (later phases) and as a
nightly tripwire, and the T2.8 gate: after the seeded random operation
sequences of T2.5 / T2.6 it must report ZERO mismatches.

For every ``Memo`` in a profile it compares the stored columns against freshly
recomputed values:

* ``total_fees`` is recomputed via ``memo_fees.resolve_memo_fees`` (the ONE fee
  rule, R-MEMO-1; never recompute line fees inline, or the T2.2 guard test
  fails);
* the three paid columns are recomputed from the memo's ``Allocation`` rows,
  exactly as ``payments.recompute_paid`` would write them:

  * ``amount_received`` (NET)   = ``round2(sum(amount))``;
  * ``amount_tds``              = ``round2(sum(tds_amount))``;
  * ``amount_paid``     (GROSS) = ``round2(received + tds)``.

The allocation sums are fetched in ONE ``GROUP BY`` over the profile's
allocations (``values("memo_id").annotate(...)``), not an N+1 per memo; memos
with no allocation default to zero. Everything is scoped to one profile at a
time, so a mismatch in one profile is never attributed to another.

Public API::

    run_check(profile=None)
        -> ProfileReport                 when ``profile`` is a Profile
        -> list[ProfileReport]           when ``profile`` is None (every fees
                                         profile, excluding soft-deleted ones)

Each ``ProfileReport`` carries ``profile_id``, ``memos_checked`` and a list of
``Mismatch`` records (one record per differing FIELD, carrying ``memo_id``,
``memo_number``, ``field``, ``stored`` and ``expected``). ``summarise`` folds one
or many reports into counts for a command / log line.

Pure read: no model is mutated, no ``data_version`` bumped. No module-level
mutable state; ``diary`` is never imported.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, NamedTuple, Optional, Union

from django.db.models import Sum

from accounts.suite import KEY_FEES
from fees.models import Allocation, Memo
from fees.services.memo_fees import resolve_memo_fees
from fees.services.money import round2

__all__ = [
    "Mismatch",
    "ProfileReport",
    "CheckSummary",
    "check_profile",
    "run_check",
    "summarise",
]

_ZERO = Decimal("0.00")

#: The four stored columns we verify, in a stable report order.
_FIELDS = ("total_fees", "amount_paid", "amount_received", "amount_tds")


class Mismatch(NamedTuple):
    """One stored column of one memo that disagrees with its recomputed value."""

    memo_id: int
    memo_number: Optional[str]
    field: str
    stored: Decimal
    expected: Decimal


class ProfileReport(NamedTuple):
    """The result of checking one profile: how many memos, and every mismatch."""

    profile_id: int
    memos_checked: int
    mismatches: List[Mismatch]

    @property
    def ok(self) -> bool:
        """True when this profile has no mismatch."""
        return not self.mismatches


class CheckSummary(NamedTuple):
    """Folded counts over one or many ``ProfileReport`` objects."""

    profiles_checked: int
    memos_checked: int
    mismatches: int

    @property
    def ok(self) -> bool:
        """True when nothing drifted anywhere."""
        return self.mismatches == 0


def _allocation_totals(profile) -> dict:
    """Maps ``memo_id -> (net, tds)`` for the profile in ONE grouped query.

    A single ``GROUP BY`` over the profile's allocations (not an N+1 per memo).
    Memos with no allocation are simply absent and default to zero at the call
    site. Both sums are ``round2``-ed to two-decimal ``Decimal``.
    """
    rows = (
        Allocation.objects.filter(profile=profile)
        .values("memo_id")
        .annotate(net=Sum("amount"), tds=Sum("tds_amount"))
    )
    totals = {}
    for row in rows:
        net = round2(row["net"] or 0)
        tds = round2(row["tds"] or 0)
        totals[row["memo_id"]] = (net, tds)
    return totals


def _expected_for(memo, net: Decimal, tds: Decimal) -> dict:
    """The four expected stored values for a memo given its allocation sums.

    ``total_fees`` comes from the single fee rule (``resolve_memo_fees``); the
    three paid amounts mirror ``payments.recompute_paid``.
    """
    return {
        "total_fees": resolve_memo_fees(memo).total_fees,
        "amount_received": net,
        "amount_tds": tds,
        "amount_paid": round2(net + tds),
    }


def check_profile(profile) -> ProfileReport:
    """Checks one profile and returns a ``ProfileReport`` (read-only).

    Every ``Memo`` in the profile is compared field by field against its
    recomputed values; a differing field becomes one ``Mismatch`` entry. Nothing
    is written. The allocation sums are aggregated once (``_allocation_totals``)
    and looked up per memo in Python.
    """
    totals = _allocation_totals(profile)
    mismatches: List[Mismatch] = []
    memos_checked = 0

    for memo in Memo.objects.filter(profile=profile).iterator():
        memos_checked += 1
        net, tds = totals.get(memo.pk, (_ZERO, _ZERO))
        expected = _expected_for(memo, net, tds)
        for field in _FIELDS:
            stored = round2(getattr(memo, field))
            want = round2(expected[field])
            if stored != want:
                mismatches.append(
                    Mismatch(
                        memo_id=memo.pk,
                        memo_number=memo.memo_number,
                        field=field,
                        stored=stored,
                        expected=want,
                    )
                )

    return ProfileReport(
        profile_id=profile.pk, memos_checked=memos_checked, mismatches=mismatches
    )


def _fees_profiles():
    """Every live (not soft-deleted) Fee Register profile, ordered by id."""
    from accounts.models import Profile

    return Profile.objects.filter(
        program=KEY_FEES, deleted_at__isnull=True
    ).order_by("id")


def run_check(profile=None) -> Union[ProfileReport, List[ProfileReport]]:
    """Runs the integrity check (read-only); THE public entry point.

    * ``profile`` a ``Profile`` -> a single ``ProfileReport`` for it.
    * ``profile`` None -> a ``list`` of ``ProfileReport`` for every live Fee
      Register profile (``program == "fees"``, not soft-deleted), in id order.

    Never writes and never bumps ``data_version``.
    """
    if profile is not None:
        return check_profile(profile)
    return [check_profile(p) for p in _fees_profiles()]


def summarise(reports) -> CheckSummary:
    """Folds a ``ProfileReport`` or an iterable of them into ``CheckSummary`` counts."""
    if isinstance(reports, ProfileReport):
        reports = [reports]
    profiles_checked = 0
    memos_checked = 0
    mismatches = 0
    for report in reports:
        profiles_checked += 1
        memos_checked += report.memos_checked
        mismatches += len(report.mismatches)
    return CheckSummary(
        profiles_checked=profiles_checked,
        memos_checked=memos_checked,
        mismatches=mismatches,
    )
