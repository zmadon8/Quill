"""Excel backup export and the sheet/column contract shared with restore (design 7.1, R-BK-1, B 11).

``export_workbook(profile)`` writes the ten desktop sheets, in order, with the exact desktop column
lists, plus the extra sheet ``WebSettings`` (web-only keys), so the desktop Fee Register can read a web
backup (decision D6). It streams: ``openpyxl.Workbook(write_only=True)`` and
``queryset.values_list(...).iterator(chunk_size=500)``, saved into a temporary file that is returned
rewound (R-NFR-2). ``openpyxl`` is imported inside the function so it is not loaded at startup.

The contract constants below are copied from the desktop app:

* ``TABLES`` from ``docs/fee_register_port/reference/source/src/services/backupService.ts`` (``TABLES``);
* ``SETTINGS_COLUMNS`` from ``.../src/db/settingsColumns.ts`` (``SETTINGS_COLUMNS``, with
  ``settingsBackupColumns()`` and ``settingsBackupDefaults()`` derived the same way).

Transformations (design 7.1): ids and foreign keys are the web ids of this file; the vestigial columns
``matters.is_custom``, ``memos.tds_rate`` and ``payments.memo_amount`` are written as 0 (they are NOT
NULL on the desktop); ``payments.tds_rate`` is the real rate; ``payments.memo_id`` is the memo id when
the payment has exactly one allocation, else empty; timestamps are ``YYYY-MM-DD HH:MM:SS`` in UTC and
never empty; booleans are 0 or 1; dates are ISO text; money is a number. ``payment_details`` is in the
backup (it is the full backup, R-PAY-5). Electron-only settings are written at their desktop defaults.
Web-only settings go to the ``WebSettings`` sheet (``key``, ``value``), including the five memo text
defaults (R-SET-7), ``memo_signature_default``, ``list_default_filter`` and ``items_per_page`` (an older file without these keys
restores to the defaults). A second web-only sheet, ``WebMemoFlags`` (``memo_id``, ``memo_number``,
``include_signature``), carries the per-memo signature flag; the desktop ``Memos`` sheet gets NO new column
(it is a contract). An older file without ``WebMemoFlags`` restores every memo with the signature default
of the file's ``WebSettings`` (off when absent). The Word template bytes and the signature image bytes (``WordTemplate``) are NEVER
written to the ``.xlsx`` (they travel in the suite backup only, design 7.4).
"""
import datetime
import tempfile

from django.db.models import Count, Min

from fees.models import (
    Allocation,
    BankAccount,
    FeesSettings,
    Firm,
    Group,
    Matter,
    Memo,
    PeriodAdjustment,
    Payment,
    SavedView,
)

__all__ = [
    "TABLES",
    "SHEET_ORDER",
    "OPTIONAL_SHEETS",
    "WEB_SETTINGS_SHEET",
    "WEB_SETTINGS_HEADERS",
    "WEB_MEMO_FLAGS_SHEET",
    "WEB_MEMO_FLAGS_HEADERS",
    "SETTINGS_COLUMNS",
    "ELECTRON_ONLY_DEFAULTS",
    "NOT_NULL_DEFAULTS",
    "WEB_SETTINGS_KEYS",
    "MEMO_TEXT_DEFAULT_KEYS",
    "settings_backup_columns",
    "settings_backup_defaults",
    "export_workbook",
]

# ---------------------------------------------------------------------------
# The contract (copied from backupService.ts TABLES, parents first for insert)
# ---------------------------------------------------------------------------

#: ``(sheet name, column list)`` in dependency order. The ``Settings`` entry is filled from
#: ``settings_backup_columns()`` below (the desktop derives it from the same catalogue).
_SETTINGS_SHEET = "Settings"

