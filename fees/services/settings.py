"""Settings and Bank Account services for the Fee Register (R-SET-1, R-SET-2, R-SET-4, R-SET-7).

Ports ``settingsService.ts`` (``getSettings`` / ``updateSettings`` /
``listBankAccounts`` / ``addBankAccount`` / ``updateBankAccount`` /
``deleteBankAccount``) to the Django ORM. Every function takes ``profile``
(``accounts.Profile``) explicitly as its first argument: a profile is one
separate Fee Register, so there is exactly one ``FeesSettings`` row per profile
(a ``OneToOne``), get-or-created on first read so a first ``get_settings``
returns the model defaults (R-SET-1).

Deviations from the original, deliberate and documented:

* The original raised ``AppError('UNKNOWN', message)`` (which maps to a 500) for
  every settings and bank validation failure. The spec (R-SET-1, brief section
  9) says use a validation error (422) with the SAME message. So this module
  raises ``FeesError("INVALID_SETTINGS", message, status=422)`` for settings and
  bank-name validation (``INVALID_*`` already maps to 422 in ``errors.py``; an
  explicit ``status=422`` is passed for clarity). The user-facing messages are
  kept close to the originals.
* Deleting a bank account still referenced by a payment is REFUSED (R-SET-2
  default) with ``FeesError("BANK_IN_USE", message, status=409)`` BEFORE any
  delete, mirroring the firms ``GROUP_IN_USE`` guard, so the caller gets a clean
  409 rather than the ``SET_NULL`` silently blanking payments.
* The Electron-only keys (``zoom_factor``, all ``backup_*`` / ``auto_backup_*``
  / ``last_*``, ``backup_retention``, ``backup_migrated``, ``word_template_path``)
  are DROPPED (brief section 9 "drop"/"replace"): if present in an update input
  they are IGNORED (not stored, no error). The Word template bytes live on
  ``WordTemplate`` (T5.2), so no ``setWordTemplatePath`` equivalent exists here.

Partial update (brief section 9): ``update_settings`` merges only the provided
known keys onto the existing row then saves. A ``None`` passed for a NOT-NULL
field resets it to that field's default; the default is read from the model
field itself (``FeesSettings._meta.get_field(name).get_default()``) so there is
no duplicated default table to drift. Validation runs per key against the merged
candidate values; unknown and Electron-only keys are skipped silently.

The memo-filename pattern (``memo_filename_pattern``) will be validated by
``fees.services.exports.filenames.validate_pattern`` once T5.1 adds it. That
module does not exist yet, so the import is GUARDED: when it is unavailable the
pattern is stored as-is (capped at the model's 200 chars) and real validation is
wired in T5.1. Do NOT create ``filenames.py`` here.

R-DATA-6 (``data_version`` bump): ``update_settings`` and every mutating bank
operation run in one ``transaction.atomic()`` and call ``touch(profile)`` EXACTLY
ONCE (reused from ``memos.py``). Reads (``get_settings`` / ``list_bank_accounts``)
never bump it. No module-level mutable state; ``diary`` is never imported.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models.functions import Lower

from fees.errors import FeesError
from fees.models import BankAccount, FeesSettings, Payment
from fees.services.memos import touch

__all__ = [
    "MAX_BANK_ACCOUNTS",
    "MAX_BANK_NAME",
    "MAX_DETAILS",
    "MAX_SUFFIX",
    "SETTINGS_KEYS",
    "get_settings",
    "update_settings",
    "list_bank_accounts",
    "add_bank_account",
    "update_bank_account",
    "delete_bank_account",
]

#: A profile may have at most this many bank accounts (original ``MAX_BANK_ACCOUNTS``).
MAX_BANK_ACCOUNTS = 50
#: Bank account names are 1 to 200 characters (R-SET-2).
MAX_BANK_NAME = 200
#: The two additional-details fields are at most this many characters (brief 9).
MAX_DETAILS = 500
#: Money suffixes are at most this many characters (R-SET-4, brief 9).
MAX_SUFFIX = 12
#: A generous cap for the multi-line memo text defaults (TextFields are not
#: DB-bounded; the brief does not cap them tightly, so this only rejects absurd
#: input while leaving line breaks intact).
MAX_MEMO_TEXT = 4000

#: Allowed values for the choice-like text settings.
_DEFAULT_TAB_CHOICES = frozenset(
    ("memos", "dashboard", "statistics", "firms", "feebook", "outstanding", "settings")
)
_MONEY_UNIT_CHOICES = frozenset(("full", "truncated"))
_PAYMENT_AMOUNT_CHOICES = frozenset(("zero", "full", "netOfTds"))

#: The financial-year format: YYYY-YY (ported from the original regex).
_FY_RE = re.compile(r"^(\d{4})-(\d{2})$")

#: The settings keys this service accepts in an update input (the brief section 9
#: "yes"/"add" keys). Anything not here (Electron-only or unknown) is ignored.
SETTINGS_KEYS = frozenset(
    (
        "default_fees_per_appearance",
        "default_fees_per_conference",
        "default_fees_misc_drafting",
        "default_additional_details_left",
        "default_additional_details_right",
        "default_court_name",
        "default_tds_rate",
        "overdue_days",
        "default_tab",
        "initial_financial_year",
        "memos_start_year",
        "feebook_start_year",
        "money_unit",
        "money_suffix_thousands",
        "money_suffix_lac",
        "money_suffix_crore",
        "hide_payment_when_paid",
        "default_lines_enabled",
        "default_payment_amount",
        "show_status_dots",
        "dashboard_kpis",
        "statistics_enabled",
        "dashboard_kpis_enabled",
        "export_owner_name",
        "memo_filename_pattern",
        "memo_default_name",
        "memo_default_designation",
        "memo_default_address",
        "memo_default_bank_details",
        "memo_default_pan",
    )
)

#: The settings keys surfaced by ``get_settings`` (SETTINGS_KEYS plus the cache
#: stamp so a caller can read the current ``data_version`` without a second hop).
_READ_KEYS = tuple(sorted(SETTINGS_KEYS)) + ("data_version",)


def _invalid(message):
    """A 422 settings validation error (replaces the original ``UNKNOWN`` / 500)."""
    return FeesError("INVALID_SETTINGS", message, status=422)


def _field_default(name):
    """The model default for a settings field (used to reset a NOT-NULL field on None)."""
    return FeesSettings._meta.get_field(name).get_default()


def get_settings(profile):
    """Returns the current settings as a dict, get-or-creating the row (R-SET-1).

    A first read creates the row with the model defaults so the returned dict
    carries ``default_tds_rate`` 10, ``money_unit`` "full", ``export_owner_name``
    "Ziyad Madon", the five memo text defaults blank and the two switches True.
    Read-only: it does NOT bump ``data_version``.
    """
    settings, _created = FeesSettings.objects.get_or_create(profile=profile)
    return {key: getattr(settings, key) for key in _READ_KEYS}


# ---------------------------------------------------------------------------
# Per-key validation (ported from updateSettings)
# ---------------------------------------------------------------------------

def _is_valid_financial_year(value):
    """Whether ``value`` is a YYYY-YY string with consecutive years (ported check)."""
    match = _FY_RE.match(str(value))
    if not match:
        return False
    start = int(match.group(1))
    end = int(match.group(2))
    return (start + 1) % 100 == end


def _as_decimal(value, message):
    """Coerces ``value`` to ``Decimal`` or raises the 422 validation error."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise _invalid(message) from exc


