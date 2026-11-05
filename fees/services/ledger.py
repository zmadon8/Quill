"""Ledger and Statement read services for the Fee Register (T3.4, R-RD-1, brief 6.5).

Ports ``ledgerService.ts`` (``paymentParticulars`` and ``buildLedger``) to the
Django ORM and adds ``build_statement``, the data builder that both the
on-screen Statement and the later Excel export (Phase 5) consume. Every function
is profile-scoped and is a pure READ: none of them bump ``data_version``.

The Ledger is a running-balance view: every non-draft memo is a DEBIT row (its
effective total fees) and every payment ALLOCATION is a CREDIT row (the net
received plus the TDS withheld, in separate columns). Rows are in date order; on
the same day memos come before payments so the balance never dips below zero
because of ordering alone. The running balance after each row is
``balance = round2(balance + (memo_amount or 0) - (payment_amount or 0) - (tds or 0))``.

Naming: the desktop / TypeScript source calls the grouping "partner"
(``partnerId``); the Django model calls it GROUP (the ``Group`` model, the
``group`` field and ``group_id`` on ``Memo``). So the scope's ``partner_id`` maps
to ``group_id`` (a ``partner_id`` / ``group_id`` of ``"none"`` is a no-op, like
the sibling services ``memo_lists`` / ``feebook`` / ``outstanding``).

Money comes through ``money.round2`` (two-decimal ``Decimal``) and every memo
total comes from ``memo_fees.effective_total_fees`` (the ONE fee rule, R-MEMO-1);
this module never multiplies a fee count by its per-unit rate, so the single-fee
guard in ``test_memo_fees`` holds.

The ``scope`` dict (shared by ``build_ledger`` and ``build_statement``) accepts
any of: ``matter_id``; ``matter_ids`` (a list); ``firm_id``; ``partner_id``
(alias ``group_id``, ``"none"`` a no-op). The filters apply to BOTH the memo
query and the payment-allocation query (the allocation query joins through its
memo and filters the memo). Drafts (``is_draft``) are always excluded.

Query-count discipline (asserted in the tests with ``assertNumQueries``):

* ``build_ledger`` is TWO queries: one for the non-draft memo rows and one for
  the payment allocations (both with ``select_related`` so the matter / payment
  names cost no per-row query). The event build, sort and running balance are
  pure in-memory.
* ``build_statement`` is at most TWO queries: the memo rows (one) plus, when the
  scope names a single matter or a firm, one more to resolve the Statement title
  name. With no scope it is a single query. The rows and totals are pure
  in-memory.
"""
from __future__ import annotations

from decimal import Decimal

from fees.models import Allocation, Memo
from fees.services import memo_fees
from fees.services.money import round2

__all__ = [
    "payment_particulars",
    "build_ledger",
    "build_statement",
]

#: Shown in place of a draft memo's (missing) number.
_DRAFT_LABEL = "(draft)"

_ZERO = Decimal("0.00")


def payment_particulars(payee, mode, memo_number) -> str:
    """Builds a payment's ledger particulars string (ports ``paymentParticulars``).

    ``"Payment by {payee} by {mode} against Memo {memo_number}"``, omitting the
    ``by {payee}`` and / or ``by {mode}`` parts when ``payee`` / ``mode`` is
    ``None`` or blank / whitespace, and using ``"(draft)"`` when ``memo_number``
    is ``None``. The surviving payee / mode is trimmed. Examples:

    * ``payment_particulars(None, None, "5 of 2026-27")`` ->
      ``"Payment against Memo 5 of 2026-27"``
    * ``payment_particulars("X", None, "1")`` -> ``"Payment by X against Memo 1"``
    """
    parts = ["Payment"]
    if payee and payee.strip():
        parts.append(f"by {payee.strip()}")
    if mode and mode.strip():
        parts.append(f"by {mode.strip()}")
    parts.append(f"against Memo {memo_number if memo_number is not None else _DRAFT_LABEL}")
    return " ".join(parts)