#: The settings catalogue copied from ``settingsColumns.ts``: ``(column, kind, default)``. ``default`` is
#: ``None`` for a nullable column (no NOT NULL / DEFAULT on the desktop). Kinds: text, int, real, bool.
SETTINGS_COLUMNS = [
    ("default_fees_per_appearance", "real", 0),
    ("default_fees_per_conference", "real", 0),
    ("default_fees_misc_drafting", "real", 0),
    ("default_additional_details_left", "text", None),
    ("default_additional_details_right", "text", None),
    ("default_court_name", "text", None),
    ("default_tds_rate", "real", 10),
    ("overdue_days", "int", 0),
    ("default_tab", "text", "memos"),
    ("auto_backup_frequency", "text", "off"),
    ("auto_backup_dir", "text", None),
    ("last_auto_backup", "text", None),
    ("word_template_path", "text", None),
    ("initial_financial_year", "text", "2026-27"),
    ("memos_start_year", "text", "2026-27"),
    ("feebook_start_year", "text", "2026-27"),
    ("money_unit", "text", "full"),
    ("money_suffix_thousands", "text", "k"),
    ("money_suffix_lac", "text", "lac"),
    ("money_suffix_crore", "text", "cr"),
    ("hide_payment_when_paid", "bool", False),
    ("default_lines_enabled", "bool", True),
    ("default_payment_amount", "text", "zero"),
    ("show_status_dots", "bool", True),
    ("zoom_factor", "real", 1),
    ("dashboard_kpis", "text", ""),
    ("backup_close_enabled", "bool", False),
    ("backup_close_dir", "text", None),
    ("backup_daily_enabled", "bool", False),
    ("backup_daily_dir", "text", None),
    ("last_backup_daily", "text", None),
    ("backup_weekly_enabled", "bool", False),
    ("backup_weekly_dir", "text", None),
    ("last_backup_weekly", "text", None),
    ("backup_monthly_enabled", "bool", False),
    ("backup_monthly_dir", "text", None),
    ("last_backup_monthly", "text", None),
    ("backup_retention", "int", 30),
    ("backup_migrated", "bool", False),
]


def settings_backup_columns():
    """Column names of the ``Settings`` sheet: ``id``, every catalogue column, ``updated_at``."""
    return ["id"] + [name for name, _kind, _default in SETTINGS_COLUMNS] + ["updated_at"]


def settings_backup_defaults():
    """Restore defaults for NOT NULL settings columns (``settingsBackupDefaults``), bools as 0 or 1."""
    out = {}
    for name, _kind, default in SETTINGS_COLUMNS:
        if default is None:
            continue
        out[name] = int(default) if isinstance(default, bool) else default
    return out


TABLES = [
    ("Firms", ["id", "name", "status", "notes", "created_at", "updated_at"]),
    ("Partners", ["id", "firm_id", "name", "created_at"]),
    (
        "Matters",
        [
            "id", "firm_id", "partner_id", "name", "is_archived", "is_custom",
            "addressee_line1", "addressee_line2", "addressee_use_firm_name", "court_name", "client",
            "additional_details_left", "additional_details_right", "plaintiff_name", "plaintiff_type",
            "defendant_name", "defendant_type", "notes", "short_name", "created_at", "updated_at",
        ],
    ),
    ("BankAccounts", ["id", "name", "created_at"]),
    (
        "Memos",
        [
            "id", "memo_number", "financial_year", "seq", "date", "matter_id", "firm_id", "partner_id",
            "addressee_line1", "addressee_line2", "court_name", "additional_details_left",
            "additional_details_right", "plaintiff_name", "plaintiff_type", "defendant_name",
            "defendant_type", "client", "num_appearances", "dates_of_appearances",
            "fees_per_appearance", "num_conferences", "dates_of_conferences", "fees_per_conference",
            "misc_drafting_description", "fees_misc_drafting", "num_drafts", "tds_rate", "written_off",
            "is_draft", "custom_fees_appearances", "custom_fees_conferences", "custom_fees_misc",
            "custom_total_fees", "created_at", "updated_at",
        ],
    ),
    (
        "Payments",
        [
            "id", "memo_id", "amount", "tds_rate", "auto_tds", "tds_amount", "memo_amount",
            "date_of_payment", "payee", "bank_account_id", "payment_details", "payment_mode",
            "created_at", "updated_at",
        ],
    ),
    ("PaymentAllocations", ["id", "payment_id", "memo_id", "amount", "tds_amount", "created_at"]),
    (
        "PeriodAdjustments",
        [
            "id", "financial_year", "month", "working_days",
            "extra_appearances", "extra_conferences", "extra_drafts",
            "ov_appearances", "ov_conferences", "ov_drafts", "ov_billed", "ov_received",
            "ov_received_plus_tds", "updated_at",
        ],
    ),
    (
        "SavedViews",
        ["id", "name", "measure", "row_dim", "col_dim", "firm_id", "from_fy", "to_fy", "created_at"],
    ),
    (_SETTINGS_SHEET, settings_backup_columns()),
]

#: Sheet names in file order (the ten desktop sheets).
SHEET_ORDER = [sheet for sheet, _columns in TABLES]

#: Sheets that an older desktop backup may lack (``OPTIONAL_SHEETS`` in ``restoreFromBuffer``), plus the
#: web-only extra sheet. Every other sheet is required.
OPTIONAL_SHEETS = frozenset(["PaymentAllocations", "PeriodAdjustments", "SavedViews", "WebSettings"])

