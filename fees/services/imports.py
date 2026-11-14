"""Memo import from a spreadsheet (design section 7, R-IM-1 to R-IM-3, porting brief section 8).

Ports ``importService.importMemos`` plus the inspect and parse half of ``electron/ipc/import.ts`` and the
mapping guess of ``ImportMemosDialog.tsx``. Services only: no view or URL lives here (Phase 7).

Public API
----------
``inspect_file(source, kind=None) -> dict``
    Step 1. Streams the file and returns ``{"headers", "sample_rows", "row_count", "mapping"}``: the trimmed
    headers, the first 5 data rows, the number of data rows and the guessed mapping. Raises
    ``FeesError("IMPORT_FAILED")`` when the file is too big, unreadable, has too many rows or columns, or
    lacks a header plus at least one data row. Takes the heavy lock.

``run_import(profile, source, mapping, auto_number=False, kind=None) -> dict``
    Step 2. Streams the file once and imports every row in ONE transaction while holding the heavy lock
    ``heavy_operation("excel_import")`` (``Busy`` propagates). Returns the result described below.

``import_memos(profile, rows, mapping, auto_number=False) -> dict``
    The row engine behind ``run_import`` (the port of ``importMemos``). ``rows`` is any iterable of dicts
    ``{header: text}``; it is consumed one row at a time. Needs the caller to hold the heavy lock for a
    large file; ``run_import`` does.

``iter_rows(source, kind=None)``
    A generator of rows (lists of trimmed strings) from an ``.xlsx`` (``openpyxl`` read-only, first sheet,
    cached formula results) or a ``.csv`` (UTF-8, comma, RFC quoting). The first row is the header. Blank
    rows are skipped. Size, row and column caps are enforced here. The file is never read whole: the csv is
    decoded chunk by chunk and handed to ``csv.reader`` line by line, and ``openpyxl`` streams the sheet.

``guess_mapping(headers)``, ``guess_field(field, headers)``, ``parse_number(text)``, ``parse_date(text)``
    The stdlib-only helpers (no Django needed to call them).

The mapping is ``{field_id: header or None}``. Field ids are ``IMPORT_FIELDS`` (snake_case of the original
camelCase names): ``firm_name`` and ``matter_name`` are required.

Result: ``{"firms_created", "matters_created", "memos_created", "payments_created", "rows_processed",
"warnings", "warnings_total"}``. ``warnings`` keeps the first ``MAX_WARNINGS``; ``warnings_total`` counts all.

Rules kept from the original
----------------------------
* Row number is index + 2 over the non-blank rows (the header is row 1).
* No de-duplication: importing a file twice creates its memos and payments twice.
* Payment rows sharing the exact same non-blank ``payment_group`` become ONE payment split across their
  memos (amount and TDS are the sums, date and payee come from the first member). A group of one, and
  every ungrouped row, is a single-memo payment.
* ``custom_total_fees`` is the Total column when that column is mapped (it overrides the breakup).

Deviations, all deliberate
--------------------------
* Impossible dates (``31/02/2026``, ``2026-02-30``) are rejected with a warning and read as blank.
* A formula cell reads as its cached result (``data_only``); the original stringified the formula.
* Memo numbers (owner decision 5). A number of the automatic shape ``YYYY-YY/N`` is KEPT as a real auto
  number (``seq = N``) when its year part equals the memo date's financial year and it is unused; otherwise
  the row is skipped with a ``Row N`` warning. Any other text is a custom number (``seq = 0``). The counter
  of each financial year ends at ``max(last_seq, highest kept N)``; gaps are never filled.
* Two optional columns. ``numbering``: ``Auto`` (next automatic number, number text ignored with a warning,
  needs a valid date or the row is a draft), ``Custom`` (store the text as a custom number even when it looks
  automatic; such a value is refused for the current or a future financial year, because the counter would
  reach it, and allowed for past years; it never moves the counter), ``Draft`` (no number). Blank decides
  from the number: automatic shape kept, other text custom, no number gives the next automatic number when
  the auto-number box is ticked and the date is valid, else a draft. ``order``: a whole number (gaps
  allowed) that sets the order in which Auto rows get numbers within a financial year; Auto rows without it
  follow the ones with it, by memo date and then file row.
* Numbering algorithm (deterministic, collision free, one transaction). When the run can allocate numbers
  (the auto-number box is ticked or ``numbering`` is mapped) the file is read TWICE. Pass 1 keeps only a
  few small values per numbered row: the set of reserved number texts (kept automatic numbers and forced
  Custom texts), the highest kept ``N`` per financial year, and one ``(fy, order, date, row)`` tuple per Auto
  row. It then locks the ``NumberSequence`` row of each year involved, reads the numbers already used in the
  database, and hands out ``base + 1``, ``base + 2`` ... in the chosen order, skipping every reserved or used
  text, where ``base = max(last_seq, highest kept N)``. The result is a ``{row: number}`` map. Pass 2 imports
  the rows in file order as before; each numbered row claims its number through ``memos.create_memo``, which
  raises the counter to ``max(last_seq, N)``. A row that fails after planning leaves a gap, never a clash.
  The file is never read whole (the upload is reopened); a one-shot iterator given to ``import_memos`` is
  buffered, which only tests do.
* Ungrouped payments are created as their row is read instead of after the last row (same result, but it
  keeps the queue small); only grouped rows are queued, as small tuples.
* ``data_version`` is bumped ONCE for the whole import (R-IM-3), although each service call stamps it.
* The default group is named with an em dash (``DEFAULT_GROUP_NAME``, written as an escape).

``openpyxl`` is imported inside functions only.
"""
import codecs
import contextlib
import csv
import datetime
import os
import re
import zipfile
from decimal import Decimal, InvalidOperation

