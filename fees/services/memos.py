"""Memo lifecycle services for the Fee Register (R-MEMO-1 to R-MEMO-7, R-DATA-4, R-DATA-6).

Ports ``memoService.ts`` (create / save draft / finalise / update / delete /
write-off / create-based-on / preview number / get) to the Django ORM. This is
the central Phase 2 service: it composes the earlier building blocks and never
re-implements their logic.

Composition (reuse, do NOT duplicate):

* ``memo_fees.resolve_memo_fees`` is the ONE fee rule (R-MEMO-1, D3). Every
  create / finalise / update stores ``total_fees = resolve_memo_fees(...).total_fees``;
  line fees are NEVER computed inline here (the T2.2 grep guard test enforces
  this).
* ``memo_fees.status_and_due`` derives Paid / Unpaid and amount due from the
  stored ``amount_paid`` vs ``total_fees``.
* ``memo_fees.net_of_tds`` and ``memo_fees.compute_is_overdue`` feed ``get_memo``.
* ``memo_numbers.next_number`` / ``preview_next_number`` / ``validate_custom_number``
  own all numbering.
* ``financial_year.derive_financial_year`` / ``current_financial_year`` own FY
  derivation.

R-DATA-6 (``data_version`` bump): every mutating operation runs in one
``transaction.atomic()`` and calls ``touch(profile)`` EXACTLY ONCE inside that
same transaction, bumping ``FeesSettings.data_version`` by one with an
``F("data_version") + 1`` update. ``touch`` get-or-creates the settings row so a
profile that has not visited Settings still has its stamp advanced. Reads
(``get_memo``, ``create_based_on``, ``preview_number``) never bump it.

R-DATA-4: ``total_fees`` is stored from ``resolve_memo_fees`` on every create and
every edit; ``amount_paid`` / ``amount_received`` / ``amount_tds`` default to 0 on
create and are left untouched by memo edits and write-off (payments.py in T2.6
maintains them).

Q5 (brief 15 Q5, R-MEMO-2): a non-draft save / finalise requires a REAL calendar
date (``datetime.date.fromisoformat``), rejecting impossible dates like
``2026-13-40`` with ``INVALID_MEMO``. A draft skips all validation.

The list views (``list_memos`` / ``list_drafts`` / ``list_memos_for_matter``) are
deferred to T3.1 (``memo_lists.py``) and are NOT implemented here; T2.5 is the
lifecycle plus ``get_memo``.

No module-level mutable state. Models and sibling services are imported at module
level; ``diary`` is never imported.
"""
from __future__ import annotations

import datetime

from django.db import transaction
from django.db.models import F

from fees.errors import FeesError
from fees.models import Allocation, FeesSettings, Matter, Memo, Payment, StatsCache
from fees.services import memo_fees, memo_numbers
from fees.services.financial_year import (
    current_financial_year,
    derive_financial_year,
)

__all__ = [
    "touch",
    "validate_memo_input",
    "create_memo",
    "save_draft",
    "finalize_draft",
    "update_memo",
    "set_memo_written_off",
    "delete_memo",
    "move_memo",
    "create_based_on",
    "preview_number",
    "get_memo",
]

#: The snapshot / case fields copied from the memo input onto the memo. These
#: travel with the input (prefilled client-side from the matter), so they are
#: read from ``data`` and NOT re-read from the matter.
_SNAPSHOT_FIELDS = (
    "addressee_line1",
    "addressee_line2",
    "court_name",
    "additional_details_left",
    "additional_details_right",
    "plaintiff_name",
    "plaintiff_type",
    "defendant_name",
    "defendant_type",
    "client",
)

#: The fee-line and detail fields copied from the input (counts, rates, dates
#: text, misc, num_drafts).
_LINE_FIELDS = (
    "num_appearances",
    "dates_of_appearances",
    "fees_per_appearance",
    "num_conferences",
    "dates_of_conferences",
    "fees_per_conference",
    "misc_drafting_description",
    "fees_misc_drafting",
    "num_drafts",
)

#: The optional custom overrides (null means "use the computed value").
_CUSTOM_FIELDS = (
    "custom_fees_appearances",
    "custom_fees_conferences",
    "custom_fees_misc",
    "custom_total_fees",
)