def _validate_candidate(key, value):
    """Validates one merged key/value, returning the value to store (R-SET-1/4/7).

    ``value`` is the merged candidate (never ``None`` here: a ``None`` input has
    already been reset to the field default by ``_merge`` before validation).
    Raises ``FeesError("INVALID_SETTINGS", ...)`` (422) on a bad value.
    """
    if key == "default_tds_rate":
        rate = _as_decimal(value, "TDS rate must be between 0 and 100")
        if rate < 0 or rate > 100:
            raise _invalid("TDS rate must be between 0 and 100")
        return rate
    if key == "overdue_days":
        message = "Overdue days must be a whole number between 0 and 3650"
        try:
            number = float(value)
        except (ValueError, TypeError) as exc:
            raise _invalid(message) from exc
        if number != int(number):
            raise _invalid(message)
        days = int(number)
        if days < 0 or days > 3650:
            raise _invalid(message)
        return days
    if key == "default_tab":
        if value not in _DEFAULT_TAB_CHOICES:
            raise _invalid("Invalid default page")
        return value
    if key == "initial_financial_year":
        if not _is_valid_financial_year(value):
            raise _invalid('Initial financial year must be in the form "2026-27"')
        return value
    if key in ("memos_start_year", "feebook_start_year"):
        if not _is_valid_financial_year(value):
            raise _invalid('Start year must be in the form "2026-27"')
        return value
    if key == "money_unit":
        if value not in _MONEY_UNIT_CHOICES:
            raise _invalid("Invalid money display mode")
        return value
    if key in ("money_suffix_thousands", "money_suffix_lac", "money_suffix_crore"):
        text = str(value)
        if len(text) > MAX_SUFFIX:
            raise _invalid(f"Money suffix must be at most {MAX_SUFFIX} characters")
        return text
    if key == "default_payment_amount":
        if value not in _PAYMENT_AMOUNT_CHOICES:
            raise _invalid("Invalid default payment amount")
        return value
    if key in ("default_additional_details_left", "default_additional_details_right"):
        text = str(value)
        if len(text) > MAX_DETAILS:
            raise _invalid(
                f"Additional details must be at most {MAX_DETAILS} characters"
            )
        return text
    if key == "default_court_name":
        text = str(value)
        if len(text) > 300:
            raise _invalid("Court name must be at most 300 characters")
        return text
    if key in (
        "default_fees_per_appearance",
        "default_fees_per_conference",
        "default_fees_misc_drafting",
    ):
        amount = _as_decimal(value, "Default fees must be a number of 0 or more")
        if amount < 0:
            raise _invalid("Default fees must be a number of 0 or more")
        return amount
    if key in (
        "hide_payment_when_paid",
        "default_lines_enabled",
        "show_status_dots",
        "statistics_enabled",
        "dashboard_kpis_enabled",
    ):
        return bool(value)
    if key == "dashboard_kpis":
        return str(value)
    if key == "export_owner_name":
        text = str(value)
        if len(text) > 80:
            raise _invalid("Owner name must be at most 80 characters")
        return text
    if key == "memo_filename_pattern":
        text = str(value)
        if len(text) > 200:
            raise _invalid("File-name pattern must be at most 200 characters")
        # T5.1 wires the real validator; guard the optional import until then.
        try:
            from fees.services.exports.filenames import validate_pattern
        except ImportError:
            return text
        validate_pattern(text)
        return text
    if key in ("memo_default_name", "memo_default_designation"):
        text = str(value)
        if len(text) > 120:
            raise _invalid("This field must be at most 120 characters")
        return text
    if key == "memo_default_pan":
        text = str(value)
        if len(text) > 20:
            raise _invalid("PAN must be at most 20 characters")
        return text
    if key in ("memo_default_address", "memo_default_bank_details"):
        # Multi-line TextFields (R-SET-7): keep line breaks; only reject absurd length.
        text = str(value)
        if len(text) > MAX_MEMO_TEXT:
            raise _invalid(f"This field must be at most {MAX_MEMO_TEXT} characters")
        return text
    # A known key with no extra rule: store the raw value.
    return value


