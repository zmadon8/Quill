"""Excel restore: preview and replace-all restore from a desktop or web ``.xlsx`` (design 7.2, R-BK-2).

Ports ``restoreFromBuffer`` / ``readSheetRows`` of ``backupService.ts`` and the porting brief section 11.

Public API
----------
``preview_workbook(source, profile=None) -> dict``
    Reads the file (no database writes) and returns counts per sheet, the memo date range, totals,
    what is missing and, when ``profile`` is given, the counts it would replace. Raises
    ``FeesError("RESTORE_FAILED")`` for an unreadable file or a missing required sheet.

``restore_workbook(profile, source, confirmation, user=None, backup_func=None) -> dict``
    Replaces ALL of ``profile``'s Fee Register data with the file. Order of work:

    1. the typed confirmation must equal ``RESTORE_CONFIRMATION`` (else ``INVALID_CONFIRMATION``);
    2. size (10 MB), extension and zip sanity are checked before the file is opened;
    3. the heavy lock ``heavy_operation("excel_restore")`` is taken (``Busy`` propagates);
    4. the workbook is opened (``openpyxl`` read-only, ``data_only``) and the required sheets and key
       columns are verified, still without touching the database;
    5. a ``pre_restore`` suite backup is made OUTSIDE the transaction (it carries the Word template and
       signature bytes). If it fails nothing is changed;
    6. ONE transaction: lock the profile row, delete this profile's rows child first, insert parents
       first in batches of 500 with ``bulk_create`` while filling ``old id -> new id`` maps and
       rewriting every foreign key, backfill allocations from the legacy ``payments.memo_id``,
       recompute ``total_fees`` (``memo_fees.resolve_memo_fees``) and the paid columns
       (``payments.recompute_paid``), rebuild ``NumberSequence`` as ``MAX(seq)`` per financial year over
       non-draft memos, apply ``Settings`` and ``WebSettings`` (including the five memo text defaults), and the per-memo
       signature flag from the web-only ``WebMemoFlags`` sheet (absent: the file's signature default),
       and ``touch`` (``data_version`` bump and ``StatsCache`` purge);
    7. any failure inside the transaction rolls everything back and raises ``FeesError("RESTORE_FAILED")``.

    Returns ``{"counts": {...}, "rows_imported": n, "warnings": [...], "fees_check": {...},
    "backup_id": id}``.

Notes
-----
* Memory: the workbook is read-only and streamed row by row; the only per-row state kept is the id
  maps (about 100 bytes per parent row) and the payment-to-memo links of the legacy backfill.
* ``created_at`` / ``updated_at`` in the file are not restored: ``auto_now(_add)`` stamps restored rows
  with the restore time (``bulk_create`` cannot override them).
* ``WordTemplate`` (including the signature image) is not in an ``.xlsx`` and is left untouched.
* ``openpyxl`` is imported inside functions only.
"""
import contextlib
import datetime
import logging
import os
import zipfile
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Max

from fees.errors import FeesError
from fees.models import (
    Allocation,
    BankAccount,
    Firm,
    Group,
    Matter,
    Memo,
    NumberSequence,
    Payment,
    PeriodAdjustment,
    SavedView,
)
from fees.services import integrity, memo_fees, payments
from fees.services.clear_all import reset_settings, wipe_profile_data
from fees.services.excel_backup import (
    MEMO_TEXT_DEFAULT_KEYS,
    NOT_NULL_DEFAULTS,
    OPTIONAL_SHEETS,
    SETTINGS_COLUMNS,
    TABLES,
    WEB_MEMO_FLAGS_SHEET,
    WEB_SETTINGS_KEYS,
    WEB_SETTINGS_SHEET,
)
from fees.services.financial_year import derive_financial_year
from fees.services.heavy import Busy, heavy_operation
from fees.services.memos import touch
from fees.services.money import round2

__all__ = [
    "RESTORE_CONFIRMATION",
    "MAX_RESTORE_BYTES",
    "MAX_UNCOMPRESSED_BYTES",
    "preview_workbook",
    "restore_workbook",
]

logger = logging.getLogger(__name__)

#: The phrase the user must type before a restore (R-BK-2, R-UI-5).
RESTORE_CONFIRMATION = "This replaces ALL your data"
#: Upload cap (R-NFR-9), checked before the file is opened.
MAX_RESTORE_BYTES = 10 * 1024 * 1024
#: Total uncompressed size of the zip parts; a guard against a decompression bomb.
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024

_BATCH = 500
_TABLE_COLUMNS = dict(TABLES)

