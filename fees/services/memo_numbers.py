"""Memo numbering primitives for the Fee Register (R-NUM-1 to R-NUM-5, brief 5.6).

This is the first Phase 2 service that touches the database. It owns the
``NumberSequence`` row (one per ``(profile, financial_year)``) and the custom
number validation rule. The create / draft / finalise flows (T2.5
``memos.py``) call these primitives; they are not implemented here.

Public API:

* ``next_number(profile, date_or_fy)`` - atomically allocate the next auto
  number ``"{FY}/{seq}"`` for a profile and FY, advancing the sequence
  (R-NUM-1). Never decremented, never reused.
* ``preview_next_number(profile, date_or_fy)`` - read-only ``"{FY}/{last_seq+1}"``
  with no write (R-NUM-4). A missing row reads as ``last_seq = 0`` -> ``/1``.
* ``validate_custom_number(profile, raw, exclude_memo_id=None)`` - trim and
  validate a user-typed custom number (R-NUM-3, brief 15 Q8), returning the
  trimmed value or raising ``FeesError("INVALID_MEMO", ...)``.
* ``is_custom_number(memo)`` - the brief-5.6 predicate: not a draft, has a
  number, and ``seq == 0``.
* ``find_memo_id_by_number(profile, raw)`` - case-insensitive exact match on
  trimmed input, non-drafts only (R-NUM-5).

``date_or_fy`` may be a ``date`` / ``datetime`` / ISO ``YYYY-MM-DD`` string (the
FY is derived with ``financial_year.derive_financial_year``) OR an already
derived ``YYYY-YY`` FY label (passed through verbatim). This keeps callers that
already hold the FY from re-deriving it.

Atomic increment and why it is correct on both backends: ``next_number`` wraps a
``transaction.atomic()`` (safe to nest, so a caller already in a transaction
reuses the outer one). Inside it, ``select_for_update().get_or_create`` seeds the
row if missing, then an ``F("last_seq") + 1`` update increments the counter in a
single SQL statement and ``refresh_from_db`` reads back the new value. On
PostgreSQL ``SELECT ... FOR UPDATE`` takes a row lock so two concurrent
allocations on the same ``(profile, FY)`` serialise and never collide. On SQLite
``select_for_update`` is a no-op, but SQLite serialises writers at the database
level, so the get-or-create plus the single-statement ``F()`` increment is still
correct; the ``F()`` expression (not a read-then-write in Python) is what keeps
it race-free there.

Lazy model import (``from fees.models import ...`` inside each function) avoids
any import-time cycle and keeps this module cheap to import. No module-level
mutable state.
"""
from __future__ import annotations

import re

from django.db import transaction
from django.db.models import F

from fees.errors import FeesError
from fees.services.financial_year import derive_financial_year

__all__ = [
    "next_number",
    "preview_next_number",
    "validate_custom_number",
    "is_custom_number",
    "find_memo_id_by_number",
]

#: A value that looks like an auto number ``YYYY-YY/N`` (brief 15 Q8). Rejected as
#: a custom number so a custom value can never shadow a future auto number.
_AUTO_NUMBER_RE = re.compile(r"^\d{4}-\d{2}/\d+$")

#: The maximum length of a custom memo number (R-NUM-3).
_MAX_CUSTOM_LEN = 100


def _resolve_fy(date_or_fy) -> str:
    """Resolves ``date_or_fy`` to a ``YYYY-YY`` label.

    An already derived FY label (matching ``YYYY-YY``) is passed through verbatim;
    anything else is treated as a date / ISO date string and run through
    ``derive_financial_year``.
    """
    text = str(date_or_fy)
    if re.fullmatch(r"\d{4}-\d{2}", text):
        return text
    return derive_financial_year(date_or_fy)