def _merge(settings, data):
    """Applies validated known keys from ``data`` onto ``settings`` (partial update).

    Only keys in ``SETTINGS_KEYS`` are considered; Electron-only and unknown keys
    are skipped silently. A ``None`` for a field resets it to the field's model
    default (R-SET-1: a null on a not-null field resets the default) and is NOT
    validated further. Every other provided value is validated and the coerced
    result is stored. Returns the list of changed model field names.
    """
    changed = []
    for key, raw in data.items():
        if key not in SETTINGS_KEYS:
            continue
        if raw is None:
            value = _field_default(key)
        else:
            value = _validate_candidate(key, raw)
        setattr(settings, key, value)
        changed.append(key)
    return changed


def update_settings(profile, data):
    """Partial-updates the settings row and returns the updated settings dict (R-SET-1).

    Merges only the provided known keys onto the existing row (get-or-created),
    validating each per key (a bad value raises ``FeesError("INVALID_SETTINGS",
    message, status=422)``). A ``None`` resets a field to its model default;
    Electron-only and unknown keys are ignored. The whole merge-save-bump runs in
    one ``transaction.atomic()`` and bumps ``data_version`` exactly once.
    """
    with transaction.atomic():
        settings, _created = FeesSettings.objects.get_or_create(profile=profile)
        changed = _merge(settings, data)
        if changed:
            settings.save(update_fields=changed + ["updated_at"])
        touch(profile)
    return get_settings(profile)