#: Columns that must be present in a sheet's header row for the rows to be usable (ids and keys).
_MIN_COLUMNS = {
    "Firms": ["id", "name"],
    "Partners": ["id", "firm_id", "name"],
    "Matters": ["id", "firm_id", "partner_id", "name"],
    "BankAccounts": ["id", "name"],
    "Memos": ["id", "matter_id"],
    "Payments": ["id", "amount", "date_of_payment"],
    "PaymentAllocations": ["payment_id", "memo_id"],
    "PeriodAdjustments": ["financial_year", "month"],
    "SavedViews": ["name"],
    "Settings": [],
}


def _fail(message):
    return FeesError("RESTORE_FAILED", message)


# ---------------------------------------------------------------------------
# Source checks and opening
# ---------------------------------------------------------------------------

def _source_size(source):
    size = getattr(source, "size", None)
    if isinstance(size, int):
        return size
    if isinstance(source, (str, os.PathLike)):
        return os.path.getsize(source)
    position = source.tell()
    source.seek(0, os.SEEK_END)
    size = source.tell()
    source.seek(position)
    return size


def _source_name(source):
    if isinstance(source, (str, os.PathLike)):
        return os.fspath(source)
    name = getattr(source, "name", None)
    return name if isinstance(name, str) else None


def _rewind(source):
    if hasattr(source, "seek"):
        source.seek(0)


def _check_source(source):
    """Size, extension and zip sanity, before the file is opened as a workbook."""
    name = _source_name(source)
    if name is not None and os.path.splitext(name)[1].lower() not in ("", ".xlsx"):
        raise _fail("The backup file must be an Excel .xlsx file.")
    try:
        size = _source_size(source)
    except (OSError, ValueError) as exc:
        raise _fail("The backup file could not be read.") from exc
    if size > MAX_RESTORE_BYTES:
        raise _fail("The backup file is larger than 10 MB, so it was not opened.")
    if size == 0:
        raise _fail("The backup file is empty.")
    _rewind(source)
    try:
        with zipfile.ZipFile(source) as archive:
            total = sum(info.file_size for info in archive.infolist())
    except (zipfile.BadZipFile, OSError, ValueError, EOFError) as exc:
        raise _fail("The backup file could not be read.") from exc
    if total > MAX_UNCOMPRESSED_BYTES:
        raise _fail("The backup file expands to more than 100 MB, so it was not opened.")
    _rewind(source)


@contextlib.contextmanager
def _open_workbook(source):
    """Open the workbook read-only and check the required sheets; always closes it."""
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(source, read_only=True, data_only=True)
    except Exception as exc:
        raise _fail("The backup file could not be read.") from exc
    try:
        names = set(workbook.sheetnames)
        for sheet, _columns in TABLES:
            if sheet not in names and sheet not in OPTIONAL_SHEETS:
                raise _fail(f'Backup is missing the "{sheet}" sheet')
        yield workbook
    finally:
        workbook.close()


# ---------------------------------------------------------------------------
# Reading rows (port of readSheetRows)
# ---------------------------------------------------------------------------

def _read_sheet(workbook, sheet, columns, required=()):
    """Yield ``(row number, {column: value})`` for the data rows of ``sheet``.

    Headers are mapped by name (extra columns are ignored, missing ones read as blank). A blank value
    is ``None``; a NOT NULL column with a default (``NOT_NULL_DEFAULTS``) takes that default. A row
    with no value in any wanted column is skipped. A sheet that is absent yields nothing.
    """
    if sheet not in workbook.sheetnames:
        return
    worksheet = workbook[sheet]
    if hasattr(worksheet, "reset_dimensions"):
        worksheet.reset_dimensions()
    rows = worksheet.iter_rows(values_only=True)
    header = next(rows, None)
    if header is None:
        return
    position = {}
    for index, cell in enumerate(header):
        if cell is None:
            continue
        position.setdefault(str(cell).strip(), index)
    missing = [name for name in required if name not in position]
    if missing:
        raise _fail(f'Sheet "{sheet}" lacks the column "{missing[0]}"')
    wanted = [(name, position.get(name)) for name in columns]
    for number, row in enumerate(rows, start=2):
        values = {}
        any_value = False
        for name, index in wanted:
            value = row[index] if index is not None and index < len(row) else None
            if isinstance(value, str) and value == "":
                value = None
            if value is not None:
                any_value = True
            elif name in NOT_NULL_DEFAULTS:
                value = NOT_NULL_DEFAULTS[name]
            values[name] = value
        if any_value:
            yield number, values