def _apply_scope(qs, scope, prefix=""):
    """Applies the shared scope filters to ``qs`` (the memo or, via ``prefix``, its join).

    ``prefix`` is ``""`` when filtering a ``Memo`` queryset directly and
    ``"memo__"`` when filtering an ``Allocation`` queryset through its memo, so
    exactly the same scope narrows both sides. The filters: ``matter_id``;
    ``matter_ids`` (a list, applied together with any ``firm_id``); ``firm_id``;
    ``partner_id`` (alias ``group_id``, ``"none"`` a no-op). An unknown / missing
    key is ignored.
    """
    matter_id = scope.get("matter_id")
    if matter_id is not None:
        qs = qs.filter(**{f"{prefix}matter_id": matter_id})

    matter_ids = scope.get("matter_ids")
    if matter_ids:
        qs = qs.filter(**{f"{prefix}matter_id__in": list(matter_ids)})

    firm_id = scope.get("firm_id")
    if firm_id is not None:
        qs = qs.filter(**{f"{prefix}firm_id": firm_id})

    # The original UI calls this "partner"; the model field is group. A value of
    # "none" is a no-op (mirrors the sibling services).
    group_id = scope.get("partner_id", scope.get("group_id"))
    if group_id == "none":
        pass
    elif group_id is not None:
        qs = qs.filter(**{f"{prefix}group_id": group_id})

    return qs


def build_ledger(profile, scope=None) -> list:
    """Builds the running-balance ledger for ``scope`` (R-RD-1, brief 6.5).

    Returns a list of ledger row dicts, each carrying ``date``, ``particulars``,
    ``matter_name``, ``memo_amount`` (debit; ``None`` on a payment row),
    ``payment_amount`` (credit net; ``None`` on a memo row), ``tds`` (credit TDS;
    ``None`` on a memo row) and ``balance`` (the running balance payable after the
    row). Every non-draft memo is a debit row (``memo_amount`` = effective total
    fees; particulars ``"Memo {number}"`` plus ``" (written off)"`` when written
    off). Every payment allocation is a credit row (``payment_amount`` =
    ``round2(allocation.amount)``, ``tds`` = ``round2(allocation.tds_amount)``,
    particulars via ``payment_particulars``).

    Rows are sorted by ``date`` ascending; on the SAME day memos come before
    payments; within a kind the tie-break is the memo id / allocation id
    ascending. The running balance is
    ``round2(balance + (memo_amount or 0) - (payment_amount or 0) - (tds or 0))``.

    ``scope`` is an optional dict with any of ``matter_id``, ``matter_ids`` (a
    list), ``firm_id``, ``partner_id`` (alias ``group_id``, ``"none"`` a no-op);
    the filters apply to BOTH the memos and the payment allocations. Drafts are
    always excluded. Two queries; a pure read (no ``data_version`` bump).
    """
    scope = scope or {}

    memo_qs = _apply_scope(
        Memo.objects.filter(profile=profile, is_draft=False).select_related("matter"),
        scope,
    )

    alloc_qs = _apply_scope(
        Allocation.objects.filter(profile=profile, memo__is_draft=False).select_related(
            "payment", "memo", "memo__matter"
        ),
        scope,
        prefix="memo__",
    )

    # kind 0 = memo, 1 = payment, so memos come first on the same day.
    events = []
    for memo in memo_qs:
        suffix = " (written off)" if memo.written_off else ""
        number = memo.memo_number if memo.memo_number is not None else _DRAFT_LABEL
        events.append(
            {
                "date": memo.date,
                "kind": 0,
                "order": memo.pk,
                "row": {
                    "date": memo.date,
                    "particulars": f"Memo {number}{suffix}",
                    "matter_name": memo.matter.name,
                    "memo_amount": memo_fees.effective_total_fees(memo),
                    "payment_amount": None,
                    "tds": None,
                },
            }
        )

    for alloc in alloc_qs:
        payment = alloc.payment
        memo = alloc.memo
        events.append(
            {
                "date": payment.date_of_payment,
                "kind": 1,
                "order": alloc.pk,
                "row": {
                    "date": payment.date_of_payment,
                    "particulars": payment_particulars(
                        payment.payee, payment.payment_mode, memo.memo_number
                    ),
                    "matter_name": memo.matter.name,
                    "memo_amount": None,
                    "payment_amount": round2(alloc.amount),
                    "tds": round2(alloc.tds_amount),
                },
            }
        )

    events.sort(key=lambda e: (e["date"], e["kind"], e["order"]))

    balance = _ZERO
    rows = []
    for event in events:
        row = event["row"]
        balance = round2(
            balance
            + (row["memo_amount"] or _ZERO)
            - (row["payment_amount"] or _ZERO)
            - (row["tds"] or _ZERO)
        )
        rows.append({**row, "balance": balance})
    return rows