from django.db import DataError, IntegrityError, transaction

from fees.errors import FeesError
from fees.models import FeesSettings, Firm, Group, Matter, Memo, NumberSequence
from fees.services import history, memo_fees, memo_numbers, memos, payments
from fees.services.excel_restore import MAX_UNCOMPRESSED_BYTES
from fees.services.financial_year import current_financial_year, derive_financial_year
from fees.services.heavy import Busy, heavy_operation  # noqa: F401 (Busy is part of the contract)
from fees.services.money import round2

__all__ = [
    "IMPORT_FIELDS",
    "HEAVY_NAME",
    "MAX_IMPORT_BYTES",
    "MAX_IMPORT_ROWS",
    "MAX_IMPORT_COLUMNS",
    "MAX_CELL_CHARS",
    "MAX_WARNINGS",
    "DEFAULT_GROUP_NAME",
    "guess_field",
    "guess_mapping",
    "parse_number",
    "parse_date",
    "iter_rows",
    "inspect_file",
    "import_memos",
    "run_import",
]

#: The name of the heavy-operation lock (R-NFR-6).
HEAVY_NAME = "excel_import"
#: Upload cap (R-NFR-9), checked before the file is opened.
MAX_IMPORT_BYTES = 10 * 1024 * 1024
#: Most data rows (header excluded) one import may carry.
MAX_IMPORT_ROWS = 50_000
#: Most header columns.
MAX_IMPORT_COLUMNS = 100
#: Longest text in one cell.
MAX_CELL_CHARS = 5_000
#: Warnings kept in the result (the total is still counted).
MAX_WARNINGS = 1_000
#: Name of the group made when a row has no partner (a real em dash, U+2014, written as an escape).
DEFAULT_GROUP_NAME = "\u2014"

_CSV_CHUNK = 64 * 1024
_MAX_LINE_CHARS = 1024 * 1024
#: A single money value must stay below this (the money columns hold 12 digits before the point).
_MAX_MONEY = Decimal(10) ** 10
_MAX_TOTAL = Decimal(10) ** 12
_MAX_COUNT = 1_000_000
_MAX_GROUPS_PER_FIRM = 50
_LIMITS = {"firm": 200, "group": 200, "matter": 150, "text": 300, "number": 100}

#: (field id, label, group, required), grouped as in the dialog.
IMPORT_FIELDS = (
    ("firm_name", "Firm name", "Who", True),
    ("partner_name", "Partner", "Who", False),
    ("matter_name", "Matter / case name", "Who", True),
    ("memo_number", "Memo number (blank gives a draft)", "Memo", False),
    ("date", "Memo date", "Memo", False),
    ("numbering", "Numbering (Auto, Custom or Draft)", "Memo", False),
    ("order", "Order for automatic numbers (whole number)", "Memo", False),
    ("total_fees", "Total fee (overrides breakup)", "Fees", False),
    ("num_appearances", "No. of appearances", "Fees breakup", False),
    ("fees_per_appearance", "Fee per appearance", "Fees breakup", False),
    ("num_conferences", "No. of conferences", "Fees breakup", False),
    ("fees_per_conference", "Fee per conference", "Fees breakup", False),
    ("num_drafts", "No. of drafts", "Fees breakup", False),
    ("misc_description", "Misc / drafting description", "Fees breakup", False),
    ("fees_misc", "Misc / drafting fee", "Fees breakup", False),
    ("amount_paid", "Amount already paid (net)", "Payment", False),
    ("payment_tds", "TDS on the payment", "Payment", False),
    ("payment_date", "Payment date", "Payment", False),
    ("payee", "Payee", "Payment", False),
    ("payment_group", "Payment group (same value = paid together)", "Payment", False),
    ("court_name", "Court / cause title (to Matter)", "Matter details", False),
    ("matter_client", "Client (role) (to Matter)", "Matter details", False),
    ("party_plaintiff", "Plaintiff / applicant", "Parties (optional)", False),
    ("party_defendant", "Defendant / respondent", "Parties (optional)", False),
)
_FIELD_IDS = frozenset(field[0] for field in IMPORT_FIELDS)