def next_number(profile, date_or_fy) -> str:
    """Atomically allocates the next auto number ``"{FY}/{seq}"`` (R-NUM-1).

    Derives the FY from ``date_or_fy`` (a date / ISO string, or a ready FY
    label), gets or creates the ``NumberSequence`` row for ``(profile, FY)`` under
    a row lock, increments it with a single ``F()`` update and returns the NEW
    sequence value. The sequence is never decremented and numbers are never
    reused, so deletes leave gaps.
    """
    from fees.models import NumberSequence

    fy = _resolve_fy(date_or_fy)
    with transaction.atomic():
        row, _created = (
            NumberSequence.objects.select_for_update().get_or_create(
                profile=profile, financial_year=fy, defaults={"last_seq": 0}
            )
        )
        NumberSequence.objects.filter(pk=row.pk).update(last_seq=F("last_seq") + 1)
        row.refresh_from_db(fields=["last_seq"])
    return f"{fy}/{row.last_seq}"


def preview_next_number(profile, date_or_fy) -> str:
    """Read-only preview of the next auto number ``"{FY}/{last_seq+1}"`` (R-NUM-4).

    Creates and increments nothing. A missing sequence row reads as
    ``last_seq = 0``, so the preview is ``"{FY}/1"``.
    """
    from fees.models import NumberSequence

    fy = _resolve_fy(date_or_fy)
    last_seq = (
        NumberSequence.objects.filter(profile=profile, financial_year=fy)
        .values_list("last_seq", flat=True)
        .first()
    )
    if last_seq is None:
        last_seq = 0
    return f"{fy}/{last_seq + 1}"


def validate_custom_number(profile, raw, exclude_memo_id=None) -> str:
    """Validates a user-typed custom memo number and returns the trimmed value (R-NUM-3).

    Rules (all failures raise ``FeesError("INVALID_MEMO", ...)``):

    * trim; it must be 1 to 100 characters;
    * it must not look like an automatic number ``YYYY-YY/N`` (brief 15 Q8), so a
      custom value can never shadow a future auto number;
    * it must be unique across this profile's memos (exact match), excluding the
      memo being edited (``exclude_memo_id``).

    The database also carries a unique constraint as a backstop; this check
    mirrors the original ``assignCustomMemoNumber`` so the error is a clean
    ``INVALID_MEMO`` rather than an ``IntegrityError``.
    """
    from fees.models import Memo

    num = (raw or "").strip()
    if len(num) < 1:
        raise FeesError("INVALID_MEMO", "A custom memo number cannot be blank")
    if len(num) > _MAX_CUSTOM_LEN:
        raise FeesError(
            "INVALID_MEMO", "Memo number must be at most 100 characters"
        )
    if _AUTO_NUMBER_RE.match(num):
        raise FeesError(
            "INVALID_MEMO",
            "A custom memo number cannot look like an automatic number (YYYY-YY/N).",
        )
    clash = Memo.objects.filter(profile=profile, memo_number=num)
    if exclude_memo_id is not None:
        clash = clash.exclude(pk=exclude_memo_id)
    if clash.exists():
        raise FeesError("INVALID_MEMO", f'Memo number "{num}" is already in use')
    return num


def is_custom_number(memo) -> bool:
    """Whether a memo carries a custom number (brief 5.6): finalised, numbered, ``seq == 0``.

    ``memo`` is any object or dict exposing ``is_draft``, ``memo_number`` and
    ``seq``.
    """
    if isinstance(memo, dict):
        is_draft = memo.get("is_draft")
        memo_number = memo.get("memo_number")
        seq = memo.get("seq")
    else:
        is_draft = memo.is_draft
        memo_number = memo.memo_number
        seq = memo.seq
    return (not is_draft) and memo_number is not None and seq == 0


def find_memo_id_by_number(profile, raw):
    """Resolves a finalised memo number to its id, or ``None`` (R-NUM-5).

    Case-insensitive exact match on the trimmed input, non-drafts only. Scoped to
    the profile. Implemented here (not deferred to T2.5): it is a single read-only
    query over the ``Memo`` model with no model-mutation logic, so it belongs with
    the other numbering primitives that the Feebook payment-reassign flow calls.
    """
    from fees.models import Memo

    num = (raw or "").strip()
    if not num:
        return None
    return (
        Memo.objects.filter(profile=profile, is_draft=False, memo_number__iexact=num)
        .values_list("id", flat=True)
        .first()
    )
