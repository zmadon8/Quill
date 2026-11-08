"""Feebook read service for the Fee Register (T3.2, R-RD-1, brief 6.2).

Ports ``feebookService.ts`` (``listFeebook``) to the Django ORM. The Feebook is a
register of PAYMENTS, not memos: it shows one row per payment ALLOCATION (a
memo's share of a payment), plus one row per unaccounted payment (a payment with
no allocation). A payment split across several memos therefore shows one line per
memo, while a memo-less payment shows a single line.

Each row is labelled by Payment Type, computed from ALL of the payment's
allocations (ignoring the active filters): "Single" when the payment has exactly
one allocation, "Multiple" when it has more than one. For a Multiple payment the
sibling memo numbers are surfaced in ``group_memo_numbers`` so the user can see
which memos were settled together; a draft memo (no number) renders as
``"(draft)"``. An unaccounted row is labelled "Single" with an allocation count
of 1 and no group.

Money per row: ``amount_paid`` is the allocation NET (or, for an unaccounted
payment, the payment NET); ``tds`` is the allocation (or payment) TDS; and
``paid_plus_tds`` is the GROSS (``amount + tds``, via ``payments.gross``).
``memo_total`` is the effective memo total resolved through the single fee rule
(``memo_fees.effective_total_fees``), or ``None`` for an unaccounted row. The
``payment_details`` note is a secret and is NEVER included in any row.

Server-enforced Initial-FY cutoff (brief 6.2): payments whose payment-date
financial year is BEFORE ``FeesSettings.feebook_start_year`` are never surfaced,
for allocated AND unaccounted rows, regardless of what the caller requests
(payments pre-dating active record-keeping are historical only).

Filters (brief 6.2):

* ``financial_year``  (payment-date FY): applies to BOTH kinds of row. The
  Feebook FY is the financial year of the PAYMENT DATE, not the memo's billing
  year (a memo billed in one FY can be paid in a later FY), via
  ``financial_year.derive_financial_year``.
* ``firm_id`` and ``partner_id`` (alias ``group_id``): allocation rows only.
  Unaccounted rows have no memo and so no firm or group; they IGNORE these
  filters and still appear (Q7, deliberate: they are not tied to a firm). A
  ``partner_id`` of ``"none"`` is a no-op (mirrors ``memo_lists``).
* ``bank_account_id``: applies to BOTH kinds of row.
* ``unaccounted_only``: suppresses the allocation rows, leaving only
  unaccounted payments.

Ordering: the combined rows are sorted by ``date_of_payment`` descending, then
``payment_id`` descending, with allocations within one payment staying in
allocation-id order (a stable sort preserves the query order).

Scoping (design section 11): every query is filtered by ``profile`` like the
sibling services. This is a pure READ: it never bumps ``data_version``.

Query-count discipline (asserted in the tests with ``assertNumQueries``): one
query reads the settings cutoff; one query groups every payment's allocation
memo numbers for the Single or Multiple label; one query reads the allocation
rows (``select_related`` on memo, firm, matter and bank so their names cost no
per-row query); one query reads the unaccounted rows. The payment-date FY cutoff
and filter are applied in Python (the Indian financial year is not expressed in
portable SQL), so they add no query. When ``unaccounted_only`` is set the
allocation-row query is skipped.

This module never multiplies a fee count by its per-unit rate (memo totals come
from ``memo_fees``), so the single-fee-rule guard in ``test_memo_fees`` holds.
"""
from __future__ import annotations

from fees.models import Allocation, Payment
from fees.services import memo_fees
from fees.services.financial_year import derive_financial_year
from fees.services.money import round2
from fees.services.payments import gross
from fees.services.settings import get_settings

__all__ = ["list_feebook"]

#: Shown in place of a draft memo's (missing) number in a group listing.
_DRAFT_LABEL = "(draft)"


def _group_memo_numbers(profile):
    """Maps each payment id to its allocated memo numbers, in allocation-id order.

    One query over the profile's allocations (ordered by payment then allocation
    id) joined to the memo. A draft memo (``memo_number`` is ``None``) contributes
    ``"(draft)"``. Used to label each row Single vs Multiple and to list the
    memos a Multiple payment settled together, computed from ALL allocations so
    the label ignores the active filters.
    """
    groups = {}
    rows = (
        Allocation.objects.filter(profile=profile)
        .order_by("payment_id", "id")
        .values_list("payment_id", "memo__memo_number")
    )
    for payment_id, memo_number in rows:
        groups.setdefault(payment_id, []).append(
            memo_number if memo_number is not None else _DRAFT_LABEL
        )
    return groups


def _allocation_rows(profile, filters):
    """The allocation feebook rows (one per memo-share), newest payment first.

    One query (``select_related`` on the payment, memo, firm, matter and bank so
    their fields cost no per-row query). Applies the memo-based filters
    (``firm_id`` and ``partner_id`` / ``group_id``) in the query; the FY cutoff
    and FY filter are applied by the caller in Python on the payment date.
    """
    qs = (
        Allocation.objects.filter(profile=profile)
        .select_related(
            "payment",
            "payment__bank_account",
            "memo",
            "memo__firm",
            "memo__matter",
        )
        .order_by("-payment__date_of_payment", "-payment_id", "id")
    )

    firm_id = filters.get("firm_id")
    if firm_id is not None:
        qs = qs.filter(memo__firm_id=firm_id)

    # The original UI calls this "partner"; the model field is group. A value of
    # "none" is a no-op (mirrors memo_lists).
    group_id = filters.get("partner_id", filters.get("group_id"))
    if group_id == "none":
        pass
    elif group_id is not None:
        qs = qs.filter(memo__group_id=group_id)

    bank_account_id = filters.get("bank_account_id")
    if bank_account_id is not None:
        qs = qs.filter(payment__bank_account_id=bank_account_id)

    return qs