#: Text fields that must never be stored as NULL on the memo (the model declares
#: them ``blank=True, default=""`` and NOT nullable).
_TEXT_FIELDS = frozenset(
    _SNAPSHOT_FIELDS
    + ("dates_of_appearances", "dates_of_conferences", "misc_drafting_description")
) - {"addressee_line1"}

#: Numeric line fields whose default is 0 (never NULL on the memo).
_NUMERIC_DEFAULT_ZERO = frozenset(
    (
        "num_appearances",
        "fees_per_appearance",
        "num_conferences",
        "fees_per_conference",
        "fees_misc_drafting",
        "num_drafts",
    )
)


# ---------------------------------------------------------------------------
# data_version stamp (R-DATA-6)
# ---------------------------------------------------------------------------

def touch(profile):
    """Bumps ``FeesSettings.data_version`` by one for ``profile`` (R-DATA-6).

    Call this ONCE inside every mutating operation's ``transaction.atomic()``.
    The settings row is get-or-created so a profile that has never opened
    Settings still has a stamp to advance; the increment is a single
    ``F("data_version") + 1`` update so it is race-free.

    Bumping ``data_version`` already LOGICALLY invalidates every cached
    ``StatsCache`` row for the profile (a cached row is valid only while its
    ``data_version`` matches). This also DELETES the profile's cache rows so
    stale rows do not accumulate across mutating operations (design lines 67 and
    141; R-NFR-10). Only the ``StatsCache`` MODEL is imported here, not the
    ``stats_cache`` service, so there is no import cycle. Returns nothing.
    """
    settings, _created = FeesSettings.objects.get_or_create(profile=profile)
    FeesSettings.objects.filter(pk=settings.pk).update(
        data_version=F("data_version") + 1
    )
    StatsCache.objects.filter(profile=profile).delete()


# ---------------------------------------------------------------------------
# Validation (R-MEMO-2, brief 15 Q5)
# ---------------------------------------------------------------------------

def _read(data, name, default=None):
    """Reads ``name`` from a dict ``data``, returning ``default`` when absent."""
    return data.get(name, default)