#: The extra web-only sheet and its header row.
WEB_SETTINGS_SHEET = "WebSettings"
WEB_SETTINGS_HEADERS = ["key", "value"]

#: The per-memo web-only flags sheet (not in ``OPTIONAL_SHEETS``: it is never a required desktop sheet).
WEB_MEMO_FLAGS_SHEET = "WebMemoFlags"
WEB_MEMO_FLAGS_HEADERS = ["memo_id", "memo_number", "include_signature"]

#: The five memo text defaults (R-SET-7) carried by ``WebSettings``.
MEMO_TEXT_DEFAULT_KEYS = [
    "memo_default_name",
    "memo_default_designation",
    "memo_default_address",
    "memo_default_bank_details",
    "memo_default_pan",
]

#: Every key written to ``WebSettings``, in order (the web-only settings, design 7.1).
WEB_SETTINGS_KEYS = [
    "export_owner_name",
    "memo_filename_pattern",
    "statistics_enabled",
    "dashboard_kpis_enabled",
    "dashboard_enabled",
    "show_bank",
] + MEMO_TEXT_DEFAULT_KEYS + [
    "memo_signature_default",
    "list_default_filter",
    "items_per_page",
]

#: NOT NULL columns with a default; a blank or missing value takes this on restore (ported from
#: ``NOT_NULL_INT_DEFAULTS`` in ``readSheetRows``). The settings defaults are merged in from
#: ``settings_backup_defaults()``.
NOT_NULL_DEFAULTS = dict(
    {
        "is_archived": 0,
        "addressee_use_firm_name": 0,
        "auto_tds": 1,
        "num_drafts": 0,
        "written_off": 0,
        "is_draft": 0,
        "working_days": 0,
        "extra_appearances": 0,
        "extra_conferences": 0,
        "extra_drafts": 0,
    },
    **settings_backup_defaults(),
)

#: Electron-only settings written at desktop defaults (design 7.1); ``None`` is an empty cell.
ELECTRON_ONLY_DEFAULTS = {
    # No longer settings here: the columns stay in the file for the desktop app, written empty; a restore ignores them.
    "default_additional_details_left": None,
    "default_additional_details_right": None,
    "auto_backup_frequency": "off",
    "auto_backup_dir": None,
    "last_auto_backup": None,
    "word_template_path": None,
    "zoom_factor": 1,
    "backup_close_enabled": 0,
    "backup_close_dir": None,
    "backup_daily_enabled": 0,
    "backup_daily_dir": None,
    "last_backup_daily": None,
    "backup_weekly_enabled": 0,
    "backup_weekly_dir": None,
    "last_backup_weekly": None,
    "backup_monthly_enabled": 0,
    "backup_monthly_dir": None,
    "last_backup_monthly": None,
    "backup_retention": 30,
    "backup_migrated": 1,
}

_CHUNK = 500


# ---------------------------------------------------------------------------
# Cell converters
# ---------------------------------------------------------------------------

def _ts(value):
    """``YYYY-MM-DD HH:MM:SS`` in UTC; never empty (a missing value is "now")."""
    if value is None:
        value = datetime.datetime.now(datetime.timezone.utc)
    if value.tzinfo is not None:
        value = value.astimezone(datetime.timezone.utc)
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _date(value):
    return None if value is None else value.isoformat()[:10]


def _bool(value):
    return 1 if value else 0


def _money(value):
    return None if value is None else float(value)


def _same(value):
    return value


def _single_memo(count, memo_id):
    """``payments.memo_id``: the memo id when the payment has exactly one allocation, else empty."""
    return memo_id if count == 1 else None


# Column specs: (header, source fields, converter). The converter takes the source values in order.
def _c(header, field=None, conv=_same):
    return (header, (field if field is not None else header,), conv)


def _const(header, value):
    return (header, (), lambda: value)