#: Port of the ``guess`` needles of ``ImportMemosDialog.tsx``. A needle starting with ``=`` must equal the
#: whole header (lower-cased, trimmed); any other needle matches as a substring. Needles are tried in order.
_NEEDLES = {
    "firm_name": ("=firm", "firm", "company"),
    "partner_name": ("=partner", "partner"),
    "matter_name": ("=matter name", "matter", "case", "=title"),
    "memo_number": ("=memo no.", "memo no", "memo number", "bill no", "invoice"),
    "date": ("=date", "memo date"),
    "numbering": ("=numbering", "=numbering type", "=number type"),
    "order": ("=order", "=numbering order", "=number order", "=auto order"),
    "num_appearances": ("=appearances", "no. of appearances", "num appearance", "appearance"),
    "fees_per_appearance": ("per appearance", "appearance fee", "rate"),
    "num_conferences": ("=conferences", "no. of conferences", "conference"),
    "fees_per_conference": ("per conference", "conference fee"),
    "num_drafts": ("=drafts", "no. of drafts", "=draft", "drafts", "draft"),
    "misc_description": ("misc / drafting description", "description", "particular", "narration"),
    "fees_misc": ("misc / drafting fee", "misc", "drafting"),
    "total_fees": ("=total fees", "total fee", "amount billed", "gross", "=fees"),
    "amount_paid": ("=amount paid", "amount paid", "net paid", "=paid"),
    "payment_tds": ("=payment tds", "payment tds", "tds on", "=less tds", "=tds"),
    "payment_date": ("=payment date", "payment date", "cleared", "date paid"),
    "payee": ("=payee", "payee", "received from", "payment received from"),
    "payment_group": ("=payment group", "payment group", "pmt group", "group id"),
    "party_plaintiff": ("plaintiff", "applicant", "petitioner"),
    "party_defendant": ("defendant", "respondent"),
    "court_name": ("=court / cause title", "cause title", "=court", "court", "tribunal"),
    "matter_client": ("=client", "client", "party role"),
}


def _fail(message):
    return FeesError("IMPORT_FAILED", message)


# ---------------------------------------------------------------------------
# Pure helpers: mapping guess, number and date parsing (no Django needed)
# ---------------------------------------------------------------------------

def guess_field(field, headers):
    """The best header for ``field`` by the dialog's rules, or ``None`` (case-insensitive)."""
    lowered = [header.lower().strip() for header in headers]
    for needle in _NEEDLES[field]:
        if needle.startswith("="):
            wanted = needle[1:]
            for index, header in enumerate(lowered):
                if header == wanted:
                    return headers[index]
        else:
            for index, header in enumerate(lowered):
                if needle in header:
                    return headers[index]
    return None


def guess_mapping(headers):
    """``{field id: header or None}`` for every import field."""
    return {field[0]: guess_field(field[0], headers) for field in IMPORT_FIELDS}


_NUMBER_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


def parse_number(text):
    """A ``Decimal`` from cell text: strips the rupee sign, commas and whitespace; anything else is 0."""
    if text is None:
        return Decimal(0)
    cleaned = re.sub(r"[\u20b9,\s]", "", str(text))
    if not _NUMBER_RE.match(cleaned):
        return Decimal(0)
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return Decimal(0)
    return value if value.is_finite() else Decimal(0)


_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_DAY_FIRST_RE = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$")
#: The generic last-resort formats (day first when a numeric order is ambiguous).
_GENERIC_FORMATS = (
    "%d-%m-%y", "%d/%m/%y", "%Y/%m/%d", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d-%b-%y",
    "%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y", "%a %b %d %Y",
)


def _real_date(year, month, day):
    try:
        return datetime.date(year, month, day).isoformat()
    except ValueError:
        return None


def parse_date(text):
    """``(iso, impossible)``: a real ``YYYY-MM-DD`` or ``""``, and whether a shaped date was not real.

    Order: ``YYYY-MM-DD`` prefix, then ``D/M/YYYY`` or ``D-M-YYYY`` (DAY FIRST), then a generic parse of a
    few common shapes, else blank. ``impossible`` is true when the first two shapes matched but the
    calendar rejects them (``31/02/2026``), so the caller can warn; the value is then blank.
    """
    if text is None:
        return "", False
    value = str(text).strip()
    if not value:
        return "", False
    match = _ISO_RE.match(value)
    if match:
        iso = _real_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        return (iso, False) if iso else ("", True)
    match = _DAY_FIRST_RE.match(value)
    if match:
        iso = _real_date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        return (iso, False) if iso else ("", True)
    for fmt in _GENERIC_FORMATS:
        try:
            return datetime.datetime.strptime(value, fmt).date().isoformat(), False
        except ValueError:
            continue
    return "", False


# ---------------------------------------------------------------------------
# Source checks and the streaming readers
# ---------------------------------------------------------------------------

def _source_name(source):
    if isinstance(source, (str, os.PathLike)):
        return os.fspath(source)
    name = getattr(source, "name", None)
    return name if isinstance(name, str) else None


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


def _kind_of(source, kind):
    if kind is not None:
        lowered = str(kind).lower().lstrip(".")
        if lowered in ("xlsx", "csv"):
            return lowered
        raise _fail("Only .xlsx and .csv files can be imported.")
    name = _source_name(source)
    extension = os.path.splitext(name)[1].lower() if name else ""
    if extension in (".xlsx", ".csv"):
        return extension[1:]
    raise _fail("Only .xlsx and .csv files can be imported.")


def _check_source(source, kind):
    """Kind, size and (for xlsx) zip sanity, all before the file is opened as a spreadsheet."""
    kind = _kind_of(source, kind)
    try:
        size = _source_size(source)
    except (OSError, ValueError) as exc:
        raise _fail("The file could not be read.") from exc
    if size > MAX_IMPORT_BYTES:
        raise _fail("The file is larger than 10 MB, so it was not opened.")
    if size == 0:
        raise _fail("The file is empty.")
    if kind == "xlsx":
        _rewind(source)
        try:
            with zipfile.ZipFile(source) as archive:
                total = sum(info.file_size for info in archive.infolist())
        except (zipfile.BadZipFile, OSError, ValueError, EOFError) as exc:
            raise _fail("The file could not be read as an Excel .xlsx file.") from exc
        if total > MAX_UNCOMPRESSED_BYTES:
            raise _fail("The file expands to more than 100 MB, so it was not opened.")
    _rewind(source)
    return kind


