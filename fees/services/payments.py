"""Payment and allocation services for the Fee Register (R-PAY-1 to R-PAY-7, R-DATA-4, R-DATA-6).

Ports ``paymentService.ts`` and ``paymentPrefill.ts`` to the Django ORM. A
received payment is NET money; it may be allocated across zero, one or several
memos through the ``Allocation`` table, which is the single source of truth for
how much a memo has been paid:

* zero allocations  -> an "unaccounted" payment (a memo may be attached later);
* one allocation    -> a normal single-memo payment;
* many allocations  -> one payment split across several memos.

A memo's GROSS paid amount is ``SUM(amount + tds_amount)`` of its allocations
(TDS is money paid on the client's behalf toward the memo). ``recompute_paid``
is the ONE place in the whole app that writes the stored
``Memo.amount_paid`` / ``amount_received`` / ``amount_tds`` columns; ``memos.py``
never writes them (it leaves them on edit, R-DATA-4). Keeping that invariant is
why a payment write must go through ``_write_allocations`` so the recompute runs
in the SAME transaction as the allocation change.

Auto-TDS gross-up (R-PAY-1), kept DISTINCT from the memo net-of-tds
(``memo_fees.net_of_tds``):

* the payment ``amount`` is NET (money actually received);
* when ``auto_tds`` is on, ``compute_auto_tds(amount, rate)`` grosses the net UP
  so that ``amount + tds`` equals the figure the client paid toward the memo:
  ``0`` if not ``0 < rate < 100`` else ``round2(amount*100/(100-rate) - amount)``.
  e.g. net 90 @ 10% -> TDS 10 (gross 100); net 9000 @ 10% -> TDS 1000.

This is NOT the memo's informational net-of-tds (``total - round2(total*rate/100)``);
the two are deliberately separate and both are kept.

Allocation rules: each allocation memo must exist in the same profile
(``MEMO_NOT_FOUND``); amounts are ``round2``-ed; the per-row TDS is taken AS SENT
(the client computes it; the server does NOT recompute per row). There is NO
server-side check that the allocations sum to the payment (Q10): the UI shows a
"Remaining" warning only.

The Q3 update re-derivation (R-PAY-4), precisely:

* ``allocations`` provided (even an explicit ``[]``) -> REPLACE with them (an
  explicit empty list makes the payment unaccounted);
* ``allocations`` OMITTED and exactly 1 existing allocation -> rebuild that one
  allocation as ``{same memo, new amount, new tds}``;
* ``allocations`` OMITTED and 0 or 2+ existing allocations -> Q3 FIX: KEEP the
  existing allocations UNCHANGED. The original wiped the 2+ case; we deliberately
  fix it. "Omitted" means the caller did not pass an ``allocations`` key at all;
  an explicit ``[]`` is NOT omitted (use ``_OMITTED`` sentinel to tell them apart).

Validation (``INVALID_PAYMENT``, R-PAY-2): ``amount > 0``; a REAL calendar date
(port improvement over the original prefix regex, like memo Q5); ``0 <= rate < 100``.

R-DATA-6: every mutating op runs in one ``transaction.atomic()`` and calls
``touch(profile)`` (imported from ``memos``) EXACTLY ONCE inside it, bumping
``FeesSettings.data_version``. Reads (``get_payment``, ``list_payments_for_memo``,
``payees_for_matters``, ``payment_prefill``) never bump it.

Everything is scoped to the profile: payments and allocations carry ``profile``
and memos must be in the profile, so a payment / allocation / memo from another
profile is not found. No module-level mutable state; ``diary`` is never imported.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from fees.errors import FeesError
from fees.models import Allocation, Memo, Payment
from fees.services.memos import touch
from fees.services.money import round2

__all__ = [
    "compute_auto_tds",
    "gross",
    "resolve_tds_amount",
    "validate_payment",
    "recompute_paid",
    "add_payment_to_memo",
    "add_payment",
    "add_unaccounted_payment",
    "assign_payment_to_memo",
    "get_payment",
    "update_payment",
    "delete_payment",
    "list_payments_for_memo",
    "payees_for_matters",
    "payment_prefill",
]

#: Sentinel for "the caller did not pass an ``allocations`` key" in ``update_payment``
#: (an explicit ``None`` or ``[]`` is NOT this; it is a real value, Q3).
_OMITTED = object()

_ZERO = Decimal("0.00")


# ---------------------------------------------------------------------------
# Auto-TDS gross-up and gross (R-PAY-1). Distinct from memo net-of-tds.
# ---------------------------------------------------------------------------

def compute_auto_tds(amount, rate) -> Decimal:
    """Grosses a NET ``amount`` UP by ``rate`` percent: the payment auto-TDS (R-PAY-1).

    ``0`` unless ``0 < rate < 100``; otherwise
    ``round2(amount * 100 / (100 - rate) - amount)``. e.g. net 90 @ 10% -> 10;
    net 9000 @ 10% -> 1000. This is the payment gross-up and is DIFFERENT from
    ``memo_fees.net_of_tds`` (the memo's informational net); the two are kept
    separate on purpose.
    """
    amount_dec = round2(amount)
    rate_dec = Decimal(str(rate))
    if not (rate_dec > 0):
        return _ZERO
    if rate_dec >= 100:
        return _ZERO
    grossed = amount_dec * Decimal(100) / (Decimal(100) - rate_dec)
    return round2(grossed - amount_dec)


def gross(amount, tds) -> Decimal:
    """Gross payment = ``round2(net amount + TDS withheld)``."""
    return round2(Decimal(str(amount)) + Decimal(str(tds)))


def resolve_tds_amount(amount, tds_rate, auto_tds, tds_amount) -> Decimal:
    """The TDS to store for a payment (R-PAY-1).

    When ``auto_tds`` is on (the default), the net ``amount`` is grossed up at
    ``tds_rate`` via ``compute_auto_tds``; otherwise the entered ``tds_amount``
    is taken as sent (``round2``-ed, ``0`` when missing).
    """
    if auto_tds:
        return compute_auto_tds(amount, tds_rate or 0)
    return round2(tds_amount or 0)


# ---------------------------------------------------------------------------
# Input reading and validation (R-PAY-2, brief 15 Q5-style real date)
# ---------------------------------------------------------------------------

def _get(data, name, default=None):
    """Reads ``name`` from a dict ``data``, returning ``default`` when absent."""
    return data.get(name, default)


def _is_real_date(value) -> bool:
    """Whether ``value`` is a real calendar date (R-PAY-2 port improvement).

    Accepts a ``date`` / ``datetime`` directly; otherwise the first 10 characters
    must parse as an ISO ``YYYY-MM-DD`` date, so impossible dates like
    ``2026-13-40`` are rejected (not just the ``YYYY-MM-DD`` prefix the original
    regex accepted).
    """
    if isinstance(value, (datetime.date, datetime.datetime)):
        return True
    if not value:
        return False
    try:
        datetime.date.fromisoformat(str(value)[:10])
        return True
    except (ValueError, TypeError):
        return False


#: The most memos one payment may be split over (200, like the rest of the system). Every screen reads this one value.
MAX_ALLOCATIONS = 200


def validate_payment(data) -> None:
    """Validates a payment input per R-PAY-2, raising ``INVALID_PAYMENT`` on failure.

    ``amount`` must be strictly greater than 0; ``date_of_payment`` must be a REAL
    calendar date; ``tds_rate`` (when present) must be ``0 <= rate < 100``.
    """
    amount = _get(data, "amount")
    try:
        amount_dec = Decimal(str(amount))
    except (ValueError, TypeError, ArithmeticError):
        amount_dec = None
    if amount_dec is None or not (amount_dec > 0):
        raise FeesError("INVALID_PAYMENT", "Payment amount must be greater than 0")

    if not _is_real_date(_get(data, "date_of_payment")):
        raise FeesError("INVALID_PAYMENT", "A valid date of payment is required")

    rate = _get(data, "tds_rate")
    if rate is not None:
        rate_dec = Decimal(str(rate))
        if rate_dec < 0 or rate_dec >= 100:
            raise FeesError("INVALID_PAYMENT", "TDS rate must be between 0 and 100")

    allocations = _get(data, "allocations")
    if allocations and len(allocations) > MAX_ALLOCATIONS:
        raise FeesError(
            "INVALID_PAYMENT",
            f"A payment can be split over at most {MAX_ALLOCATIONS} memos; this one has {len(allocations)}.",
        )


# ---------------------------------------------------------------------------
# recompute_paid: the SOLE writer of the stored memo paid columns (R-DATA-4)
# ---------------------------------------------------------------------------

def recompute_paid(memo_ids) -> None:
    """Rewrites the stored ``amount_paid`` / ``amount_received`` / ``amount_tds`` (R-DATA-4).

    This is the ONLY place in the app that writes those three columns. For each
    affected memo it sums the memo's ``Allocation`` rows and writes:

    * ``amount_paid``     (GROSS) = ``round2(sum(amount + tds_amount))``;
    * ``amount_received`` (NET)   = ``round2(sum(amount))``;
    * ``amount_tds``              = ``round2(sum(tds_amount))``.

    A memo with no remaining allocations is reset to ``0 / 0 / 0``. The write is a
    direct ``UPDATE`` (it never touches ``total_fees`` or any other column). Call
    this inside the caller's transaction for every memo whose allocations changed
    (the memos newly allocated AND any memo that lost an allocation).
    """
    ids = {mid for mid in memo_ids if mid is not None}
    for memo_id in ids:
        agg = Allocation.objects.filter(memo_id=memo_id).aggregate(
            net=Sum("amount"), tds=Sum("tds_amount")
        )
        net = round2(agg["net"] or 0)
        tds = round2(agg["tds"] or 0)
        paid = round2(net + tds)
        Memo.objects.filter(pk=memo_id).update(
            amount_paid=paid, amount_received=net, amount_tds=tds
        )


# ---------------------------------------------------------------------------
# Allocation writing (internal). Validates memos, round2s, recomputes.
# ---------------------------------------------------------------------------

def _memo_id_of(row):
    """Reads the memo id from an allocation-row dict (``memo_id`` or ``memo``)."""
    if "memo_id" in row and row["memo_id"] is not None:
        value = row["memo_id"]
    else:
        value = row.get("memo")
    if isinstance(value, Memo):
        return value.pk
    return value


def _write_allocations(profile, payment, rows) -> None:
    """Replaces ``payment``'s allocations with ``rows`` and recomputes the touched memos.

    Deletes the payment's existing ``Allocation`` rows, inserts the new ones
    (each memo validated to exist in ``profile`` -> ``MEMO_NOT_FOUND``; amounts
    ``round2``-ed; the per-row TDS taken AS SENT; ``profile`` copied onto the
    allocation), then calls ``recompute_paid`` over the UNION of the memos that
    now have an allocation and the memos that previously had one, so a memo that
    just LOST its allocation is reset too. Must run inside the caller's
    ``transaction.atomic()``.
    """
    previous_memo_ids = set(
        Allocation.objects.filter(payment=payment).values_list("memo_id", flat=True)
    )
    Allocation.objects.filter(payment=payment).delete()

    new_memo_ids = set()
    new_rows = []
    for row in rows:
        memo_id = _memo_id_of(row)
        memo = Memo.objects.filter(profile=profile, pk=memo_id).first()
        if memo is None:
            raise FeesError("MEMO_NOT_FOUND", f"Memo {memo_id} not found")
        new_rows.append(
            Allocation(
                payment=payment,
                memo=memo,
                profile=profile,
                amount=round2(row.get("amount") or 0),
                tds_amount=round2(row.get("tds_amount") or 0),
            )
        )
        new_memo_ids.add(memo.pk)

    if new_rows:
        Allocation.objects.bulk_create(new_rows)

    recompute_paid(previous_memo_ids | new_memo_ids)


def _resolve_allocations(data, tds_amount, single_memo_id):
    """Derives the allocation rows from a payment input (ports ``resolveAllocations``).

    An explicit non-empty ``allocations`` list is used as-is (amounts ``round2``-ed,
    per-row TDS as sent, ``0`` when missing). Otherwise, when ``single_memo_id`` is
    given the whole payment is one allocation ``{memo, amount, tds}``; with no memo
    the list is empty (unaccounted).
    """
    allocations = _get(data, "allocations")
    if allocations:
        return [
            {
                "memo_id": _memo_id_of(row),
                "amount": round2(row.get("amount") or 0),
                "tds_amount": round2(row.get("tds_amount") or 0),
            }
            for row in allocations
        ]
    if single_memo_id is not None:
        return [
            {
                "memo_id": single_memo_id,
                "amount": round2(_get(data, "amount") or 0),
                "tds_amount": round2(tds_amount),
            }
        ]
    return []


# ---------------------------------------------------------------------------
# Payment row insert / field copy
# ---------------------------------------------------------------------------

def _bank_account_id_of(data):
    """Reads the bank-account id from ``bank_account_id`` or ``bank_account``."""
    value = _get(data, "bank_account_id")
    if value is not None:
        return value
    return _get(data, "bank_account")


def _insert_payment(profile, data, tds_amount) -> Payment:
    """Inserts and returns a ``Payment`` from the input (``tds_amount`` already resolved)."""
    mode = (_get(data, "payment_mode") or "").strip()
    payment = Payment(
        profile=profile,
        amount=round2(_get(data, "amount") or 0),
        tds_rate=Decimal(str(_get(data, "tds_rate") or 0)),
        auto_tds=bool(_get(data, "auto_tds", True)),
        tds_amount=round2(tds_amount),
        date_of_payment=_get(data, "date_of_payment"),
        payee=(_get(data, "payee") or ""),
        bank_account_id=_bank_account_id_of(data),
        payment_mode=mode,
        payment_details=(_get(data, "payment_details") or ""),
    )
    payment.save()
    return payment


def _apply_payment_fields(payment, data, tds_amount) -> None:
    """Copies the editable fields from ``data`` onto an existing ``payment`` (update)."""
    mode = (_get(data, "payment_mode") or "").strip()
    payment.amount = round2(_get(data, "amount") or 0)
    payment.tds_rate = Decimal(str(_get(data, "tds_rate") or 0))
    payment.auto_tds = bool(_get(data, "auto_tds", True))
    payment.tds_amount = round2(tds_amount)
    payment.date_of_payment = _get(data, "date_of_payment")
    payment.payee = _get(data, "payee") or ""
    payment.bank_account_id = _bank_account_id_of(data)
    payment.payment_mode = mode
    payment.payment_details = _get(data, "payment_details") or ""


# ---------------------------------------------------------------------------
# Create operations (R-PAY-3)
# ---------------------------------------------------------------------------

def add_payment_to_memo(profile, memo_id, data) -> dict:
    """Adds a payment allocated wholly to one memo (the memo Payment modal, R-PAY-3).

    The memo must exist in the profile (``MEMO_NOT_FOUND``). Validates the input.
    The allocations are the explicit list if the caller sent a non-empty one,
    else a single ``{memo, amount, tds}``. One transaction; ``data_version``
    bumped once.
    """
    memo = Memo.objects.filter(profile=profile, pk=memo_id).first()
    if memo is None:
        raise FeesError("MEMO_NOT_FOUND", f"Memo {memo_id} not found")
    validate_payment(data)
    tds_amount = resolve_tds_amount(
        _get(data, "amount"),
        _get(data, "tds_rate"),
        bool(_get(data, "auto_tds", True)),
        _get(data, "tds_amount"),
    )
    with transaction.atomic():
        payment = _insert_payment(profile, data, tds_amount)
        _write_allocations(
            profile, payment, _resolve_allocations(data, tds_amount, memo.pk)
        )
        touch(profile)
    return get_payment(profile, payment.pk)


def add_payment(profile, data) -> dict:
    """Adds a payment with explicit allocations across 0..n memos (Feebook, R-PAY-3).

    An empty / missing ``allocations`` list means an unaccounted payment. One
    transaction; ``data_version`` bumped once.
    """
    validate_payment(data)
    tds_amount = resolve_tds_amount(
        _get(data, "amount"),
        _get(data, "tds_rate"),
        bool(_get(data, "auto_tds", True)),
        _get(data, "tds_amount"),
    )
    with transaction.atomic():
        payment = _insert_payment(profile, data, tds_amount)
        _write_allocations(
            profile, payment, _resolve_allocations(data, tds_amount, None)
        )
        touch(profile)
    return get_payment(profile, payment.pk)


def add_unaccounted_payment(profile, data) -> dict:
    """Creates an unaccounted payment (always zero allocations, R-PAY-3).

    One transaction; ``data_version`` bumped once.
    """
    validate_payment(data)
    tds_amount = resolve_tds_amount(
        _get(data, "amount"),
        _get(data, "tds_rate"),
        bool(_get(data, "auto_tds", True)),
        _get(data, "tds_amount"),
    )
    with transaction.atomic():
        payment = _insert_payment(profile, data, tds_amount)
        _write_allocations(profile, payment, [])
        touch(profile)
    return get_payment(profile, payment.pk)


def assign_payment_to_memo(profile, payment_id, memo_id) -> dict:
    """Attaches a payment to a memo by REPLACING all allocations with one (R-PAY-3).

    The payment and memo must both exist in the profile
    (``INVALID_PAYMENT`` / ``MEMO_NOT_FOUND``). The single new allocation is
    ``{memo, payment.amount, payment.tds_amount}``. Used to attach an unaccounted
    payment (including by typing a memo number in the Feebook via
    ``memo_numbers.find_memo_id_by_number``). One transaction; ``data_version``
    bumped once.
    """
    payment = Payment.objects.filter(profile=profile, pk=payment_id).first()
    if payment is None:
        raise FeesError("INVALID_PAYMENT", f"Payment {payment_id} not found")
    memo = Memo.objects.filter(profile=profile, pk=memo_id).first()
    if memo is None:
        raise FeesError("MEMO_NOT_FOUND", f"Memo {memo_id} not found")
    with transaction.atomic():
        _write_allocations(
            profile,
            payment,
            [
                {
                    "memo_id": memo.pk,
                    "amount": payment.amount,
                    "tds_amount": payment.tds_amount,
                }
            ],
        )
        touch(profile)
    return get_payment(profile, payment.pk)


# ---------------------------------------------------------------------------
# Read (get)
# ---------------------------------------------------------------------------

def _allocation_dtos(payment):
    """The allocation DTOs for a payment, ordered by id, each with its gross share."""
    rows = (
        Allocation.objects.filter(payment=payment)
        .select_related("memo")
        .order_by("id")
    )
    out = []
    for alloc in rows:
        out.append(
            {
                "id": alloc.pk,
                "payment_id": alloc.payment_id,
                "memo_id": alloc.memo_id,
                "memo_number": alloc.memo.memo_number,
                "amount": round2(alloc.amount),
                "tds_amount": round2(alloc.tds_amount),
                "gross_amount": gross(alloc.amount, alloc.tds_amount),
            }
        )
    return out


def _payment_dto(payment) -> dict:
    """Builds the payment detail dict with its allocations and gross amount."""
    allocations = _allocation_dtos(payment)
    single_memo_id = allocations[0]["memo_id"] if len(allocations) == 1 else None
    return {
        "id": payment.pk,
        "memo_id": single_memo_id,
        "amount": round2(payment.amount),
        "tds_rate": payment.tds_rate,
        "auto_tds": payment.auto_tds,
        "tds_amount": round2(payment.tds_amount),
        "gross_amount": gross(payment.amount, payment.tds_amount),
        "date_of_payment": payment.date_of_payment,
        "payee": payment.payee,
        "bank_account_id": payment.bank_account_id,
        "payment_mode": payment.payment_mode,
        "payment_details": payment.payment_details,
        "allocations": allocations,
    }


def get_payment(profile, payment_id) -> dict:
    """Returns a payment detail dict scoped to the profile (``INVALID_PAYMENT`` if missing).

    A pure read: it does NOT bump ``data_version``.
    """
    payment = Payment.objects.filter(profile=profile, pk=payment_id).first()
    if payment is None:
        raise FeesError("INVALID_PAYMENT", f"Payment {payment_id} not found")
    return _payment_dto(payment)


# ---------------------------------------------------------------------------
# Update (R-PAY-4, incl. the Q3 fix)
# ---------------------------------------------------------------------------

def update_payment(profile, payment_id, data) -> dict:
    """Updates a payment and re-derives its allocations (R-PAY-4, Q3 fix).

    The payment must exist in the profile (``INVALID_PAYMENT``). Validates the
    input and updates the editable fields. Allocation re-derivation (precise):

    * ``allocations`` provided (even explicit ``[]``) -> replace with them (an
      explicit empty list makes the payment unaccounted);
    * ``allocations`` OMITTED and exactly 1 existing allocation -> rebuild that
      one allocation as ``{same memo, new amount, new tds}``;
    * ``allocations`` OMITTED and 0 or 2+ existing -> Q3 FIX: KEEP them unchanged.

    "Omitted" is tested with the ``_OMITTED`` sentinel, so an explicit ``None`` or
    ``[]`` is NOT treated as omitted. One transaction; ``data_version`` bumped once.
    """
    payment = Payment.objects.filter(profile=profile, pk=payment_id).first()
    if payment is None:
        raise FeesError("INVALID_PAYMENT", f"Payment {payment_id} not found")
    validate_payment(data)
    tds_amount = resolve_tds_amount(
        _get(data, "amount"),
        _get(data, "tds_rate"),
        bool(_get(data, "auto_tds", True)),
        _get(data, "tds_amount"),
    )

    allocations_in = data.get("allocations", _OMITTED)

    with transaction.atomic():
        _apply_payment_fields(payment, data, tds_amount)
        payment.save()

        if allocations_in is not _OMITTED:
            # Explicit value (even []) replaces the old split.
            next_rows = _resolve_allocations(
                {"allocations": allocations_in, "amount": _get(data, "amount")},
                tds_amount,
                None,
            )
            _write_allocations(profile, payment, next_rows)
        else:
            existing = list(
                Allocation.objects.filter(payment=payment)
                .order_by("id")
                .values_list("memo_id", flat=True)
            )
            if len(existing) == 1:
                # Rebuild the single allocation with the new amount / tds.
                next_rows = _resolve_allocations(data, tds_amount, existing[0])
                _write_allocations(profile, payment, next_rows)
            else:
                # Q3 FIX: 0 or 2+ existing and omitted -> keep them unchanged.
                # They still need recompute in case the TDS-bearing amount did
                # not change but we keep allocations as-is (no write needed).
                pass

        touch(profile)

    return get_payment(profile, payment.pk)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def delete_payment(profile, payment_id) -> None:
    """Deletes a payment and its allocations, recomputing the memos it touched (R-PAY-3).

    The payment must exist in the profile (``INVALID_PAYMENT``). In one
    transaction: record the memos that had an allocation, delete the allocations,
    delete the payment, recompute those memos (they go back toward 0 if they lost
    their last allocation), then bump ``data_version`` once.
    """
    payment = Payment.objects.filter(profile=profile, pk=payment_id).first()
    if payment is None:
        raise FeesError("INVALID_PAYMENT", f"Payment {payment_id} not found")
    with transaction.atomic():
        memo_ids = set(
            Allocation.objects.filter(payment=payment).values_list(
                "memo_id", flat=True
            )
        )
        Allocation.objects.filter(payment=payment).delete()
        payment.delete()
        recompute_paid(memo_ids)
        touch(profile)


# ---------------------------------------------------------------------------
# Reads: per-memo payments, payee suggestions
# ---------------------------------------------------------------------------

def list_payments_for_memo(profile, memo_id) -> list:
    """Payments allocated to ``memo_id`` with each one's per-memo SHARE surfaced (R-PAY-6).

    Ordered by date of payment then id. The returned ``amount`` / ``tds_amount`` /
    ``gross_amount`` and ``memo_id`` are narrowed to THIS memo's allocation, so the
    memo page shows the portion applied here, not a split payment's whole figure.
    A pure read: it does NOT bump ``data_version``.
    """
    payments = (
        Payment.objects.filter(profile=profile, allocations__memo_id=memo_id)
        .distinct()
        .order_by("date_of_payment", "id")
    )
    out = []
    for payment in payments:
        dto = _payment_dto(payment)
        share = next(
            (a for a in dto["allocations"] if a["memo_id"] == memo_id), None
        )
        if share is not None:
            dto = {
                **dto,
                "memo_id": memo_id,
                "amount": share["amount"],
                "tds_amount": share["tds_amount"],
                "gross_amount": share["gross_amount"],
            }
        out.append(dto)
    return out


def payees_for_matters(profile, matter_ids) -> list:
    """Distinct non-blank payees on payments allocated to memos of ``matter_ids`` (R-PAY-6).

    Grouped case-insensitively on the trimmed payee, ordered by the last payment
    date descending then the count descending. Returns dicts
    ``{payee, count, last_date}`` where ``payee`` is the spelling on the latest
    payment. A pure read: it does NOT bump ``data_version``.
    """
    ids = [mid for mid in (matter_ids or []) if mid is not None]
    if not ids:
        return []

    rows = (
        Payment.objects.filter(
            profile=profile, allocations__memo__matter_id__in=ids
        )
        .exclude(payee="")
        .distinct()
        .values("id", "payee", "date_of_payment")
    )

    groups = {}
    for row in rows:
        payee = (row["payee"] or "").strip()
        if not payee:
            continue
        key = payee.lower()
        pay_date = row["date_of_payment"]
        bucket = groups.get(key)
        if bucket is None:
            groups[key] = {
                "payee": payee,
                "count": 1,
                "last_date": pay_date,
            }
        else:
            bucket["count"] += 1
            if pay_date is not None and (
                bucket["last_date"] is None or pay_date >= bucket["last_date"]
            ):
                bucket["last_date"] = pay_date
                bucket["payee"] = payee

    def _sort_key(item):
        last = item["last_date"]
        # Sort most-recent first, then by count; a missing date sorts last.
        return (last is not None, last, item["count"])

    ordered = sorted(groups.values(), key=_sort_key, reverse=True)
    return ordered


# ---------------------------------------------------------------------------
# Prefill (R-PAY-7, pure function; UI-facing but ported server-side)
# ---------------------------------------------------------------------------

def payment_prefill(mode, due, rate) -> dict:
    """What to prefill into "Amount Received" for a memo with ``due`` outstanding (R-PAY-7).

    A pure port of ``paymentPrefill.ts`` with ``d = max(0, round2(due))``:

    * ``"full"``      -> ``{amount: d, auto_tds: False, tds_amount: 0}`` (the memo
      is paid in full by exactly this amount; no TDS added on top);
    * ``"netOfTds"``  -> ``{amount: round2(d - less), auto_tds: True, tds_amount: 0}``
      where ``less = round2(d * rate / 100)`` when ``0 < rate < 100`` else ``0``
      (auto-TDS then adds the TDS back so amount + TDS equals the amount due);
    * anything else (``"zero"``) -> ``{amount: 0, auto_tds: True, tds_amount: 0}``.

    ``due`` is supplied by the caller; when editing a payment the caller excludes
    this payment's own gross for that memo before calling. This is a pure read and
    takes no ``profile`` and bumps nothing.
    """
    d = round2(due)
    if d < 0:
        d = _ZERO
    if mode == "full":
        return {"amount": d, "auto_tds": False, "tds_amount": _ZERO}
    if mode == "netOfTds":
        rate_dec = Decimal(str(rate))
        if rate_dec > 0 and rate_dec < 100:
            less = round2(d * rate_dec / Decimal(100))
        else:
            less = _ZERO
        return {"amount": round2(d - less), "auto_tds": True, "tds_amount": _ZERO}
    return {"amount": _ZERO, "auto_tds": True, "tds_amount": _ZERO}