_FIRMS = [
    _c("id"), _c("name"), _c("status"), _c("notes"),
    _c("created_at", conv=_ts), _c("updated_at", conv=_ts),
]
_PARTNERS = [_c("id"), _c("firm_id"), _c("name"), _c("created_at", conv=_ts)]
_MATTERS = [
    _c("id"), _c("firm_id"), _c("partner_id", "group_id"), _c("name"),
    _c("is_archived", conv=_bool), _const("is_custom", 0),
    _c("addressee_line1"), _c("addressee_line2"),
    _c("addressee_use_firm_name", conv=_bool), _c("court_name"), _c("client"),
    _c("additional_details_left"), _c("additional_details_right"),
    _c("plaintiff_name"), _c("plaintiff_type"), _c("defendant_name"), _c("defendant_type"),
    _c("notes"), _c("short_name"),
    _c("created_at", conv=_ts), _c("updated_at", conv=_ts),
]
_BANKS = [_c("id"), _c("name"), _c("created_at", conv=_ts)]
_MEMOS = [
    _c("id"), _c("memo_number"), _c("financial_year"), _c("seq"), _c("date", conv=_date),
    _c("matter_id"), _c("firm_id"), _c("partner_id", "group_id"),
    _c("addressee_line1"), _c("addressee_line2"), _c("court_name"),
    _c("additional_details_left"), _c("additional_details_right"),
    _c("plaintiff_name"), _c("plaintiff_type"), _c("defendant_name"), _c("defendant_type"),
    _c("client"),
    _c("num_appearances"), _c("dates_of_appearances"), _c("fees_per_appearance", conv=_money),
    _c("num_conferences"), _c("dates_of_conferences"), _c("fees_per_conference", conv=_money),
    _c("misc_drafting_description"), _c("fees_misc_drafting", conv=_money),
    _c("num_drafts"), _const("tds_rate", 0),
    _c("written_off", conv=_bool), _c("is_draft", conv=_bool),
    _c("custom_fees_appearances", conv=_money), _c("custom_fees_conferences", conv=_money),
    _c("custom_fees_misc", conv=_money), _c("custom_total_fees", conv=_money),
    _c("created_at", conv=_ts), _c("updated_at", conv=_ts),
]
_PAYMENTS = [
    _c("id"),
    ("memo_id", ("alloc_count", "alloc_memo"), _single_memo),
    _c("amount", conv=_money), _c("tds_rate", conv=_money), _c("auto_tds", conv=_bool),
    _c("tds_amount", conv=_money), _const("memo_amount", 0),
    _c("date_of_payment", conv=_date), _c("payee"), _c("bank_account_id"),
    _c("payment_details"), _c("payment_mode"),
    _c("created_at", conv=_ts), _c("updated_at", conv=_ts),
]
_ALLOCATIONS = [
    _c("id"), _c("payment_id"), _c("memo_id"),
    _c("amount", conv=_money), _c("tds_amount", conv=_money), _c("created_at", conv=_ts),
]
_ADJUSTMENTS = [
    _c("id"), _c("financial_year"), _c("month"), _c("working_days"),
    _c("extra_appearances"), _c("extra_conferences"), _c("extra_drafts"),
    _c("ov_appearances", conv=_money), _c("ov_conferences", conv=_money), _c("ov_drafts", conv=_money),
    _c("ov_billed", conv=_money), _c("ov_received", conv=_money),
    _c("ov_received_plus_tds", conv=_money), _c("updated_at", conv=_ts),
]
_VIEWS = [
    _c("id"), _c("name"), _c("measure"), _c("row_dim"), _c("col_dim"), _c("firm_id"),
    _c("from_fy"), _c("to_fy"), _c("created_at", conv=_ts),
]

_SHEET_SPECS = {
    "Firms": _FIRMS,
    "Partners": _PARTNERS,
    "Matters": _MATTERS,
    "BankAccounts": _BANKS,
    "Memos": _MEMOS,
    "Payments": _PAYMENTS,
    "PaymentAllocations": _ALLOCATIONS,
    "PeriodAdjustments": _ADJUSTMENTS,
    "SavedViews": _VIEWS,
}


def _queryset(sheet, profile):
    """The profile's rows for ``sheet`` in id order."""
    if sheet == "Firms":
        return Firm.objects.filter(profile=profile)
    if sheet == "Partners":
        return Group.objects.filter(profile=profile)
    if sheet == "Matters":
        return Matter.objects.filter(profile=profile)
    if sheet == "BankAccounts":
        return BankAccount.objects.filter(profile=profile)
    if sheet == "Memos":
        return Memo.objects.filter(profile=profile)
    if sheet == "Payments":
        return Payment.objects.filter(profile=profile).annotate(
            alloc_count=Count("allocations"), alloc_memo=Min("allocations__memo_id")
        )
    if sheet == "PaymentAllocations":
        return Allocation.objects.filter(profile=profile)
    if sheet == "PeriodAdjustments":
        return PeriodAdjustment.objects.filter(profile=profile)
    return SavedView.objects.filter(profile=profile)