def _rewind(source):
    if hasattr(source, "seek"):
        source.seek(0)


def _cell_text(value):
    """Cell value to trimmed text. A date becomes ``YYYY-MM-DD``; a formula arrives as its cached result."""
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, datetime.datetime):
        text = value.date().isoformat()
    elif isinstance(value, (datetime.date, datetime.time)):
        text = value.isoformat()
    elif isinstance(value, int):
        text = str(value)
    elif isinstance(value, (float, Decimal)):
        try:
            number = Decimal(repr(value)) if isinstance(value, float) else value
            text = format(number, "f") if number.is_finite() else str(value)
        except InvalidOperation:
            text = str(value)
        if "." in text:
            text = text.rstrip("0").rstrip(".")
    else:
        text = str(value).strip()
    if len(text) > MAX_CELL_CHARS:
        raise _fail(f"A cell holds more than {MAX_CELL_CHARS} characters, so the file was not imported.")
    return text


def _shape_rows(raw_rows):
    """Common caps and blank-row skipping over an iterator of lists of cell texts."""
    width = None
    data_rows = 0
    for cells in raw_rows:
        if width is None:
            while cells and cells[-1] == "":
                cells = cells[:-1]
            if not cells:
                continue
            if len(cells) > MAX_IMPORT_COLUMNS:
                raise _fail(f"The file has more than {MAX_IMPORT_COLUMNS} columns, so it was not imported.")
            width = len(cells)
            yield cells
            continue
        cells = cells[:width]
        if not any(cells):
            continue
        data_rows += 1
        if data_rows > MAX_IMPORT_ROWS:
            raise _fail(f"The file has more than {MAX_IMPORT_ROWS} rows, so it was not imported.")
        yield cells


def _xlsx_cells(source):
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(source, read_only=True, data_only=True)
    except Exception as exc:
        raise _fail("The file could not be read as an Excel .xlsx file.") from exc
    try:
        if not workbook.worksheets:
            raise _fail("The workbook has no sheets.")
        sheet = workbook.worksheets[0]
        if hasattr(sheet, "reset_dimensions"):
            sheet.reset_dimensions()
        for row in sheet.iter_rows(values_only=True):
            yield [_cell_text(value) for value in row[: MAX_IMPORT_COLUMNS + 1]]
    except FeesError:
        raise
    except Exception as exc:
        raise _fail("The file could not be read as an Excel .xlsx file.") from exc
    finally:
        workbook.close()


_EOL = re.compile(r"(\r\n|\r|\n)")


def _csv_lines(source):
    """Lines (with their line ends) from a binary or text stream, read in bounded chunks."""
    decoder = codecs.getincrementaldecoder("utf-8-sig")(errors="strict")
    pending = ""
    while True:
        chunk = source.read(_CSV_CHUNK)
        if not chunk:
            break
        text = chunk if isinstance(chunk, str) else decoder.decode(chunk)
        buffered = pending + text
        held = ""
        if buffered.endswith("\r"):  # may be the first half of \r\n
            held = "\r"
            buffered = buffered[:-1]
        pieces = _EOL.split(buffered)
        for index in range(0, len(pieces) - 1, 2):
            yield pieces[index] + pieces[index + 1]
        pending = pieces[-1] + held
        if len(pending) > _MAX_LINE_CHARS:
            raise _fail("The file has a line that is far too long, so it was not imported.")
    tail = decoder.decode(b"", True)
    rest = pending + tail
    if rest:
        yield rest


def _csv_cells(source):
    try:
        for row in csv.reader(_csv_lines(source)):
            cells = [_cell_text(value) for value in row[: MAX_IMPORT_COLUMNS + 1]]
            yield cells
    except UnicodeDecodeError as exc:
        raise _fail("The CSV file must be saved as UTF-8.") from exc
    except csv.Error as exc:
        raise _fail("The CSV file could not be read.") from exc


@contextlib.contextmanager
def _opened(source):
    """A path is opened in binary mode and closed after; a file object is used as given."""
    if isinstance(source, (str, os.PathLike)):
        with open(source, "rb") as handle:
            yield handle
    else:
        yield source


def iter_rows(source, kind=None):
    """Rows of the spreadsheet as lists of trimmed strings, header first, blank rows skipped.

    Checks the kind, the 10 MB size cap and (xlsx) the zip sanity NOW, before the file is opened; the rows
    then stream. Use ``contextlib.closing`` (or exhaust it) so the workbook and the file are released.
    """
    kind = _check_source(source, kind)
    return _stream(source, kind)


def _stream(source, kind):
    with _opened(source) as handle:
        cells = _xlsx_cells(handle) if kind == "xlsx" else _csv_cells(handle)
        try:
            yield from _shape_rows(cells)
        finally:
            cells.close()


def inspect_file(source, kind=None):
    """Step 1: headers, the first 5 data rows, the data row count and the guessed mapping (R-IM-1)."""
    with heavy_operation(HEAVY_NAME):
        header = None
        sample = []
        count = 0
        with contextlib.closing(iter_rows(source, kind)) as rows:
            for cells in rows:
                if header is None:
                    header = cells
                    continue
                count += 1
                if count <= 5:
                    sample.append(cells + [""] * (len(header) - len(cells)))
        if header is None or count < 1:
            raise _fail("The file needs a header row and at least one data row.")
        return {"headers": header, "sample_rows": sample, "row_count": count, "mapping": guess_mapping(header)}


