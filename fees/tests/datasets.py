"""Seeded planning-dataset generator for the Fee Register memory and throughput tests (R-NFR-7).

``build_planning_dataset(profile, ...)`` fills one profile with a coherent, FK-valid fee dataset at the
RAM-budget planning size (6,000 memos, 8,000 payments, 9,000 allocations over several financial years)
using ``bulk_create`` so it builds in well under 30 seconds even at full size. ``random.Random(seed)``
makes it deterministic so tests are reproducible.

The amounts are plausible and consistent (never negative, so the check constraints hold) but the stored
memo totals ``amount_paid``/``amount_received``/``amount_tds`` are left at 0: this generator is for
memory and throughput tests, not for the correctness of totals, which the service layer owns. Memo
numbers are unique per profile (``"<fy>/<n>"``) so the unique constraint holds.

This module is test support under ``fees/tests``; it is imported by the dataset tests and later by the
``fees_memory_bench`` management command (T1.6). It is stdlib plus the fee models only and holds no
module-level mutable state.
"""
import datetime
import random
from decimal import Decimal

from fees.models import (
    Allocation,
    Firm,
    Group,
    Matter,
    Memo,
    Payment,
    PeriodAdjustment,
)

# The planning dataset spreads memos over this many financial years (RAM budget section 3 and 8).
_NUM_YEARS = 12
_FIRST_FY_START = 2015  # April of this calendar year is the first financial year in the dataset.

_NUM_FIRMS = 6


def _fy_label(start_year):
    """The Indian financial-year label for an April-starting year, e.g. 2015 -> ``"2015-16"``."""
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def _fy_bounds(start_year):
    """The first and last date of the April-starting financial year ``start_year``."""
    return datetime.date(start_year, 4, 1), datetime.date(start_year + 1, 3, 31)


def _date_in_fy(rng, start_year):
    """A random date inside the financial year that starts in April of ``start_year``."""
    first, last = _fy_bounds(start_year)
    span = (last - first).days
    return first + datetime.timedelta(days=rng.randint(0, span))


def twelve_years_of_adjustments(profile, *, years=_NUM_YEARS, first_fy_start=_FIRST_FY_START):
    """Create one ``PeriodAdjustment`` per month for ``years`` financial years (12 x 12 by default).

    Months are 1 to 12 so the check constraint holds. Returns the number of rows created.
    """
    rows = [
        PeriodAdjustment(
            profile=profile,
            financial_year=_fy_label(first_fy_start + y),
            month=month,
            working_days=20,
        )
        for y in range(years)
        for month in range(1, 13)
    ]
    PeriodAdjustment.objects.bulk_create(rows, batch_size=500)
    return len(rows)


def build_planning_dataset(
    profile,
    *,
    memos=6000,
    payments=8000,
    allocations=9000,
    firms=_NUM_FIRMS,
    years=_NUM_YEARS,
    first_fy_start=_FIRST_FY_START,
    adjustments=True,
    seed=0,
):
    """Fill ``profile`` with a seeded, FK-valid fee dataset and return a counts summary dict.

    The children that need parent ids (memos need matters; allocations need memos and payments) are
    built by ``bulk_create``-ing the parents first, reading their ids back with ``values_list``, then
    building the children in memory and ``bulk_create``-ing those. No per-row saves and no per-row
    queries, so it stays well under the 30 second build gate at the planning size.

    Defaults are the planning size; pass smaller ``memos``/``payments``/``allocations`` to scale down.
    """
    rng = random.Random(seed)

    # Firms, one group each, and a handful of matters per group.
    firm_rows = [Firm(profile=profile, name=f"Firm {i:03d}") for i in range(firms)]
    Firm.objects.bulk_create(firm_rows, batch_size=500)
    firm_ids = list(
        Firm.objects.filter(profile=profile).order_by("pk").values_list("pk", flat=True)
    )

    group_rows = [Group(profile=profile, firm_id=fid, name="Main") for fid in firm_ids]
    Group.objects.bulk_create(group_rows, batch_size=500)
    group_by_firm = dict(
        Group.objects.filter(profile=profile).values_list("firm_id", "pk")
    )

    matters_per_firm = 8
    matter_rows = [
        Matter(
            profile=profile,
            firm_id=fid,
            group_id=group_by_firm[fid],
            name=f"Matter {fid}-{m}",
        )
        for fid in firm_ids
        for m in range(matters_per_firm)
    ]
    Matter.objects.bulk_create(matter_rows, batch_size=500)
    matter_triples = list(
        Matter.objects.filter(profile=profile)
        .order_by("pk")
        .values_list("pk", "firm_id", "group_id")
    )

    # Memos, spread across the financial years with a plausible non-negative total.
    memo_rows = []
    for n in range(memos):
        start_year = first_fy_start + rng.randrange(years)
        fy = _fy_label(start_year)
        matter_id, firm_id, group_id = matter_triples[rng.randrange(len(matter_triples))]
        total = Decimal(rng.randrange(1000, 500001)).quantize(Decimal("0.01"))
        memo_rows.append(
            Memo(
                profile=profile,
                memo_number=f"{fy}/{n}",
                financial_year=fy,
                seq=n,
                date=_date_in_fy(rng, start_year),
                matter_id=matter_id,
                firm_id=firm_id,
                group_id=group_id,
                addressee_line1=f"Addressee {n}",
                total_fees=total,
            )
        )
    Memo.objects.bulk_create(memo_rows, batch_size=500)
    memo_ids = list(
        Memo.objects.filter(profile=profile).order_by("pk").values_list("pk", flat=True)
    )

    # Payments, with a net amount and an auto-computed TDS at a plausible rate.
    payment_rows = []
    for _p in range(payments):
        start_year = first_fy_start + rng.randrange(years)
        amount = Decimal(rng.randrange(500, 200001)).quantize(Decimal("0.01"))
        rate = Decimal(rng.choice([0, 10])).quantize(Decimal("0.01"))
        tds = (amount * rate / Decimal(100)).quantize(Decimal("0.01"))
        payment_rows.append(
            Payment(
                profile=profile,
                amount=amount,
                tds_rate=rate,
                auto_tds=True,
                tds_amount=tds,
                date_of_payment=_date_in_fy(rng, start_year),
            )
        )
    Payment.objects.bulk_create(payment_rows, batch_size=500)
    payment_ids = list(
        Payment.objects.filter(profile=profile).order_by("pk").values_list("pk", flat=True)
    )

    # Allocations link a payment to a memo; both id pools are already in memory.
    allocation_rows = []
    for a in range(allocations):
        amount = Decimal(rng.randrange(0, 100001)).quantize(Decimal("0.01"))
        tds = Decimal(rng.randrange(0, 10001)).quantize(Decimal("0.01"))
        allocation_rows.append(
            Allocation(
                payment_id=payment_ids[a % len(payment_ids)],
                memo_id=memo_ids[rng.randrange(len(memo_ids))],
                profile=profile,
                amount=amount,
                tds_amount=tds,
            )
        )
    Allocation.objects.bulk_create(allocation_rows, batch_size=500)

    summary = {
        "firms": len(firm_ids),
        "groups": len(group_rows),
        "matters": len(matter_rows),
        "memos": len(memo_ids),
        "payments": len(payment_ids),
        "allocations": len(allocation_rows),
        "financial_years": years,
    }
    if adjustments:
        summary["adjustments"] = twelve_years_of_adjustments(
            profile, years=years, first_fy_start=first_fy_start
        )
    return summary