def _verify_specs():
    """Module-load guard: each spec's headers equal the contract column list (cheap, no I/O)."""
    for sheet, columns in TABLES:
        if sheet in _SHEET_SPECS:
            headers = [header for header, _fields, _conv in _SHEET_SPECS[sheet]]
            if headers != columns:  # pragma: no cover - a programming error caught at import
                raise RuntimeError(f"export columns for {sheet} differ from the contract")


_verify_specs()


# ---------------------------------------------------------------------------
# Settings rows
# ---------------------------------------------------------------------------

_BOOL_SETTINGS = {name for name, kind, _d in SETTINGS_COLUMNS if kind == "bool"}


def _settings_row(settings):
    """The single ``Settings`` data row: model values, Electron-only columns at defaults."""
    row = [1]
    for name, _kind, _default in SETTINGS_COLUMNS:
        if name in ELECTRON_ONLY_DEFAULTS:
            row.append(ELECTRON_ONLY_DEFAULTS[name])
            continue
        value = getattr(settings, name)
        if name in _BOOL_SETTINGS:
            row.append(_bool(value))
        elif isinstance(value, (int, float)) or hasattr(value, "quantize"):
            row.append(float(value) if hasattr(value, "quantize") else value)
        else:
            row.append(value)
    row.append(_ts(getattr(settings, "updated_at", None)))
    return row


def _web_settings_rows(settings):
    """``(key, value)`` rows of the ``WebSettings`` sheet: web-only keys, booleans as 0 or 1."""
    rows = []
    for key in WEB_SETTINGS_KEYS:
        value = getattr(settings, key)
        rows.append([key, _bool(value) if isinstance(value, bool) else value])
    return rows


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_workbook(profile):
    """Write ``profile``'s Fee Register to an ``.xlsx`` and return it as a rewound temporary file.

    The returned object is a binary ``tempfile.TemporaryFile`` positioned at 0; the caller streams it
    (for example in a ``FileResponse``) and closes it, which deletes it. Rows are streamed from the
    database in chunks of 500 and written with ``openpyxl`` ``write_only`` mode, so memory stays flat
    whatever the data size (R-NFR-2, gate: under 12 MB on the planning dataset).
    """
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

    workbook = Workbook(write_only=True)

    def clean(sheet, value):
        """Make a value safe for a cell: no control characters, and text is never a formula."""
        if isinstance(value, str):
            value = ILLEGAL_CHARACTERS_RE.sub("", value)
            if value.startswith("="):
                cell = WriteOnlyCell(sheet, value=value)
                cell.data_type = "s"
                return cell
        return value

    def write_rows(sheet, headers, rows):
        sheet.append(list(headers))
        for row in rows:
            sheet.append([clean(sheet, value) for value in row])

    for sheet_name, columns in TABLES:
        sheet = workbook.create_sheet(sheet_name)
        if sheet_name == _SETTINGS_SHEET:
            settings = FeesSettings.objects.filter(profile=profile).first() or FeesSettings(profile=profile)
            write_rows(sheet, columns, [_settings_row(settings)])
            continue
        spec = _SHEET_SPECS[sheet_name]
        fields = []
        for _header, source, _conv in spec:
            for name in source:
                if name not in fields:
                    fields.append(name)
        index = {name: i for i, name in enumerate(fields)}
        plan = [(tuple(index[n] for n in source), conv) for _header, source, conv in spec]
        queryset = _queryset(sheet_name, profile).order_by("pk").values_list(*fields)

        def rows(queryset=queryset, plan=plan):
            for values in queryset.iterator(chunk_size=_CHUNK):
                yield [conv(*[values[i] for i in positions]) for positions, conv in plan]

        write_rows(sheet, columns, rows())

    web_sheet = workbook.create_sheet(WEB_SETTINGS_SHEET)
    settings = FeesSettings.objects.filter(profile=profile).first() or FeesSettings(profile=profile)
    write_rows(web_sheet, WEB_SETTINGS_HEADERS, _web_settings_rows(settings))

    flags_sheet = workbook.create_sheet(WEB_MEMO_FLAGS_SHEET)
    flag_rows = (
        [pk, number, _bool(include)]
        for pk, number, include in Memo.objects.filter(profile=profile)
        .order_by("pk")
        .values_list("pk", "memo_number", "include_signature")
        .iterator(chunk_size=_CHUNK)
    )
    write_rows(flags_sheet, WEB_MEMO_FLAGS_HEADERS, flag_rows)

    out = tempfile.TemporaryFile()
    workbook.save(out)
    out.seek(0)
    return out