# ---------------------------------------------------------------------------
# The import engine (port of importMemos)
# ---------------------------------------------------------------------------

class _RowSkip(Exception):
    """A row that cannot be imported; the message becomes the warning text after ``Row N: ``."""


def _validate_mapping(mapping, headers=None):
    if not isinstance(mapping, dict):
        raise _fail("The column mapping is missing.")
    unknown = [key for key in mapping if key not in _FIELD_IDS]
    if unknown:
        raise _fail(f"Unknown import field: {unknown[0]}")
    if not mapping.get("firm_name") or not mapping.get("matter_name"):
        raise _fail("Firm name and Matter name columns must be mapped")
    if headers is not None:
        for field, header in mapping.items():
            if header and header not in headers:
                raise _fail(f'The column "{header}" is not in the file.')


def _today():
    return datetime.date.today().isoformat()


class _Importer:
    """State of one import run: counters, lookup caches, warnings and the grouped-payment queue."""

    def __init__(self, profile, mapping, auto_number):
        self.profile = profile
        self.mapping = {field: header for field, header in mapping.items() if header}
        self.auto_number = bool(auto_number)
        self.firms_created = 0
        self.matters_created = 0
        self.memos_created = 0
        self.payments_created = 0
        self.rows_processed = 0
        self.warnings = []
        self.warnings_total = 0
        self.firm_ids = {}  # lower name -> firm id
        self.group_ids = {}  # (firm id, lower name) -> group id
        self.group_counts = {}  # firm id -> groups known
        self.matters = {}  # (firm id, lower name) -> [matter id, has court, has client]
        self.grouped = {}  # payment group -> [(memo id, net, tds, date, payee, row no)]
        self.quiet = False  # true during the planning pass, which must not warn
        self.assigned = {}  # row no -> planned automatic number text
        # The planning pass is needed only when the run can hand out new automatic numbers.
        self.needs_plan = self.auto_number or "numbering" in self.mapping

    # -- small helpers -----------------------------------------------------

    def warn(self, text):
        if self.quiet:
            return
        self.warnings_total += 1
        if len(self.warnings) < MAX_WARNINGS:
            self.warnings.append(text)

    def get(self, row, field):
        header = self.mapping.get(field)
        if not header:
            return None
        value = row.get(header)
        return None if value is None else str(value).strip()

    def number(self, row, field, row_no):
        """A parsed money value (0 when blank or unreadable); out of range skips the row."""
        value = parse_number(self.get(row, field))
        if abs(value) >= _MAX_MONEY:
            raise _RowSkip(f"the value in the {field.replace('_', ' ')} column is too large.")
        return round2(value)

    def count(self, row, field, row_no):
        value = parse_number(self.get(row, field))
        if abs(value) > _MAX_COUNT:
            raise _RowSkip(f"the value in the {field.replace('_', ' ')} column is too large.")
        whole = int(value.to_integral_value())
        if whole != value:
            self.warn(f"Row {row_no}: {field.replace('_', ' ')} {value} was rounded to {whole}.")
        return whole

    def date(self, row, field, row_no):
        iso, impossible = parse_date(self.get(row, field))
        if impossible:
            self.warn(f"Row {row_no}: {self.get(row, field)!r} is not a real date, so it was treated as blank.")
        return iso

    @staticmethod
    def limit(label, value, kind):
        if value and len(value) > _LIMITS[kind]:
            raise _RowSkip(f"the {label} is longer than {_LIMITS[kind]} characters.")

    # -- find or create ----------------------------------------------------

    def find_or_create_firm(self, name):
        key = name.lower()
        firm_id = self.firm_ids.get(key)
        if firm_id is None:
            firm = Firm.objects.filter(profile=self.profile, name__iexact=name).only("pk").first()
            if firm is None:
                firm = Firm.objects.create(profile=self.profile, name=name, status="active")
                self.firms_created += 1
            firm_id = self.firm_ids[key] = firm.pk
        return firm_id

    def find_or_create_group(self, firm_id, name):
        key = (firm_id, name.lower())
        group_id = self.group_ids.get(key)
        if group_id is not None:
            return group_id
        group = Group.objects.filter(firm_id=firm_id, name__iexact=name).only("pk").first()
        if group is None:
            known = self.group_counts.get(firm_id)
            if known is None:
                known = Group.objects.filter(firm_id=firm_id).count()
            if known >= _MAX_GROUPS_PER_FIRM:
                raise _RowSkip(f"the firm already has the most groups allowed ({_MAX_GROUPS_PER_FIRM}).")
            group = Group.objects.create(profile=self.profile, firm_id=firm_id, name=name)
            self.group_counts[firm_id] = known + 1
        self.group_ids[key] = group.pk
        return group.pk

    def find_or_create_matter(self, firm_id, group_name, name, court, client):
        """The matter by (firm, name), reused even under another group. Court and client fill only if blank."""
        key = (firm_id, name.lower())
        entry = self.matters.get(key)
        if entry is None:
            matter = Matter.objects.filter(profile=self.profile, firm_id=firm_id, name__iexact=name).first()
            if matter is None:
                group_id = self.find_or_create_group(firm_id, group_name)
                matter = Matter.objects.create(
                    profile=self.profile,
                    firm_id=firm_id,
                    group_id=group_id,
                    name=name,
                    is_archived=False,
                    court_name=court or "",
                    client=client or "",
                )
                self.matters_created += 1
            entry = self.matters[key] = [matter.pk, bool(matter.court_name), bool(matter.client)]
            return entry[0]
        updates = {}
        if court and not entry[1]:
            updates["court_name"] = court
            entry[1] = True
        if client and not entry[2]:
            updates["client"] = client
            entry[2] = True
        if updates:
            Matter.objects.filter(pk=entry[0]).update(**updates)
        return entry[0]

    # -- numbering (owner decision 5) ----------------------------------------

    def decide(self, row, row_no, number_raw, date_iso):
        """What to do about the memo number of a row: ``(kind, text)``.

        ``kind`` is ``draft`` (no number), ``custom`` (other text, ``seq = 0``), ``keep`` (an automatic-shaped
        number kept as a real auto number), ``forced`` (automatic-shaped text forced to be custom) or ``alloc``
        (a new automatic number from the plan; ``text`` is ``None``). Warns (unless quiet) and may raise
        ``_RowSkip``.
        """
        mode = (self.get(row, "numbering") or "").lower()
        if mode and mode not in ("auto", "custom", "draft"):
            self.warn(f'Row {row_no}: Numbering "{self.get(row, "numbering")}" is not Auto, Custom or Draft, '
                      "so it was ignored.")
            mode = ""
        if mode == "draft":
            if number_raw:
                self.warn(f'Row {row_no}: Numbering is Draft, so the number "{number_raw}" was ignored.')
            return "draft", None
        if mode == "auto":
            if number_raw:
                self.warn(f'Row {row_no}: Numbering is Auto, so the number "{number_raw}" was ignored '
                          "and the next automatic number is used.")
            if not date_iso:
                self.warn(f"Row {row_no}: Numbering is Auto but there is no valid date, imported as draft.")
                return "draft", None
            return "alloc", None
        if mode == "custom" and not number_raw:
            self.warn(f"Row {row_no}: Numbering is Custom but the number is blank, imported as draft.")
            return "draft", None
        if number_raw:
            if not date_iso:
                self.warn(f'Row {row_no}: memo "{number_raw}" has no valid date, imported as draft.')
                return "draft", None
            parsed = memo_numbers.parse_auto_number(number_raw)
            if parsed is None:
                return "custom", number_raw
            if mode == "custom":
                if int(parsed[0][:4]) >= int(current_financial_year()[:4]):
                    raise _RowSkip(
                        f'the number "{number_raw}" looks automatic and belongs to the current or a future '
                        f"financial year ({parsed[0]}), so it cannot be forced to be a custom number. "
                        "Leave Numbering blank or use Auto to keep it as an automatic number."
                    )
                return "forced", number_raw
            return "keep", number_raw
        if self.auto_number and date_iso:
            return "alloc", None
        return "draft", None

    def order_of(self, row, row_no):
        """The ``order`` column as a whole number, or ``None`` (blank, not mapped or not a whole number)."""
        raw = self.get(row, "order")
        if not raw:
            return None
        if not re.fullmatch(r"[+-]?\d{1,9}", raw):
            self.warn(f'Row {row_no}: order "{raw}" is not a whole number, so it was ignored.')
            return None
        return int(raw)

    def plan(self, rows):
        """Pass 1: reserve kept numbers and plan the automatic ones (see the module docstring)."""
        self.quiet = True
        reserved = set()
        highest = {}  # fy -> highest kept N
        wanted = {}  # fy -> [(has no order, order, date, row no)]
        try:
            for index, row in enumerate(rows):
                row_no = index + 2
                if not self.get(row, "firm_name") or not self.get(row, "matter_name"):
                    continue
                iso, _impossible = parse_date(self.get(row, "date"))
                try:
                    kind, text = self.decide(row, row_no, self.get(row, "memo_number"), iso)
                except _RowSkip:
                    continue
                if kind in ("keep", "forced"):
                    if text in reserved:
                        continue  # the first one wins; pass 2 refuses the later copy as already in use
                    reserved.add(text)
                    fy, seq = memo_numbers.parse_auto_number(text)
                    if (kind == "keep" and fy == derive_financial_year(iso)
                            and 1 <= seq <= memo_numbers.MAX_AUTO_SEQ):
                        highest[fy] = max(highest.get(fy, 0), seq)
                elif kind == "alloc":
                    order = self.order_of(row, row_no)
                    wanted.setdefault(derive_financial_year(iso), []).append(
                        (order is None, order or 0, iso, row_no)
                    )
        finally:
            self.quiet = False
        for fy, items in wanted.items():
            # Lock the counter row so nobody else takes a number between the plan and the claims.
            counter, _created = NumberSequence.objects.select_for_update().get_or_create(
                profile=self.profile, financial_year=fy, defaults={"last_seq": 0}
            )
            used = set(
                Memo.objects.filter(profile=self.profile, memo_number__startswith=f"{fy}/")
                .values_list("memo_number", flat=True)
            )
            items.sort()
            seq = max(counter.last_seq, highest.get(fy, 0))
            for _no_order, _order, _iso, row_no in items:
                seq += 1
                while f"{fy}/{seq}" in reserved or f"{fy}/{seq}" in used:
                    seq += 1
                self.assigned[row_no] = f"{fy}/{seq}"

    # -- one row -----------------------------------------------------------

    def process(self, row, row_no):
        try:
            self._process(row, row_no)
        except _RowSkip as skip:
            self.warn(f"Row {row_no}: skipped, {skip}")

    def _process(self, row, row_no):
        firm_name = self.get(row, "firm_name")
        matter_name = self.get(row, "matter_name")
        number_raw = self.get(row, "memo_number")
        paid = self.number(row, "amount_paid", row_no) if "amount_paid" in self.mapping else Decimal(0)

        # Rule 1: no firm, matter or number but money received is an unaccounted payment.
        if not firm_name and not matter_name and not number_raw and paid > 0:
            self.unaccounted(row, row_no, paid)
            return
        # Rule 2.
        if not firm_name or not matter_name:
            self.warn(f"Row {row_no}: skipped (missing firm or matter name).")
            return

        partner = self.get(row, "partner_name") or DEFAULT_GROUP_NAME
        court = self.get(row, "court_name") or ""
        client = self.get(row, "matter_client") or ""
        plaintiff = self.get(row, "party_plaintiff") or ""
        defendant = self.get(row, "party_defendant") or ""
        payee = (self.get(row, "payee") or "") if "payee" in self.mapping else ""
        self.limit("firm name", firm_name, "firm")
        self.limit("partner name", partner, "group")
        self.limit("matter name", matter_name, "matter")
        self.limit("memo number", number_raw, "number")
        for label, value in (("court name", court), ("client", client), ("plaintiff", plaintiff),
                             ("defendant", defendant), ("payee", payee)):
            self.limit(label, value, "text")

        date_iso = self.date(row, "date", row_no)
        kind, number_text = self.decide(row, row_no, number_raw, date_iso)
        is_draft = kind == "draft"
        if kind == "alloc":
            self.order_of(row, row_no)  # only to warn about an unreadable order value
            number_text = self.assigned.get(row_no)  # None falls back to the next number at save time

        data = {
            "date": date_iso or _today(),
            "custom_memo_number": number_text,
            "force_custom_number": kind == "forced",
            "addressee_line1": firm_name,
            "court_name": court,
            "client": client,
            "plaintiff_name": plaintiff,
            "defendant_name": defendant,
            "num_appearances": self.count(row, "num_appearances", row_no),
            "fees_per_appearance": self.number(row, "fees_per_appearance", row_no),
            "num_conferences": self.count(row, "num_conferences", row_no),
            "fees_per_conference": self.number(row, "fees_per_conference", row_no),
            "misc_drafting_description": self.get(row, "misc_description") or "",
            "fees_misc_drafting": self.number(row, "fees_misc", row_no),
            "num_drafts": self.count(row, "num_drafts", row_no) if "num_drafts" in self.mapping else 0,
            "custom_total_fees": self.number(row, "total_fees", row_no) if "total_fees" in self.mapping else None,
        }
        total = memo_fees.resolve_memo_fees(data).total_fees
        if total < 0:
            raise _RowSkip("Total Fees must be greater than or equal to 0.")
        if total >= _MAX_TOTAL:
            raise _RowSkip("the total fees are too large.")

        pay_net = paid
        pay_tds = Decimal(0)
        pay_date = ""
        if pay_net > 0 and not is_draft:
            pay_tds = max(self.number(row, "payment_tds", row_no), Decimal(0)) if "payment_tds" in self.mapping else Decimal(0)
            pay_date = self.date(row, "payment_date", row_no) if "payment_date" in self.mapping else ""

        firm_id = self.find_or_create_firm(firm_name)
        data["matter_id"] = self.find_or_create_matter(firm_id, partner, matter_name, court, client)
        try:
            memo = memos.create_memo(self.profile, data, is_draft)
        except FeesError as error:
            self.warn(f"Row {row_no}: {error.message}")
            return
        except (DataError, IntegrityError):
            self.warn(f"Row {row_no}: the memo could not be saved.")
            return
        self.memos_created += 1
        self.rows_processed += 1

        if pay_net > 0 and not memo.is_draft:
            group = (self.get(row, "payment_group") or "") if "payment_group" in self.mapping else ""
            when = pay_date or date_iso or _today()
            if group:
                self.grouped.setdefault(group, []).append((memo.pk, pay_net, pay_tds, when, payee, row_no))
            else:
                self.single_payment(memo.pk, pay_net, pay_tds, when, payee, row_no)
        elif pay_net > 0:
            self.warn(f"Row {row_no}: paid amount ignored because the memo is a draft (no number).")

    def unaccounted(self, row, row_no, paid):
        tds = max(self.number(row, "payment_tds", row_no), Decimal(0)) if "payment_tds" in self.mapping else Decimal(0)
        when = self.date(row, "payment_date", row_no) if "payment_date" in self.mapping else ""
        payee = (self.get(row, "payee") or "") if "payee" in self.mapping else ""
        self.limit("payee", payee, "text")
        try:
            payments.add_unaccounted_payment(
                self.profile,
                {
                    "amount": paid,
                    "tds_rate": 0,
                    "auto_tds": False,
                    "tds_amount": tds,
                    "payee": payee,
                    "date_of_payment": when or _today(),
                },
            )
        except (FeesError, DataError, IntegrityError) as error:
            self.warn(f"Row {row_no}: unaccounted payment not recorded ({getattr(error, 'message', error)}).")
            return
        self.payments_created += 1
        self.rows_processed += 1

    def single_payment(self, memo_id, net, tds, when, payee, row_no):
        try:
            payments.add_payment_to_memo(
                self.profile,
                memo_id,
                {"amount": net, "tds_rate": 0, "auto_tds": False, "tds_amount": tds,
                 "payee": payee, "date_of_payment": when},
            )
        except (FeesError, DataError, IntegrityError) as error:
            self.warn(f"Row {row_no}: payment not recorded ({getattr(error, 'message', error)}).")
            return
        self.payments_created += 1

    def finish_groups(self):
        """Rule 7: a group of two or more is ONE payment split across its memos; one member is single."""
        groups, self.grouped = self.grouped, {}
        for members in groups.values():
            if len(members) == 1:
                memo_id, net, tds, when, payee, row_no = members[0]
                self.single_payment(memo_id, net, tds, when, payee, row_no)
                continue
            first = members[0]
            try:
                payments.add_payment(
                    self.profile,
                    {
                        "amount": sum((member[1] for member in members), Decimal(0)),
                        "tds_rate": 0,
                        "auto_tds": False,
                        "tds_amount": sum((member[2] for member in members), Decimal(0)),
                        "date_of_payment": first[3],
                        "payee": first[4],
                        "allocations": [
                            {"memo_id": member[0], "amount": member[1], "tds_amount": member[2]}
                            for member in members
                        ],
                    },
                )
            except (FeesError, DataError, IntegrityError) as error:
                self.warn(f"Payment group (row {first[5]}): split payment not recorded "
                          f"({getattr(error, 'message', error)}).")
                continue
            self.payments_created += 1

    def result(self):
        return {
            "firms_created": self.firms_created,
            "matters_created": self.matters_created,
            "memos_created": self.memos_created,
            "payments_created": self.payments_created,
            "rows_processed": self.rows_processed,
            "warnings": self.warnings,
            "warnings_total": self.warnings_total,
        }