def _rows(workbook, sheet):
    """Rows of ``sheet`` with the contract columns and the minimum-column check."""
    return _read_sheet(workbook, sheet, _TABLE_COLUMNS[sheet], _MIN_COLUMNS.get(sheet, ()))


# ---------------------------------------------------------------------------
# Value coercion
# ---------------------------------------------------------------------------

def _bad(sheet, number, column, value):
    return _fail(f'Sheet "{sheet}" row {number}: the value {value!r} in "{column}" is not valid')


def _key(value):
    """An old id as an int map key, or ``None`` when blank or not a whole number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value == int(value) else None
    try:
        return int(str(value).strip())
    except ValueError:
        try:
            number = float(str(value).strip())
        except ValueError:
            return None
        return int(number) if number == int(number) else None


def _text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    return str(value)


def _text_or_none(value):
    text = _text(value).strip()
    return text or None


def _int(value, sheet, number, column, default=0):
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value).strip()))
    except (ValueError, OverflowError):
        raise _bad(sheet, number, column, value) from None


def _bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, (bool, int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "t"):
        return True
    if text in ("0", "false", "no", "n", "f", ""):
        return False
    return default


def _dec(value, sheet, number, column, nullable=False):
    """A two-decimal ``Decimal`` from a number or text (``₹`` and commas tolerated)."""
    if value is None:
        return None if nullable else Decimal("0.00")
    if isinstance(value, bool):
        value = int(value)
    try:
        if isinstance(value, str):
            cleaned = value.replace("\u20b9", "").replace(",", "").strip()
            if not cleaned:
                return None if nullable else Decimal("0.00")
            result = Decimal(cleaned)
        elif isinstance(value, float):
            result = Decimal(repr(value))
        else:
            result = Decimal(value)
        if not result.is_finite():
            raise InvalidOperation
        return round2(result)
    except (InvalidOperation, ValueError, TypeError):
        raise _bad(sheet, number, column, value) from None


def _date(value):
    """A ``date`` from a date, datetime or ISO text; ``None`` if blank or not a real date."""
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def _ref(id_map, value, sheet, number, what):
    """Map an old foreign key to the new id, or fail with a clear message."""
    key = _key(value)
    if key is None or key not in id_map:
        raise _fail(f'Sheet "{sheet}" row {number}: the {what} {value!r} is not in the backup')
    return id_map[key]


def _required_name(value, sheet, number):
    name = _text(value).strip()
    if not name:
        raise _fail(f'Sheet "{sheet}" row {number}: the name is blank')
    return name


# ---------------------------------------------------------------------------
# Batched insert with id remapping
# ---------------------------------------------------------------------------

class _Loader:
    """Collect model objects and ``bulk_create`` them 500 at a time, filling ``id_map``.

    ``add(old_id, obj, extra)`` queues one object. On flush, ``id_map[old_id]`` becomes the new primary
    key (when ``old_id`` is not ``None``) and the optional ``hook(obj, extra)`` is called, so a caller
    can record data keyed by the new id without holding the objects.
    """

    def __init__(self, model, id_map=None, hook=None):
        self.model = model
        self.id_map = id_map
        self.hook = hook
        self.count = 0
        self._items = []

    def add(self, old_id, obj, extra=None):
        self._items.append((old_id, obj, extra))
        self.count += 1
        if len(self._items) >= _BATCH:
            self.flush()

    def flush(self):
        if not self._items:
            return
        objs = [item[1] for item in self._items]
        self.model.objects.bulk_create(objs)
        for old_id, obj, extra in self._items:
            if old_id is not None and self.id_map is not None:
                self.id_map[old_id] = obj.pk
            if self.hook is not None:
                self.hook(obj, extra)
        self._items = []


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

_SETTINGS_MONEY = ("default_fees_per_appearance", "default_fees_per_conference", "default_fees_misc_drafting")
_SETTINGS_BOOL = ("hide_payment_when_paid", "default_lines_enabled", "show_status_dots")
_SETTINGS_TEXT = (
    "default_additional_details_left",
    "default_additional_details_right",
    "default_court_name",
    "default_tab",
    "initial_financial_year",
    "memos_start_year",
    "feebook_start_year",
    "money_unit",
    "money_suffix_thousands",
    "money_suffix_lac",
    "money_suffix_crore",
    "default_payment_amount",
    "dashboard_kpis",
)
_SETTINGS_SHEET_COLUMNS = ["id"] + [name for name, _kind, _default in SETTINGS_COLUMNS]
_WEB_TEXT_KEYS = ("export_owner_name", "memo_filename_pattern") + tuple(MEMO_TEXT_DEFAULT_KEYS)
_WEB_BOOL_KEYS = ("statistics_enabled", "dashboard_kpis_enabled")


def _apply_settings_row(settings, values, number):
    """Copy the desktop ``Settings`` row onto the ``FeesSettings`` object (Electron-only columns ignored)."""
    for name in _SETTINGS_MONEY:
        setattr(settings, name, _dec(values.get(name), "Settings", number, name))
    settings.default_tds_rate = _dec(values.get("default_tds_rate"), "Settings", number, "default_tds_rate")
    settings.overdue_days = max(0, _int(values.get("overdue_days"), "Settings", number, "overdue_days"))
    for name in _SETTINGS_BOOL:
        setattr(settings, name, _bool(values.get(name)))
    for name in _SETTINGS_TEXT:
        setattr(settings, name, _text(values.get(name)))


def _web_settings_found(workbook):
    """The known ``WebSettings`` keys of the file as ``{key: value}`` (empty when the sheet is absent)."""
    found = {}
    for _number, values in _read_sheet(workbook, WEB_SETTINGS_SHEET, ["key", "value"], ["key", "value"]):
        key = _text(values["key"]).strip()
        if key in WEB_SETTINGS_KEYS:
            found[key] = values["value"]
    return found


def _memo_flags(workbook, found):
    """``(flags, default)``: ``{old memo id: include_signature}`` from ``WebMemoFlags`` and the value a
    memo takes when the file has no flag for it (the file's ``memo_signature_default``, off when absent)."""
    default = _bool(found.get("memo_signature_default"), default=False)
    if WEB_MEMO_FLAGS_SHEET not in workbook.sheetnames:
        return {}, default
    flags = {}
    for _number, values in _read_sheet(
        workbook, WEB_MEMO_FLAGS_SHEET, ["memo_id", "include_signature"], ["memo_id"]
    ):
        key = _key(values["memo_id"])
        if key is not None:
            flags[key] = _bool(values["include_signature"], default=False)
    return flags, default


def _apply_web_settings(settings, workbook, found=None):
    """Apply the ``WebSettings`` sheet (key, value) when present; unknown keys are ignored."""
    if found is None:
        found = _web_settings_found(workbook)
    for key in _WEB_BOOL_KEYS:
        if key in found:
            setattr(settings, key, _bool(found[key], default=True))
    if "memo_signature_default" in found:
        settings.memo_signature_default = _bool(found["memo_signature_default"], default=False)
    if _text(found.get("list_default_filter")).strip() in ("all", "active"):
        settings.list_default_filter = _text(found["list_default_filter"]).strip()
    for key in _WEB_TEXT_KEYS:
        if key in found:
            text = _text(found[key])
            if key == "export_owner_name" and not text.strip():
                continue  # keep the default name rather than a blank one
            setattr(settings, key, text)
    return len(found)


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

def _memo_for_fees(values, number):
    """A transient ``Memo`` carrying only the fee inputs, for ``resolve_memo_fees``."""
    return Memo(
        num_appearances=_int(values.get("num_appearances"), "Memos", number, "num_appearances"),
        fees_per_appearance=_dec(values.get("fees_per_appearance"), "Memos", number, "fees_per_appearance"),
        num_conferences=_int(values.get("num_conferences"), "Memos", number, "num_conferences"),
        fees_per_conference=_dec(values.get("fees_per_conference"), "Memos", number, "fees_per_conference"),
        fees_misc_drafting=_dec(values.get("fees_misc_drafting"), "Memos", number, "fees_misc_drafting"),
        custom_fees_appearances=_dec(
            values.get("custom_fees_appearances"), "Memos", number, "custom_fees_appearances", True
        ),
        custom_fees_conferences=_dec(
            values.get("custom_fees_conferences"), "Memos", number, "custom_fees_conferences", True
        ),
        custom_fees_misc=_dec(values.get("custom_fees_misc"), "Memos", number, "custom_fees_misc", True),
        custom_total_fees=_dec(values.get("custom_total_fees"), "Memos", number, "custom_total_fees", True),
    )


def _current_counts(profile):
    return {
        "firms": Firm.objects.filter(profile=profile).count(),
        "matters": Matter.objects.filter(profile=profile).count(),
        "memos": Memo.objects.filter(profile=profile).count(),
        "payments": Payment.objects.filter(profile=profile).count(),
        "allocations": Allocation.objects.filter(profile=profile).count(),
    }


def preview_workbook(source, profile=None):
    """Read the file without touching the database and describe what a restore would do.

    Keys: ``sheets`` (rows per sheet present), ``missing_optional`` (optional sheets absent),
    ``memo_date_min`` / ``memo_date_max`` (ISO text or ``None``), ``total_fees`` (sum of the resolved
    fees of non-draft memos), ``payments_total`` (sum of payment amounts), ``payments_with_memo_id``
    (legacy links), ``has_web_settings``, ``confirmation_phrase`` and, when ``profile`` is given,
    ``replaces`` (the profile's current counts that the restore would delete).
    """
    _check_source(source)
    try:
        with heavy_operation("excel_restore"):
            with _open_workbook(source) as workbook:
                names = set(workbook.sheetnames)
                sheets = {}
                date_min = date_max = None
                total_fees = Decimal("0.00")
                payments_total = Decimal("0.00")
                legacy_links = 0
                for sheet, _columns in TABLES:
                    if sheet not in names:
                        continue
                    count = 0
                    for number, values in _rows(workbook, sheet):
                        count += 1
                        if sheet == "Memos":
                            memo_date = _date(values.get("date"))
                            if memo_date is not None:
                                date_min = memo_date if date_min is None else min(date_min, memo_date)
                                date_max = memo_date if date_max is None else max(date_max, memo_date)
                            if not _bool(values.get("is_draft")):
                                total_fees += memo_fees.resolve_memo_fees(_memo_for_fees(values, number)).total_fees
                        elif sheet == "Payments":
                            payments_total += _dec(values.get("amount"), "Payments", number, "amount")
                            if _key(values.get("memo_id")) is not None:
                                legacy_links += 1
                    sheets[sheet] = count
                has_web = WEB_SETTINGS_SHEET in names
    except (FeesError, Busy):
        raise
    except Exception as exc:
        raise _fail("The backup file could not be read.") from exc
    result = {
        "sheets": sheets,
        "missing_optional": [s for s in sorted(OPTIONAL_SHEETS) if s not in names],
        "memo_date_min": date_min.isoformat() if date_min else None,
        "memo_date_max": date_max.isoformat() if date_max else None,
        "total_fees": total_fees,
        "payments_total": payments_total,
        "payments_with_memo_id": legacy_links,
        "has_web_settings": has_web,
        "confirmation_phrase": RESTORE_CONFIRMATION,
    }
    if profile is not None:
        result["replaces"] = _current_counts(profile)
    return result


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

def _default_backup(kind, user):
    from backups import services

    return services.create_backup(kind, user)


def _backfill_allocations(profile, links, has_allocation):
    """Create an allocation for each payment that has a legacy ``memo_id`` but no allocation row.

    ``links`` maps new payment id to new memo id. The allocation takes the payment's net amount and
    TDS. Returns the number created.
    """
    pending = [pid for pid in links if pid not in has_allocation]
    created = 0
    for start in range(0, len(pending), _BATCH):
        chunk = pending[start:start + _BATCH]
        rows = Payment.objects.filter(pk__in=chunk).values_list("pk", "amount", "tds_amount")
        Allocation.objects.bulk_create(
            [
                Allocation(
                    payment_id=pid, memo_id=links[pid], profile=profile, amount=amount, tds_amount=tds
                )
                for pid, amount, tds in rows
            ]
        )
        created += len(chunk)
    return created


def _recompute_paid_all(profile):
    """Rewrite the stored paid columns of every memo that has allocations (the sole writer)."""
    memo_ids = list(
        Allocation.objects.filter(profile=profile).values_list("memo_id", flat=True).distinct()
    )
    for start in range(0, len(memo_ids), _BATCH):
        payments.recompute_paid(memo_ids[start:start + _BATCH])


def _rebuild_sequences(profile):
    """``NumberSequence`` = MAX(seq) per financial year over non-draft memos (drafts do not count)."""
    rows = (
        Memo.objects.filter(profile=profile, is_draft=False)
        .exclude(financial_year="")
        .values("financial_year")
        .annotate(top=Max("seq"))
    )
    NumberSequence.objects.bulk_create(
        [NumberSequence(profile=profile, financial_year=r["financial_year"], last_seq=r["top"] or 0) for r in rows]
    )
    return len(rows)


def _load(profile, workbook):
    """Insert everything from the workbook (inside the caller's transaction). Returns the report."""
    from accounts.models import Profile

    Profile.objects.select_for_update().get(pk=profile.pk)
    wipe_profile_data(profile)
    warnings = []

    firm_ids, group_ids, bank_ids, matter_ids, memo_ids, payment_ids = {}, {}, {}, {}, {}, {}
    matter_scope = {}  # new matter id -> (new firm id, new group id), for the denormalised memo columns

    # Firms
    loader = _Loader(Firm, firm_ids)
    for number, v in _rows(workbook, "Firms"):
        status = _text(v["status"]).strip().lower()
        loader.add(
            _key(v["id"]),
            Firm(
                profile=profile,
                name=_required_name(v["name"], "Firms", number),
                status="archived" if status == "archived" else "active",
                notes=_text(v["notes"]),
            ),
        )
    loader.flush()
    n_firms = loader.count

    # Partners (groups)
    loader = _Loader(Group, group_ids)
    for number, v in _rows(workbook, "Partners"):
        loader.add(
            _key(v["id"]),
            Group(
                profile=profile,
                firm_id=_ref(firm_ids, v["firm_id"], "Partners", number, "firm"),
                name=_required_name(v["name"], "Partners", number),
            ),
        )
    loader.flush()
    n_groups = loader.count

    # Matters
    loader = _Loader(Matter, matter_ids, hook=lambda obj, _extra: matter_scope.__setitem__(obj.pk, (obj.firm_id, obj.group_id)))
    for number, v in _rows(workbook, "Matters"):
        loader.add(
            _key(v["id"]),
            Matter(
                profile=profile,
                firm_id=_ref(firm_ids, v["firm_id"], "Matters", number, "firm"),
                group_id=_ref(group_ids, v["partner_id"], "Matters", number, "group"),
                name=_required_name(v["name"], "Matters", number),
                is_archived=_bool(v["is_archived"]),
                short_name=_text(v["short_name"]),
                notes=_text(v["notes"]),
                addressee_line1=_text(v["addressee_line1"]),
                addressee_line2=_text(v["addressee_line2"]),
                court_name=_text(v["court_name"]),
                client=_text(v["client"]),
                additional_details_left=_text(v["additional_details_left"]),
                additional_details_right=_text(v["additional_details_right"]),
                plaintiff_name=_text(v["plaintiff_name"]),
                plaintiff_type=_text(v["plaintiff_type"]),
                defendant_name=_text(v["defendant_name"]),
                defendant_type=_text(v["defendant_type"]),
                addressee_use_firm_name=_bool(v["addressee_use_firm_name"]),
            ),
        )
    loader.flush()
    n_matters = loader.count

    # Bank accounts
    loader = _Loader(BankAccount, bank_ids)
    for number, v in _rows(workbook, "BankAccounts"):
        loader.add(
            _key(v["id"]),
            BankAccount(profile=profile, name=_required_name(v["name"], "BankAccounts", number)),
        )
    loader.flush()
    n_banks = loader.count

    # Memos: firm and group come from the matter (R-DATA-5); total_fees from the single fee rule.
    web_found = _web_settings_found(workbook)
    signature_flags, signature_default = _memo_flags(workbook, web_found)
    loader = _Loader(Memo, memo_ids)
    invalid_dates = 0
    for number, v in _rows(workbook, "Memos"):
        matter_id = _ref(matter_ids, v["matter_id"], "Memos", number, "matter")
        firm_id, group_id = matter_scope[matter_id]
        memo_date = _date(v["date"])
        if memo_date is None and v["date"] is not None:
            invalid_dates += 1
        financial_year = _text(v["financial_year"]).strip()
        if not financial_year and memo_date is not None:
            financial_year = derive_financial_year(memo_date)
        memo = Memo(
            profile=profile,
            memo_number=_text_or_none(v["memo_number"]),
            financial_year=financial_year,
            seq=_int(v["seq"], "Memos", number, "seq"),
            date=memo_date,
            matter_id=matter_id,
            firm_id=firm_id,
            group_id=group_id,
            addressee_line1=_text(v["addressee_line1"]),
            addressee_line2=_text(v["addressee_line2"]),
            court_name=_text(v["court_name"]),
            additional_details_left=_text(v["additional_details_left"]),
            additional_details_right=_text(v["additional_details_right"]),
            plaintiff_name=_text(v["plaintiff_name"]),
            plaintiff_type=_text(v["plaintiff_type"]),
            defendant_name=_text(v["defendant_name"]),
            defendant_type=_text(v["defendant_type"]),
            client=_text(v["client"]),
            num_appearances=_int(v["num_appearances"], "Memos", number, "num_appearances"),
            dates_of_appearances=_text(v["dates_of_appearances"]),
            fees_per_appearance=_dec(v["fees_per_appearance"], "Memos", number, "fees_per_appearance"),
            num_conferences=_int(v["num_conferences"], "Memos", number, "num_conferences"),
            dates_of_conferences=_text(v["dates_of_conferences"]),
            fees_per_conference=_dec(v["fees_per_conference"], "Memos", number, "fees_per_conference"),
            misc_drafting_description=_text(v["misc_drafting_description"]),
            fees_misc_drafting=_dec(v["fees_misc_drafting"], "Memos", number, "fees_misc_drafting"),
            num_drafts=_int(v["num_drafts"], "Memos", number, "num_drafts"),
            written_off=_bool(v["written_off"]),
            is_draft=_bool(v["is_draft"]),
            include_signature=signature_flags.get(_key(v["id"]), signature_default),
            custom_fees_appearances=_dec(v["custom_fees_appearances"], "Memos", number, "custom_fees_appearances", True),
            custom_fees_conferences=_dec(v["custom_fees_conferences"], "Memos", number, "custom_fees_conferences", True),
            custom_fees_misc=_dec(v["custom_fees_misc"], "Memos", number, "custom_fees_misc", True),
            custom_total_fees=_dec(v["custom_total_fees"], "Memos", number, "custom_total_fees", True),
        )
        memo.total_fees = memo_fees.resolve_memo_fees(memo).total_fees
        loader.add(_key(v["id"]), memo)
    loader.flush()
    n_memos = loader.count
    if invalid_dates:
        warnings.append(f"{invalid_dates} memo date(s) were not valid dates and were left blank.")

    # Payments; the legacy payments.memo_id is kept (by new ids) for the allocation backfill.
    links = {}

    def remember_link(obj, memo_id):
        if memo_id is not None:
            links[obj.pk] = memo_id

    loader = _Loader(Payment, payment_ids, hook=remember_link)
    unlinked = 0
    for number, v in _rows(workbook, "Payments"):
        paid_on = _date(v["date_of_payment"])
        if paid_on is None:
            raise _fail(f'Sheet "Payments" row {number}: the payment date {v["date_of_payment"]!r} is not valid')
        bank_key = _key(v["bank_account_id"])
        legacy_key = _key(v["memo_id"])
        legacy_memo = memo_ids.get(legacy_key) if legacy_key is not None else None
        if legacy_key is not None and legacy_memo is None:
            unlinked += 1
        loader.add(
            _key(v["id"]),
            Payment(
                profile=profile,
                amount=_dec(v["amount"], "Payments", number, "amount"),
                tds_rate=_dec(v["tds_rate"], "Payments", number, "tds_rate"),
                auto_tds=_bool(v["auto_tds"], True),
                tds_amount=_dec(v["tds_amount"], "Payments", number, "tds_amount"),
                date_of_payment=paid_on,
                payee=_text(v["payee"]),
                bank_account_id=bank_ids.get(bank_key) if bank_key is not None else None,
                payment_mode=_text(v["payment_mode"]),
                payment_details=_text(v["payment_details"]),
            ),
            extra=legacy_memo,
        )
    loader.flush()
    n_payments = loader.count
    if unlinked:
        warnings.append(f"{unlinked} payment(s) pointed at a memo that is not in the file and were left unassigned.")

    # Allocations, then the legacy backfill for payments that have none.
    has_allocation = set()
    loader = _Loader(Allocation)
    for number, v in _rows(workbook, "PaymentAllocations"):
        payment_id = _ref(payment_ids, v["payment_id"], "PaymentAllocations", number, "payment")
        has_allocation.add(payment_id)
        loader.add(
            None,
            Allocation(
                payment_id=payment_id,
                memo_id=_ref(memo_ids, v["memo_id"], "PaymentAllocations", number, "memo"),
                profile=profile,
                amount=_dec(v["amount"], "PaymentAllocations", number, "amount"),
                tds_amount=_dec(v["tds_amount"], "PaymentAllocations", number, "tds_amount"),
            ),
        )
    loader.flush()
    n_allocations = loader.count
    backfilled = _backfill_allocations(profile, links, has_allocation)
    links.clear()
    has_allocation.clear()

    # Stored paid columns from the allocations (the sole writer).
    _recompute_paid_all(profile)

    # Period adjustments
    loader = _Loader(PeriodAdjustment)
    for number, v in _rows(workbook, "PeriodAdjustments"):
        loader.add(
            None,
            PeriodAdjustment(
                profile=profile,
                financial_year=_text(v["financial_year"]).strip(),
                month=_int(v["month"], "PeriodAdjustments", number, "month"),
                working_days=_int(v["working_days"], "PeriodAdjustments", number, "working_days"),
                extra_appearances=_int(v["extra_appearances"], "PeriodAdjustments", number, "extra_appearances"),
                extra_conferences=_int(v["extra_conferences"], "PeriodAdjustments", number, "extra_conferences"),
                extra_drafts=_int(v["extra_drafts"], "PeriodAdjustments", number, "extra_drafts"),
                ov_appearances=_dec(v["ov_appearances"], "PeriodAdjustments", number, "ov_appearances", True),
                ov_conferences=_dec(v["ov_conferences"], "PeriodAdjustments", number, "ov_conferences", True),
                ov_drafts=_dec(v["ov_drafts"], "PeriodAdjustments", number, "ov_drafts", True),
                ov_billed=_dec(v["ov_billed"], "PeriodAdjustments", number, "ov_billed", True),
                ov_received=_dec(v["ov_received"], "PeriodAdjustments", number, "ov_received", True),
                ov_received_plus_tds=_dec(
                    v["ov_received_plus_tds"], "PeriodAdjustments", number, "ov_received_plus_tds", True
                ),
            ),
        )
    loader.flush()
    n_adjustments = loader.count

    # Saved views
    loader = _Loader(SavedView)
    for number, v in _rows(workbook, "SavedViews"):
        firm_key = _key(v["firm_id"])
        loader.add(
            None,
            SavedView(
                profile=profile,
                name=_required_name(v["name"], "SavedViews", number),
                measure=_text(v["measure"]),
                row_dim=_text(v["row_dim"]),
                col_dim=_text(v["col_dim"]),
                firm_id=firm_ids.get(firm_key) if firm_key is not None else None,
                from_fy=_text(v["from_fy"]),
                to_fy=_text(v["to_fy"]),
            ),
        )
    loader.flush()
    n_views = loader.count

    n_sequences = _rebuild_sequences(profile)

    # Settings: reset to defaults, then the desktop row, then the web-only sheet.
    settings = reset_settings(profile)
    for number, v in _read_sheet(workbook, "Settings", _SETTINGS_SHEET_COLUMNS, _MIN_COLUMNS["Settings"]):
        _apply_settings_row(settings, v, number)
        break
    web_keys = _apply_web_settings(settings, workbook, web_found)
    settings.save()

    touch(profile)  # data_version bump and StatsCache purge

    counts = {
        "firms": n_firms,
        "groups": n_groups,
        "matters": n_matters,
        "bank_accounts": n_banks,
        "memos": n_memos,
        "payments": n_payments,
        "allocations": n_allocations,
        "allocations_backfilled": backfilled,
        "period_adjustments": n_adjustments,
        "saved_views": n_views,
        "number_sequences": n_sequences,
        "web_settings": web_keys,
    }
    rows_imported = (
        n_firms + n_groups + n_matters + n_banks + n_memos + n_payments + n_allocations
        + n_adjustments + n_views
    )
    return {"counts": counts, "rows_imported": rows_imported, "warnings": warnings}


def restore_workbook(profile, source, confirmation, user=None, backup_func=None):
    """Replace ALL of ``profile``'s Fee Register data with the ``.xlsx`` at ``source``.

    ``source`` is a path or a seekable binary file object (an uploaded file works). See the module
    docstring for the order of work and the result. ``backup_func(kind, user)`` defaults to the suite
    ``create_backup`` and is called as ``("pre_restore", user)``; a test may pass a stub.
    """
    if (confirmation or "").strip() != RESTORE_CONFIRMATION:
        raise FeesError(
            "INVALID_CONFIRMATION",
            f'Type "{RESTORE_CONFIRMATION}" exactly to confirm. Nothing was changed.',
        )
    _check_source(source)
    backup_func = backup_func or _default_backup
    with heavy_operation("excel_restore"):
        with _open_workbook(source) as workbook:
            try:
                backup = backup_func("pre_restore", user)
            except Exception as exc:
                logger.exception("Safety backup before Excel restore failed")
                raise _fail(f"The safety backup could not be made, so nothing was changed. ({exc})") from exc
            try:
                with transaction.atomic():
                    result = _load(profile, workbook)
            except FeesError:
                raise
            except Exception as exc:
                logger.exception("Excel restore failed and was rolled back")
                raise _fail(f"The backup could not be restored and nothing was changed. ({exc})") from exc
    report = integrity.check_profile(profile)
    result["fees_check"] = {
        "ok": report.ok,
        "memos_checked": report.memos_checked,
        "mismatches": len(report.mismatches),
    }
    result["backup_id"] = getattr(backup, "pk", None)
    return result