def _scope_title(profile, scope):
    """The Statement title / subtitle for ``scope`` (brief 6.5).

    Returns ``(title, subtitle)``. When the scope names a single matter the title
    is ``"Statement - {matter name}"`` with the firm as the subtitle; otherwise,
    when it names a firm, the title is ``"Statement - {firm name}"`` with an empty
    subtitle. With neither (or several matters) the title is the plain
    ``"Statement"``. A hyphen is used in the title, never an em dash (project
    rule). One extra query only when a name must be resolved, so callers that
    already filter by id stay cheap; resolving the name is skipped when the scope
    has no single matter / firm.
    """
    from fees.models import Firm, Matter

    matter_id = scope.get("matter_id")
    matter_ids = scope.get("matter_ids")
    if matter_id is not None and not matter_ids:
        matter = (
            Matter.objects.filter(profile=profile, pk=matter_id)
            .select_related("firm")
            .first()
        )
        if matter is not None:
            return f"Statement - {matter.name}", matter.firm.name
        return "Statement", ""

    firm_id = scope.get("firm_id")
    if firm_id is not None:
        firm = Firm.objects.filter(profile=profile, pk=firm_id).first()
        if firm is not None:
            return f"Statement - {firm.name}", ""
        return "Statement", ""

    return "Statement", ""


def build_statement(profile, scope=None) -> dict:
    """Builds the Statement data for ``scope`` (brief 6.5 / 7.3).

    Returns a plain data dict the on-screen Statement and the later Excel export
    both format::

        {
          "title": "Statement - {matter}" | "Statement - {firm}" | "Statement",
          "subtitle": "{firm name}" | "",
          "rows": [ {memo_number, date, matter_name, total, paid,
                     outstanding, status}, ... ],
          "totals": {total_billed, total_paid, total_outstanding, count},
        }

    One row per non-draft memo in scope, ordered by ``date`` then ``seq`` then id:

    * ``total``       = effective total fees (``memo_fees.effective_total_fees``);
    * ``paid``        = the stored GROSS ``amount_paid``;
    * ``outstanding`` = ``max(0, round2(total - paid))`` (floored at 0);
    * ``status``      = ``memo_fees.status_and_due`` status, but ``"Written Off"``
      overrides when the memo is written off.

    The totals summary sums ``total`` / ``paid`` / ``outstanding`` (each
    ``round2``-ed) and counts the rows. ``scope`` mirrors ``build_ledger``'s
    scope. Drafts are always excluded. A pure read (no ``data_version`` bump).

    Two queries: the title / name resolution (one, only when the scope names a
    single matter or a firm) and the non-draft memo rows (``select_related`` on
    the matter so its name costs no per-row query). The rows and totals are pure
    in-memory.
    """
    scope = scope or {}

    title, subtitle = _scope_title(profile, scope)

    memo_qs = _apply_scope(
        Memo.objects.filter(profile=profile, is_draft=False)
        .select_related("matter")
        .order_by("date", "seq", "id"),
        scope,
    )

    rows = []
    total_billed = _ZERO
    total_paid = _ZERO
    total_outstanding = _ZERO
    for memo in memo_qs:
        total = memo_fees.effective_total_fees(memo)
        paid = round2(memo.amount_paid)
        outstanding = round2(total - paid)
        if outstanding < 0:
            outstanding = _ZERO
        status = memo_fees.status_and_due(total, paid).status
        if memo.written_off:
            status = "Written Off"

        rows.append(
            {
                "memo_number": memo.memo_number,
                "date": memo.date,
                "matter_name": memo.matter.name,
                "total": total,
                "paid": paid,
                "outstanding": outstanding,
                "status": status,
            }
        )
        total_billed = round2(total_billed + total)
        total_paid = round2(total_paid + paid)
        total_outstanding = round2(total_outstanding + outstanding)

    return {
        "title": title,
        "subtitle": subtitle,
        "rows": rows,
        "totals": {
            "total_billed": total_billed,
            "total_paid": total_paid,
            "total_outstanding": total_outstanding,
            "count": len(rows),
        },
    }