# ---------------------------------------------------------------------------
# Bank accounts (R-SET-2)
# ---------------------------------------------------------------------------

def _validate_bank_name(raw):
    """Trims ``raw`` and returns it, or raises the 422 validation error (1 to 200)."""
    clean = (raw or "").strip()
    if len(clean) < 1 or len(clean) > MAX_BANK_NAME:
        raise _invalid(
            f"Bank account name must be between 1 and {MAX_BANK_NAME} characters"
        )
    return clean


def list_bank_accounts(profile):
    """Bank accounts for a profile ordered by ``Lower(name)`` (R-SET-2). Read-only.

    Returns a queryset; does NOT bump ``data_version``.
    """
    return BankAccount.objects.filter(profile=profile).order_by(Lower("name"))


def add_bank_account(profile, name):
    """Adds a bank account (R-SET-2) and returns the ``BankAccount``.

    Validates and trims the name (1 to 200 chars), enforces at most
    ``MAX_BANK_ACCOUNTS`` per profile and rejects a case-insensitive duplicate
    within the profile. One transaction; ``data_version`` bumped once.
    """
    clean = _validate_bank_name(name)
    with transaction.atomic():
        if BankAccount.objects.filter(profile=profile).count() >= MAX_BANK_ACCOUNTS:
            raise _invalid(f"At most {MAX_BANK_ACCOUNTS} bank accounts are allowed")
        if BankAccount.objects.filter(profile=profile, name__iexact=clean).exists():
            raise _invalid(f'Bank account "{clean}" already exists')
        account = BankAccount.objects.create(profile=profile, name=clean)
        touch(profile)
    return account


def update_bank_account(profile, account_id, name):
    """Renames a bank account (R-SET-2) and returns the ``BankAccount``.

    ``BANK_ACCOUNT_NOT_FOUND`` if missing or not in this profile;
    ``INVALID_SETTINGS`` (422) on an invalid or case-insensitively colliding name
    within the profile. One transaction; ``data_version`` bumped once.
    """
    clean = _validate_bank_name(name)
    with transaction.atomic():
        account = BankAccount.objects.filter(profile=profile, pk=account_id).first()
        if account is None:
            raise FeesError(
                "BANK_ACCOUNT_NOT_FOUND", f"Bank account {account_id} not found"
            )
        dupe = (
            BankAccount.objects.filter(profile=profile, name__iexact=clean)
            .exclude(pk=account.pk)
            .exists()
        )
        if dupe:
            raise _invalid(f'Bank account "{clean}" already exists')
        account.name = clean
        account.save(update_fields=["name", "updated_at"])
        touch(profile)
    return account


def delete_bank_account(profile, account_id):
    """Deletes a bank account (R-SET-2); REFUSES when a payment references it.

    ``BANK_ACCOUNT_NOT_FOUND`` if missing or not in this profile. If any
    ``Payment`` still references the account, raises ``FeesError("BANK_IN_USE",
    message, status=409)`` BEFORE any delete (R-SET-2 default is refuse), so the
    caller gets a clean documented error rather than the ``SET_NULL`` silently
    blanking payments. Otherwise deletes the account. One transaction;
    ``data_version`` bumped once. Returns ``None``.
    """
    with transaction.atomic():
        account = BankAccount.objects.filter(profile=profile, pk=account_id).first()
        if account is None:
            raise FeesError(
                "BANK_ACCOUNT_NOT_FOUND", f"Bank account {account_id} not found"
            )
        if Payment.objects.filter(profile=profile, bank_account=account).exists():
            raise FeesError(
                "BANK_IN_USE",
                "This bank account is used by a payment, so it cannot be removed.",
                status=409,
            )
        account.delete()
        touch(profile)
    return None