def import_memos(profile, rows, mapping, auto_number=False):
    """Imports ``rows`` (dicts keyed by header) with ``mapping`` in ONE transaction (port of importMemos).

    The whole import is one ``transaction.atomic()``: an unexpected error rolls everything back.
    ``data_version`` is bumped once at the end (the per-call stamps are folded into one; ``touch`` also
    purges the ``StatsCache`` rows). A row that fails is skipped with a ``Row N: ...`` warning.
    """
    _validate_mapping(mapping)
    importer = _Importer(profile, mapping, auto_number)
    if importer.needs_plan and iter(rows) is rows:
        rows = list(rows)  # a one-shot iterator cannot be read twice; files are reopened instead
    with transaction.atomic():
        # Lock the settings row so a concurrent change waits and the single bump below is exact.
        settings, _created = FeesSettings.objects.select_for_update().get_or_create(profile=profile)
        start_version = settings.data_version
        with history.quiet():
            if importer.needs_plan:
                importer.plan(rows)
            for index, row in enumerate(rows):
                importer.process(row, index + 2)
            importer.finish_groups()
        history.record(
            profile, "import", "memo", None,
            f"Imported {importer.memos_created} memos and {importer.payments_created} payments from a file",
        )
        FeesSettings.objects.filter(pk=settings.pk).update(data_version=start_version)
        memos.touch(profile)
    return importer.result()