def _unaccounted_rows(profile, filters):
    """The unaccounted feebook rows (payments with no allocation), newest first.

    One query (``select_related`` on the bank account). Not constrained by the
    memo-based filters (Q7): an unaccounted payment has no memo and so no firm or
    group, but it DOES honour ``bank_account_id``. The FY cutoff and FY filter are
    applied by the caller in Python on the payment date.
    """
    qs = (
        Payment.objects.filter(profile=profile, allocations__isnull=True)
        .select_related("bank_account")
        .order_by("-date_of_payment", "-id")
    )
    bank_account_id = filters.get("bank_account_id")
    if bank_account_id is not None:
        qs = qs.filter(bank_account_id=bank_account_id)
    return qs


def _passes_fy(date_of_payment, initial_fy, financial_year):
    """Whether a payment date clears the cutoff and the optional FY filter.

    ``False`` when the payment-date FY is before ``initial_fy`` (the server
    cutoff) or, when a ``financial_year`` filter is given, when it does not equal
    that FY. Labels sort as plain strings (fixed-width year prefix), so a string
    comparison is the FY ordering.
    """
    fy = derive_financial_year(date_of_payment)
    if fy < initial_fy:
        return False
    if financial_year and fy != financial_year:
        return False
    return True


def _allocation_entry(alloc, group):
    """Builds one allocation feebook row dict (never carries ``payment_details``)."""
    payment = alloc.payment
    memo = alloc.memo
    allocation_count = len(group)
    is_multiple = allocation_count > 1
    bank = payment.bank_account
    return {
        "payment_id": payment.pk,
        "allocation_id": alloc.pk,
        "memo_id": memo.pk,
        "memo_number": memo.memo_number,
        "memo_total": memo_fees.effective_total_fees(memo),
        "firm_id": memo.firm_id,
        "firm_name": memo.firm.name if memo.firm_id is not None else None,
        "matter_id": memo.matter_id,
        "matter_name": memo.matter.name if memo.matter_id is not None else None,
        "amount_paid": round2(alloc.amount),
        "tds": round2(alloc.tds_amount),
        "paid_plus_tds": gross(alloc.amount, alloc.tds_amount),
        "payee": payment.payee,
        "date_of_payment": payment.date_of_payment,
        "bank_account_id": payment.bank_account_id,
        "bank_account_name": bank.name if bank is not None else None,
        "payment_mode": payment.payment_mode,
        "payment_type": "Multiple" if is_multiple else "Single",
        "allocation_count": allocation_count,
        # The memos settled together by this payment (only meaningful if > 1).
        "group_memo_numbers": list(group) if is_multiple else [],
    }


def _unaccounted_entry(payment):
    """Builds one unaccounted feebook row dict (never carries ``payment_details``)."""
    bank = payment.bank_account
    return {
        "payment_id": payment.pk,
        "allocation_id": None,
        "memo_id": None,
        "memo_number": None,
        "memo_total": None,
        "firm_id": None,
        "firm_name": None,
        "matter_id": None,
        "matter_name": None,
        "amount_paid": round2(payment.amount),
        "tds": round2(payment.tds_amount),
        "paid_plus_tds": gross(payment.amount, payment.tds_amount),
        "payee": payment.payee,
        "date_of_payment": payment.date_of_payment,
        "bank_account_id": payment.bank_account_id,
        "bank_account_name": bank.name if bank is not None else None,
        "payment_mode": payment.payment_mode,
        "payment_type": "Single",
        "allocation_count": 1,
        "group_memo_numbers": [],
    }


def list_feebook(profile, filters=None):
    """Lists the Feebook rows for ``profile`` (R-RD-1, brief 6.2).

    Returns a list of row dicts: one per payment allocation plus one per
    unaccounted payment, sorted by ``date_of_payment`` descending then
    ``payment_id`` descending. ``filters`` is an optional dict with any of
    ``financial_year`` (payment-date FY, both kinds of row), ``firm_id`` and
    ``partner_id`` (alias ``group_id``; allocation rows only, ``"none"`` is a
    no-op), ``bank_account_id`` (both kinds of row) and ``unaccounted_only``
    (suppresses the allocation rows).

    The Initial-FY cutoff (``FeesSettings.feebook_start_year``) is enforced on
    the server for both kinds of row and cannot be bypassed by the caller. The
    unaccounted rows ignore the firm and group filters and still appear (Q7).
    ``payment_details`` is never included. A pure read: it does NOT bump
    ``data_version``.
    """
    filters = filters or {}
    initial_fy = get_settings(profile)["feebook_start_year"]
    financial_year = filters.get("financial_year")

    entries = []

    if not filters.get("unaccounted_only"):
        groups = _group_memo_numbers(profile)
        for alloc in _allocation_rows(profile, filters):
            if not _passes_fy(alloc.payment.date_of_payment, initial_fy, financial_year):
                continue
            entries.append(_allocation_entry(alloc, groups.get(alloc.payment_id, [])))

    for payment in _unaccounted_rows(profile, filters):
        if not _passes_fy(payment.date_of_payment, initial_fy, financial_year):
            continue
        entries.append(_unaccounted_entry(payment))

    # Combine by date desc, then payment id desc (stable: allocation-id order
    # within one payment is preserved from the query ordering).
    entries.sort(key=lambda row: (row["date_of_payment"], row["payment_id"]), reverse=True)
    return entries