def _is_real_date(value) -> bool:
    """Whether ``value`` is a real calendar date (Q5).

    Accepts a ``date`` / ``datetime`` directly; otherwise the first 10 characters
    must parse as an ISO ``YYYY-MM-DD`` date, so impossible dates like
    ``2026-13-40`` or ``2026-02-30`` are rejected (not just the YYYY-MM-DD
    prefix the original regex accepted).
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


def validate_memo_input(data, is_draft=False):
    """Validates a memo input per R-MEMO-2 / brief 15 Q5.

    Drafts skip validation entirely (they may be saved incomplete). A non-draft
    requires a REAL date and a matter, and the computed (non-custom) total must
    be ``>= 0``. A missing / invalid date or matter raises ``INVALID_MEMO`` with
    the original message listing the missing fields, e.g. "Missing or invalid
    required field(s): Date, Matter". The non-custom total is computed via
    ``memo_fees`` (never inline) over a row where the custom overrides are
    stripped, so the ``>= 0`` guard is the single fee rule's.
    """
    if is_draft:
        return
    missing = []
    if not _is_real_date(_read(data, "date")):
        missing.append("Date")
    if _read(data, "matter_id") is None and _read(data, "matter") is None:
        missing.append("Matter")
    if missing:
        raise FeesError(
            "INVALID_MEMO",
            f"Missing or invalid required field(s): {', '.join(missing)}",
        )
    # The non-custom total, via the single fee rule (custom overrides stripped).
    probe = {
        "num_appearances": _read(data, "num_appearances", 0) or 0,
        "fees_per_appearance": _read(data, "fees_per_appearance", 0) or 0,
        "num_conferences": _read(data, "num_conferences", 0) or 0,
        "fees_per_conference": _read(data, "fees_per_conference", 0) or 0,
        "fees_misc_drafting": _read(data, "fees_misc_drafting", 0) or 0,
        "custom_fees_appearances": None,
        "custom_fees_conferences": None,
        "custom_fees_misc": None,
        "custom_total_fees": None,
    }
    if memo_fees.effective_total_fees(probe) < 0:
        raise FeesError(
            "INVALID_MEMO", "Total Fees must be greater than or equal to 0"
        )


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------

def _matter_id_from(data):
    """Picks the matter id from either ``matter_id`` or ``matter`` in ``data``."""
    matter = _read(data, "matter_id")
    if matter is not None:
        return matter
    obj = _read(data, "matter")
    if isinstance(obj, Matter):
        return obj.pk
    return obj


def _apply_input_fields(memo, data):
    """Copies the snapshot / line / custom fields from ``data`` onto ``memo``.

    Text snapshot fields never become NULL (the model forbids it): a missing or
    None value becomes ``""``. Numeric line fields default to 0. The four custom
    overrides pass through verbatim (None means "no override"). ``addressee_line1``
    is required by the model, so a missing value stores ``""`` too.
    """
    for field in _SNAPSHOT_FIELDS:
        if field not in data:
            continue
        value = data[field]
        if field in _TEXT_FIELDS or field == "addressee_line1":
            setattr(memo, field, value if value is not None else "")
        else:
            setattr(memo, field, value)
    for field in _LINE_FIELDS:
        if field not in data:
            continue
        value = data[field]
        if field in _NUMERIC_DEFAULT_ZERO:
            setattr(memo, field, value if value is not None else 0)
        elif field in _TEXT_FIELDS:
            setattr(memo, field, value if value is not None else "")
        else:
            setattr(memo, field, value)
    for field in _CUSTOM_FIELDS:
        if field in data:
            setattr(memo, field, data[field])
    if "include_signature" in data:
        memo.include_signature = bool(data["include_signature"])


def _stored_total_fees(memo):
    """The stored ``total_fees`` for ``memo`` via the single fee rule (R-DATA-4, D3)."""
    return memo_fees.resolve_memo_fees(memo).total_fees


# ---------------------------------------------------------------------------
# Create / save draft
# ---------------------------------------------------------------------------

def create_memo(profile, data, is_draft=False):
    """Creates a memo (draft or finalised) and returns the ``Memo`` (R-MEMO-1, R-MEMO-3).

    Validates the input (drafts skip validation, Q5). Loads the matter scoped to
    the profile (``MATTER_NOT_FOUND``); a non-draft requires an ACTIVE matter
    (``MATTER_ARCHIVED``). The addressee / case fields are snapshotted from the
    INPUT (prefilled client-side, not re-read from the matter); ``firm_id`` /
    ``group_id`` are copied from the matter (R-DATA-5).

    Numbering, in one ``transaction.atomic()``:

    * draft -> no number, ``seq = 0``, FY from the date or the current FY;
    * else a supplied number of the automatic shape ``YYYY-YY/N`` (owner decision 5)
      -> a real auto number: its FY must equal the FY of the date, it must be unused,
      ``seq = N`` and the FY counter becomes ``max(last_seq, N)``
      (``memo_numbers.resolve_number``);
    * else a supplied custom number -> ``validate_custom_number`` stored verbatim,
      ``seq = 0``, FY from the date. ``data["force_custom_number"]`` (the importer's
      ``Numbering = Custom``) keeps even an automatic-shaped text as a custom number
      and leaves the counter alone;
    * else -> ``next_number(profile, date)`` split into ``FY/seq``.

    ``total_fees`` is stored from ``resolve_memo_fees`` (D3); ``amount_paid`` /
    ``amount_received`` / ``amount_tds`` default to 0. ``data_version`` is bumped
    once in the same transaction.
    """
    validate_memo_input(data, is_draft)

    matter_id = _matter_id_from(data)
    matter = Matter.objects.filter(profile=profile, pk=matter_id).first()
    if matter is None:
        raise FeesError("MATTER_NOT_FOUND", f"Matter {matter_id} not found")
    if not is_draft and matter.is_archived:
        raise FeesError(
            "MATTER_ARCHIVED", "Memos can only be created for Active Matters"
        )

    raw_date = _read(data, "date")
    custom_raw = (_read(data, "custom_memo_number") or "")
    has_custom_number = bool(str(custom_raw).strip())

    with transaction.atomic():
        memo = Memo(
            profile=profile,
            matter=matter,
            firm_id=matter.firm_id,
            group_id=matter.group_id,
            date=raw_date or None,
            is_draft=is_draft,
            addressee_line1="",
        )
        _apply_input_fields(memo, data)

        if is_draft:
            memo.memo_number = None
            memo.seq = 0
            memo.financial_year = (
                derive_financial_year(raw_date)
                if raw_date
                else current_financial_year()
            )
        elif has_custom_number:
            fy = derive_financial_year(raw_date)
            if _read(data, "force_custom_number"):
                memo.memo_number = memo_numbers.validate_custom_number(
                    profile, custom_raw
                )
                memo.seq = 0
                memo.financial_year = fy
            else:
                (
                    memo.memo_number,
                    memo.financial_year,
                    memo.seq,
                ) = memo_numbers.resolve_number(profile, custom_raw, fy)
        else:
            number = memo_numbers.next_number(profile, raw_date)
            fy, seq_text = number.rsplit("/", 1)
            memo.memo_number = number
            memo.financial_year = fy
            memo.seq = int(seq_text)

        memo.total_fees = _stored_total_fees(memo)
        memo.amount_paid = 0
        memo.amount_received = 0
        memo.amount_tds = 0
        memo.save()
        touch(profile)

    return memo


def save_draft(profile, data):
    """Saves an incomplete draft memo. Convenience for ``create_memo(..., is_draft=True)``."""
    return create_memo(profile, data, is_draft=True)


# ---------------------------------------------------------------------------
# Finalise a draft
# ---------------------------------------------------------------------------

def finalize_draft(profile, memo_id, custom_number=None):
    """Promotes a draft to a numbered memo and returns the ``Memo`` (R-MEMO-3).

    ``MEMO_NOT_FOUND`` if missing / not in profile. A no-op returning the memo if
    it is already finalised. A valid REAL date is required (``INVALID_MEMO``, Q5).
    Assigns a custom number (``validate_custom_number`` with ``exclude`` set) when
    one is supplied, else auto numbers via ``next_number``; sets ``is_draft``
    False, the number, FY and seq. ``total_fees`` is kept in sync. One
    transaction; ``data_version`` bumped once.
    """
    memo = Memo.objects.filter(profile=profile, pk=memo_id).first()
    if memo is None:
        raise FeesError("MEMO_NOT_FOUND", f"Memo {memo_id} not found")
    if not memo.is_draft:
        return memo
    if not _is_real_date(memo.date):
        raise FeesError(
            "INVALID_MEMO", "A valid date is required before finalising a draft"
        )

    has_custom_number = bool(str(custom_number or "").strip())

    with transaction.atomic():
        if has_custom_number:
            (
                memo.memo_number,
                memo.financial_year,
                memo.seq,
            ) = memo_numbers.resolve_number(
                profile,
                custom_number,
                derive_financial_year(memo.date),
                exclude_memo_id=memo.pk,
            )
        else:
            number = memo_numbers.next_number(profile, memo.date)
            fy, seq_text = number.rsplit("/", 1)
            memo.memo_number = number
            memo.financial_year = fy
            memo.seq = int(seq_text)
        memo.is_draft = False
        memo.total_fees = _stored_total_fees(memo)
        memo.save(
            update_fields=[
                "memo_number",
                "financial_year",
                "seq",
                "is_draft",
                "total_fees",
                "updated_at",
            ]
        )
        touch(profile)

    return memo


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def update_memo(profile, memo_id, data):
    """Edits a memo's fields and returns the ``Memo`` (R-MEMO-4, R-DATA-4).

    ``MEMO_NOT_FOUND`` if missing / not in profile. Re-validates with the
    non-draft rules (Q5). Updates the editable snapshot / line / custom fields and
    recomputes-and-stores ``total_fees``.

    FY / number rules:

    * editing a FINALISED memo's date KEEPS its number and ``financial_year``;
    * editing a DRAFT's date RE-DERIVES ``financial_year`` from the new date;
    * a finalised memo may set / keep / clear a custom number: passing
      ``custom_memo_number`` sets it (``resolve_number`` with ``exclude``: an
      automatic-shaped value of the memo's own FY becomes a real auto number and
      raises the counter, any other text is custom and leaves it alone);
      an explicit empty string clears it back to auto for a drafted memo is not
      done here (only drafts auto-number via finalise).

    The sequence is NEVER advanced on edit. Payments / allocations and
    ``amount_paid`` etc. are untouched (payments.py maintains them). One
    transaction; ``data_version`` bumped once.
    """
    memo = Memo.objects.filter(profile=profile, pk=memo_id).first()
    if memo is None:
        raise FeesError("MEMO_NOT_FOUND", f"Memo {memo_id} not found")

    validate_memo_input(data, is_draft=memo.is_draft)

    with transaction.atomic():
        if "date" in data:
            memo.date = data["date"] or None
            if memo.is_draft:
                memo.financial_year = (
                    derive_financial_year(memo.date)
                    if memo.date
                    else current_financial_year()
                )
            # A finalised memo keeps its number and financial_year on a date edit.

        _apply_input_fields(memo, data)

        # A finalised memo may set / keep a custom number when one is supplied.
        if not memo.is_draft and "custom_memo_number" in data:
            raw = data["custom_memo_number"]
            typed = str(raw or "").strip()
            # Typing back the memo's own number changes nothing (a custom memo whose
            # text looks automatic, e.g. a past year's forced custom number, must not
            # turn into an auto number just because the form sent it again).
            if typed and typed != memo.memo_number:
                (
                    memo.memo_number,
                    memo.financial_year,
                    memo.seq,
                ) = memo_numbers.resolve_number(
                    profile, typed, memo.financial_year, exclude_memo_id=memo.pk
                )

        memo.total_fees = _stored_total_fees(memo)
        memo.save()
        touch(profile)

    return memo


# ---------------------------------------------------------------------------
# Write-off (bad debt)
# ---------------------------------------------------------------------------

def set_memo_written_off(profile, memo_id, written_off):
    """Toggles a memo's written-off flag and returns the ``Memo`` (R-MEMO-5).

    ``MEMO_NOT_FOUND`` if missing / not in profile. A fully PAID memo (status from
    the stored ``amount_paid`` vs ``total_fees`` via ``status_and_due``) cannot be
    written off -> ``INVALID_MEMO`` "A fully paid memo cannot be written off".
    Restoring (``written_off=False``) is always allowed. Payments are never
    altered. One transaction; ``data_version`` bumped once.
    """
    memo = Memo.objects.filter(profile=profile, pk=memo_id).first()
    if memo is None:
        raise FeesError("MEMO_NOT_FOUND", f"Memo {memo_id} not found")

    flag = bool(written_off)
    if flag:
        due = memo_fees.status_and_due(memo.total_fees, memo.amount_paid)
        if due.status == "Paid":
            raise FeesError(
                "INVALID_MEMO", "A fully paid memo cannot be written off"
            )

    with transaction.atomic():
        memo.written_off = flag
        memo.save(update_fields=["written_off", "updated_at"])
        touch(profile)

    return memo


# ---------------------------------------------------------------------------
# Delete (does NOT decrement the sequence)
# ---------------------------------------------------------------------------

def delete_memo(profile, memo_id):
    """Deletes a memo, its allocations and any payment left orphaned by it (R-MEMO-6).

    ``MEMO_NOT_FOUND`` if missing / not in profile. In one
    ``transaction.atomic()``:

    1. record the ids of payments that currently have an allocation to this memo;
    2. delete this memo's ``Allocation`` rows (the memo FK on allocations is
       ``PROTECT``, so they must go first);
    3. for each recorded payment, if it now has ZERO remaining allocations delete
       it (that is a payment whose allocations were all to this memo); a payment
       still allocated to another memo keeps its other allocations and survives;
    4. delete the memo.

    The number sequence is NOT decremented (numbers are never reused).
    ``data_version`` is bumped once. Returns nothing.
    """
    memo = Memo.objects.filter(profile=profile, pk=memo_id).first()
    if memo is None:
        raise FeesError("MEMO_NOT_FOUND", f"Memo {memo_id} not found")

    with transaction.atomic():
        payment_ids = list(
            Allocation.objects.filter(memo=memo)
            .values_list("payment_id", flat=True)
            .distinct()
        )
        Allocation.objects.filter(memo=memo).delete()
        if payment_ids:
            orphan_ids = [
                pid
                for pid in payment_ids
                if not Allocation.objects.filter(payment_id=pid).exists()
            ]
            if orphan_ids:
                Payment.objects.filter(pk__in=orphan_ids).delete()
        memo.delete()
        touch(profile)


# ---------------------------------------------------------------------------
# Move to another matter
# ---------------------------------------------------------------------------

def move_memo(profile, memo_id, target_matter_id):
    """Moves a memo to another matter of the same profile and returns the ``Memo``.

    ``MEMO_NOT_FOUND`` if the memo is missing / not in profile; ``MATTER_NOT_FOUND`` if the target
    matter is missing / not in profile; ``MATTER_ARCHIVED`` if the target is archived. The memo's
    ``matter``, ``firm`` and ``group`` follow the target (R-DATA-5). The number, financial year,
    fee lines, totals and payments are untouched, so no stored total changes. Moving a memo to its
    own matter is a no-op that still succeeds. One transaction; ``data_version`` bumped once.
    """
    memo = Memo.objects.filter(profile=profile, pk=memo_id).first()
    if memo is None:
        raise FeesError("MEMO_NOT_FOUND", f"Memo {memo_id} not found")
    target = Matter.objects.filter(profile=profile, pk=target_matter_id).first()
    if target is None:
        raise FeesError("MATTER_NOT_FOUND", f"Matter {target_matter_id} not found")
    if target.is_archived:
        raise FeesError("MATTER_ARCHIVED", "A memo can only be moved to an Active Matter")
    with transaction.atomic():
        memo.matter = target
        memo.firm_id = target.firm_id
        memo.group_id = target.group_id
        memo.save(update_fields=["matter", "firm", "group", "updated_at"])
        touch(profile)
    return memo


# ---------------------------------------------------------------------------
# Create Based On (returns FORM DATA, not a saved memo)
# ---------------------------------------------------------------------------

def create_based_on(profile, source_memo_id):
    """Returns prefilled FORM DATA from an existing memo (R-MEMO-4), NOT a saved memo.

    ``MEMO_NOT_FOUND`` if the source is missing / not in profile. Copies the
    matter, addressee, court, details left/right, parties and types, client,
    counts, rates, dates text, misc description / amount, ``num_drafts`` and all
    custom overrides. The date is blank (the user must enter one). This is a pure
    read: it does NOT bump ``data_version``.
    """
    src = Memo.objects.filter(profile=profile, pk=source_memo_id).first()
    if src is None:
        raise FeesError("MEMO_NOT_FOUND", f"Memo {source_memo_id} not found")

    form = {
        "source_memo_id": source_memo_id,
        "date": "",
        "matter_id": src.matter_id,
    }
    for field in _SNAPSHOT_FIELDS + _LINE_FIELDS + _CUSTOM_FIELDS:
        form[field] = getattr(src, field)
    form["include_signature"] = src.include_signature
    return form


# ---------------------------------------------------------------------------
# Preview number
# ---------------------------------------------------------------------------

def preview_number(profile, date):
    """Read-only preview of the next auto number for ``date`` (R-NUM-4).

    Delegates to ``memo_numbers.preview_next_number`` (creates / advances
    nothing). Does not bump ``data_version``.
    """
    return memo_numbers.preview_next_number(profile, date)


# ---------------------------------------------------------------------------
# Get (detail with derived values)
# ---------------------------------------------------------------------------

def get_memo(profile, memo_id):
    """Returns a memo detail dict with derived values for the memo page (R-MEMO-7).

    ``MEMO_NOT_FOUND`` if missing / not in profile. Reads ``FeesSettings`` ONCE
    for ``default_tds_rate`` and ``overdue_days``. Derived values use the stored
    columns and the memo's allocations:

    * ``fees_appearances`` / ``fees_conferences`` / ``fees_misc`` / ``total_fees``
      from ``resolve_memo_fees``;
    * ``net_of_tds`` at the settings default TDS rate;
    * ``amount_due`` / ``status`` from the stored ``amount_paid`` vs ``total_fees``;
    * ``is_overdue`` at the settings ``overdue_days``;
    * ``date_of_last_payment`` and ``payment_count`` from the allocations.

    This is a pure read: it does NOT bump ``data_version``.
    """
    memo = (
        Memo.objects.filter(profile=profile, pk=memo_id)
        .select_related("firm", "group", "matter")
        .first()
    )
    if memo is None:
        raise FeesError("MEMO_NOT_FOUND", f"Memo {memo_id} not found")

    settings = (
        FeesSettings.objects.filter(profile=profile)
        .values("default_tds_rate", "overdue_days")
        .first()
    ) or {}
    default_tds_rate = settings.get("default_tds_rate") or 0
    overdue_days = settings.get("overdue_days") or 0

    fees = memo_fees.resolve_memo_fees(memo)
    due = memo_fees.status_and_due(fees.total_fees, memo.amount_paid)
    net = memo_fees.net_of_tds(fees.total_fees, default_tds_rate)
    overdue = memo_fees.compute_is_overdue(
        memo.date, due.status, memo.written_off, overdue_days
    )

    allocations = Allocation.objects.filter(memo=memo).select_related("payment")
    payment_count = 0
    last_payment = None
    for alloc in allocations:
        payment_count += 1
        pay_date = alloc.payment.date_of_payment
        if last_payment is None or pay_date > last_payment:
            last_payment = pay_date

    return {
        "id": memo.pk,
        "memo_number": memo.memo_number,
        "financial_year": memo.financial_year,
        "seq": memo.seq,
        "date": memo.date,
        "matter_id": memo.matter_id,
        "firm_id": memo.firm_id,
        "group_id": memo.group_id,
        "firm_name": memo.firm.name,
        "group_name": memo.group.name,
        "matter_name": memo.matter.name,
        "matter_short_name": memo.matter.short_name or None,
        "addressee_line1": memo.addressee_line1,
        "addressee_line2": memo.addressee_line2,
        "court_name": memo.court_name,
        "additional_details_left": memo.additional_details_left,
        "additional_details_right": memo.additional_details_right,
        "plaintiff_name": memo.plaintiff_name,
        "plaintiff_type": memo.plaintiff_type,
        "defendant_name": memo.defendant_name,
        "defendant_type": memo.defendant_type,
        "client": memo.client,
        "num_appearances": memo.num_appearances,
        "dates_of_appearances": memo.dates_of_appearances,
        "fees_per_appearance": memo.fees_per_appearance,
        "num_conferences": memo.num_conferences,
        "dates_of_conferences": memo.dates_of_conferences,
        "fees_per_conference": memo.fees_per_conference,
        "misc_drafting_description": memo.misc_drafting_description,
        "fees_misc_drafting": memo.fees_misc_drafting,
        "num_drafts": memo.num_drafts,
        "custom_fees_appearances": memo.custom_fees_appearances,
        "custom_fees_conferences": memo.custom_fees_conferences,
        "custom_fees_misc": memo.custom_fees_misc,
        "custom_total_fees": memo.custom_total_fees,
        "is_draft": memo.is_draft,
        "include_signature": memo.include_signature,
        "fees_appearances": fees.fees_appearances,
        "fees_conferences": fees.fees_conferences,
        "fees_misc": fees.fees_misc,
        "total_fees": fees.total_fees,
        "net_of_tds": net,
        "amount_paid": memo.amount_paid,
        "amount_received": memo.amount_received,
        "amount_tds": memo.amount_tds,
        "amount_due": due.amount_due,
        "status": due.status,
        "date_of_last_payment": last_payment,
        "payment_count": payment_count,
        "written_off": memo.written_off,
        "is_overdue": overdue,
        "is_custom_number": memo_numbers.is_custom_number(memo),
        "custom_memo_number": (
            memo.memo_number
            if (not memo.is_draft and memo.seq == 0)
            else None
        ),
    }