def _dict_rows(rows, headers):
    """Turn list rows into ``{header: text}`` dicts one at a time (a later duplicate header wins)."""
    positions = [(header, index) for index, header in enumerate(headers) if header]
    for cells in rows:
        yield {header: (cells[index] if index < len(cells) else "") for header, index in positions}


class _FileRows:
    """The data rows of an upload as dicts. Every ``iter()`` reopens the file, so the numbering plan can read it twice."""

    def __init__(self, source, kind, header):
        self.source = source
        self.kind = kind
        self.header = header

    def __iter__(self):
        with contextlib.closing(iter_rows(self.source, self.kind)) as rows:
            next(rows, None)  # the header
            yield from _dict_rows(rows, self.header)


def run_import(profile, source, mapping, auto_number=False, kind=None):
    """Step 2: stream ``source`` and import it with ``mapping`` (R-IM-2, R-IM-3).

    Holds ``heavy_operation("excel_import")`` for the whole run. The caller (a view in Phase 7) must have
    checked the Editor role. Raises ``FeesError("IMPORT_FAILED")`` for a bad file or mapping and ``Busy``
    when another heavy job is running; nothing is changed in either case.
    """
    _validate_mapping(mapping)
    with heavy_operation(HEAVY_NAME):
        with contextlib.closing(iter_rows(source, kind)) as rows:
            header = next(rows, None)
            if header is None:
                raise _fail("The file needs a header row and at least one data row.")
            _validate_mapping(mapping, header)
            first = next(rows, None)
            if first is None:
                raise _fail("The file needs a header row and at least one data row.")
        try:
            return import_memos(profile, _FileRows(source, kind, header), mapping, auto_number)
        except (DataError, IntegrityError) as exc:
            raise _fail("The import could not be saved, so nothing was imported.") from exc
