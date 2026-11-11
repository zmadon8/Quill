"""Excel exports for the Fee Register (T5.3, design 8, requirements R-EX-3, PORTING_BRIEF 7.3).

Every function takes ``profile`` first, is a pure READ (no ``data_version`` bump), and returns
``(file_name, file)`` where ``file`` is a binary ``tempfile.TemporaryFile`` positioned at 0 (R-EX-5,
R-NFR-4). The caller streams it and closes it, which deletes it. Workbooks are written with
``openpyxl.Workbook(write_only=True)``; ``openpyxl`` is imported inside the functions so it is not loaded
at startup. Rows are written from the services' lists as they are read.

Common rules (B 7.3): the header row is bold; money cells use the number format ``#,##0``; dates are
``DD.MM.YYYY`` text; a text cell is never a formula (a value starting with ``=`` is stored as text);
control characters are stripped. ``payment_details`` is never read and never written.

Workbooks (sheet, columns, totals) are copied from ``exportService.ts``:

* ``export_memos``: sheet ``Memos``; ``EXPORT_FAILED`` when there are no rows; no totals;
  file ``Memos {FY or All Years}.xlsx``.
* ``export_statement``: sheet ``Statement``; the Ledger columns, no totals row; file ``{statement title}.xlsx``.
* ``export_ledger``: sheet ``Ledger``; bold ``Totals (n)`` row (Memo, Payment, TDS; Balance blank); file ``Ledger[ - name].xlsx``.
* ``export_feebook``: sheet ``Feebook``; only the visible columns, Date and Memo No. always;
  file ``Feebook {FY or All Years}.xlsx``.
* ``export_outstanding``: sheet ``Outstanding``; only the visible columns, Date, Memo Number and Due always;
  bold ``TOTAL`` row (in the Matter column when shown, else the Memo column);
  default file ``All Outstanding Memos.xlsx``.
* ``export_outstanding_by_firm``: sheet ``Outstanding by Firm``; bold ``TOTAL``;
  file ``Outstanding \u2014 Firm Summary.xlsx`` (an em dash, U+2014, written here as an escape).
* ``export_statistics``: sheet ``Statistics``, ``Metric`` plus one column per period, 13 metric rows;
  file ``Statistics {FY}.xlsx`` for a month table, else ``Statistics.xlsx``.
* ``export_annual_summary``: sheets ``Annual``, ``Annual Stats``, ``Quarter-wise``, ``Month-wise``,
  ``Details by Firm``, ``Details by Matter`` (bold ``TOTAL`` rows); file ``Annual Summary {FY}.xlsx``.

Deliberate differences from the desktop: text titles use a plain hyphen where the original used an em dash
(project rule: no em dashes), and amounts are written as exact decimals.
"""

import itertools
import re
import tempfile

from django.db.models import Max

from fees.errors import FeesError
from fees.exports.filenames import sanitize_value
from fees.models import Allocation
from fees.services import feebook as feebook_service
from fees.services import ledger as ledger_service
from fees.services import memo_lists, outstanding as outstanding_service
from fees.services.money import format_date
from fees.services.statistics import (
    get_annual_breakdown,
    get_period_statistics,
    get_year_end_summary,
)

__all__ = [
    "FEEBOOK_COLUMNS",
    "OUTSTANDING_COLUMNS",
    "STAT_METRIC_ROWS",
    "MONEY_FORMAT",
    "OUTSTANDING_FIRM_SUMMARY_FILENAME",
    "export_annual_summary",
    "export_feebook",
    "export_ledger",
    "export_memos",
    "export_outstanding",
    "export_outstanding_by_firm",
    "export_statement",
    "export_statistics",
]

MONEY_FORMAT = "#,##0"
#: ``Outstanding``, an em dash (U+2014), ``Firm Summary.xlsx`` (R-EX-3).
OUTSTANDING_FIRM_SUMMARY_FILENAME = "Outstanding \u2014 Firm Summary.xlsx"
DEFAULT_OUTSTANDING_FILENAME = "All Outstanding Memos.xlsx"

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_ZERO = 0


class Money:
    """Marks a value to be written with the ``#,##0`` number format."""

    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


def _text(value):
    return "" if value is None else str(value)


# ---------------------------------------------------------------------------
# Column catalogues (copied from FEEBOOK_EXPORT_COLUMNS and OUTSTANDING_EXPORT_COLUMNS)
# ---------------------------------------------------------------------------

#: ``(key, header, width, is_money, value(entry))`` in display order.
FEEBOOK_COLUMNS = (
    ("date", "Date", 14, False, lambda r: format_date(r["date_of_payment"])),
    ("memo", "Memo No.", 16, False, lambda r: _text(r["memo_number"]) if r["memo_id"] else "Unaccounted"),
    ("matter", "Matter Name", 26, False, lambda r: _text(r["matter_name"])),
    ("payee", "Payee", 20, False, lambda r: _text(r["payee"])),
    ("paid", "Paid", 14, True, lambda r: r["amount_paid"]),
    ("tds", "TDS", 12, True, lambda r: r["tds"]),
    ("gross", "Paid + TDS", 14, True, lambda r: r["paid_plus_tds"]),
    ("bank", "Bank", 22, False, lambda r: _text(r["bank_account_name"])),
    ("mode", "Mode", 14, False, lambda r: _text(r["payment_mode"])),
    ("type", "Type", 12, False, lambda r: _text(r["payment_type"])),
)
FEEBOOK_ALWAYS = ("date", "memo")

OUTSTANDING_COLUMNS = (
    ("firm", "Firm", 28, False, lambda e: _text(e["firm_name"])),
    ("partner", "Group", 22, False, lambda e: _text(e["partner_name"])),
    ("date", "Date", 14, False, lambda e: format_date(e["date"])),
    ("memo", "Memo Number", 16, False, lambda e: _text(e["memo_number"])),
    ("matter", "Matter Name", 28, False, lambda e: _text(e["matter_name"])),
    ("total", "Total Memo Amount", 18, True, lambda e: e["total_fees"]),
    ("net", "Net of TDS", 14, True, lambda e: e["net_of_tds"]),
    ("paid", "Already Paid", 14, True, lambda e: e["amount_paid"]),
    ("due", "Due", 14, True, lambda e: e["due"]),
)
OUTSTANDING_ALWAYS = ("date", "memo", "due")

#: ``(key, label, is_money)`` for the 13 statistics rows (``STAT_METRIC_ROWS``), snake case keys.
STAT_METRIC_ROWS = (
    ("num_appearances", "Appearances", False),
    ("num_conferences", "Conferences", False),
    ("num_drafts", "Drafts", False),
    ("amount_billed", "Amount Billed", True),
    ("amount_recovered", "Amount Recovered", True),
    ("percent_recovered", "% Recovered", False),
    ("amount_received", "Amount Received", True),
    ("amount_received_plus_tds", "Received + TDS", True),
    ("fees_per_day", "Fees / Day", True),
    ("appearances_per_week", "Appearances / Week", False),
    ("conferences_per_week", "Conferences / Week", False),
    ("drafts_per_week", "Drafts / Week", False),
    ("fees_per_week", "Fees / Week", True),
)


def select_columns(catalogue, always, visible_keys):
    """The catalogue columns to export: all when ``visible_keys`` is ``None``, else the visible ones plus
    the mandatory ``always`` keys, in catalogue order."""
    if visible_keys is None:
        return list(catalogue)
    wanted = set(visible_keys) | set(always)
    return [column for column in catalogue if column[0] in wanted]


# ---------------------------------------------------------------------------
# Workbook writer
# ---------------------------------------------------------------------------


class _Book:
    """A thin write-only workbook: bold headers, ``Money`` cells, safe text, widths, one temp file."""

    def __init__(self):
        from openpyxl import Workbook
        from openpyxl.styles import Font

        self._bold = Font(bold=True)
        self._font = Font
        self._wb = Workbook(write_only=True)

    def sheet(self, title, widths):
        from openpyxl.utils import get_column_letter

        ws = self._wb.create_sheet(title)
        for index, width in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(index)].width = width
        return _Sheet(self, ws)

    def save(self):
        out = tempfile.TemporaryFile()
        try:
            self._wb.save(out)
            out.seek(0)
        except BaseException:
            out.close()
            raise
        return out


class _Sheet:
    def __init__(self, book, ws):
        self._book = book
        self._ws = ws

    def _cell(self, value, bold=False, size=None):
        from openpyxl.cell import WriteOnlyCell

        number_format = None
        if isinstance(value, Money):
            number_format = MONEY_FORMAT
            value = value.value
        if isinstance(value, str):
            value = _CONTROL.sub("", value)
        formula_like = isinstance(value, str) and value.startswith("=")
        if not (bold or number_format or formula_like or size):
            return value
        cell = WriteOnlyCell(self._ws, value=value)
        if formula_like:
            cell.data_type = "s"
        if number_format:
            cell.number_format = number_format
        if bold or size:
            cell.font = self._book._font(bold=bold, size=size) if size else self._book._bold
        return cell

    def header(self, labels):
        self._ws.append([self._cell(label, bold=True) for label in labels])

    def row(self, values, bold=False, size=None):
        self._ws.append([self._cell(value, bold=bold, size=size) for value in values])

    def blank(self):
        self._ws.append([])


def _safe_name(text):
    return sanitize_value(text) or "Export"


def _financial_year_label(filters):
    value = (filters or {}).get("financial_year")
    return _safe_name(value) if value else "All Years"


def _xlsx_name(text, fallback):
    name = sanitize_value(text or "")
    if not name:
        return fallback
    return name if name.lower().endswith(".xlsx") else name + ".xlsx"


# ---------------------------------------------------------------------------
# Memos
# ---------------------------------------------------------------------------


def _last_payment_dates(profile):
    """``{memo_id: date of the latest payment}`` in one grouped query."""
    return dict(
        Allocation.objects.filter(profile=profile)
        .values("memo_id")
        .annotate(last=Max("payment__date_of_payment"))
        .values_list("memo_id", "last")
    )


def export_memos(profile, filters=None):
    """The Memos workbook for the memos ``memo_lists.list_memos`` returns for ``filters``.

    ``EXPORT_FAILED`` when there are no rows. Two queries for the rows plus one for the last payment dates.
    """
    items = memo_lists.iter_memos(profile, filters)
    first = next(items, None)
    if first is None:
        raise FeesError("EXPORT_FAILED")
    last = _last_payment_dates(profile)
    book = _Book()
    sheet = book.sheet("Memos", (16, 14, 28, 28, 14, 14, 14, 18, 10))
    sheet.header(
        [
            "Memo Number", "Date", "Firm", "Matter Name", "Total Fees", "Net of TDS",
            "Amount Paid", "Date of Last Payment", "Status",
        ]
    )
    for item in itertools.chain([first], items):
        last_date = last.get(item["id"])
        sheet.row(
            [
                _text(item["memo_number"]),
                format_date(item["date"]),
                _text(item["firm_name"]),
                _text(item["matter_name"]),
                Money(item["total_fees"]),
                Money(item["net_of_tds"]),
                Money(item["amount_paid"]),
                format_date(last_date) if last_date else "",
                _text(item["status"]),
            ]
        )
    return f"Memos {_financial_year_label(filters)}.xlsx", book.save()


# ---------------------------------------------------------------------------
# Statement and ledger
# ---------------------------------------------------------------------------


def _ledger_format_sheet(book, sheet_name, rows, with_totals=False):
    """The Ledger layout (columns, widths, money cells, running balance), shared by Ledger and Statement.

    ``with_totals`` adds a bold ``Totals`` row under the Memo, Payment and TDS columns (Balance is left blank).
    """
    sheet = book.sheet(sheet_name, (14, 52, 28, 16, 16, 12, 16))
    sheet.header(
        ["Date", "Particulars", "Matter Name", "Memo Amount", "Payment Amount", "TDS", "Balance Payable"]
    )
    for row in rows:
        sheet.row(
            [
                format_date(row["date"]),
                _text(row["particulars"]),
                _text(row["matter_name"]),
                Money(row["memo_amount"]) if row["memo_amount"] is not None else "",
                Money(row["payment_amount"]) if row["payment_amount"] is not None else "",
                Money(row["tds"]) if row["tds"] is not None else "",
                Money(row["balance"]),
            ]
        )
    if with_totals:
        totals = ledger_service.ledger_totals(rows)
        sheet.row(
            [
                "",
                f"Totals ({totals['count']})",
                "",
                Money(totals["memo_amount"]),
                Money(totals["payment_amount"]),
                Money(totals["tds"]),
                "",
            ],
            bold=True,
        )


def export_statement(profile, scope=None):
    """The Statement of the Matter workbook for ``scope``: the same format as the Ledger export.

    The scope and the ``Statement - ...`` file name are those of ``ledger.build_statement``.
    """
    scope = scope or {}
    rows = ledger_service.build_ledger(profile, scope)
    title = ledger_service.scope_title(profile, scope)[0]
    book = _Book()
    _ledger_format_sheet(book, "Statement", rows)
    return _xlsx_name(title, "Statement.xlsx"), book.save()


def export_ledger(profile, scope=None):
    """The Ledger workbook for ``scope`` (as ``ledger.build_ledger``)."""
    scope = scope or {}
    rows = ledger_service.build_ledger(profile, scope)
    title = ledger_service.scope_title(profile, scope)[0]
    title = "Ledger" + title[len("Statement"):] if title.startswith("Statement") else "Ledger"
    book = _Book()
    _ledger_format_sheet(book, "Ledger", rows, with_totals=True)
    return _xlsx_name(title, "Ledger.xlsx"), book.save()


# ---------------------------------------------------------------------------
# Feebook and outstanding
# ---------------------------------------------------------------------------


def export_feebook(profile, filters=None, visible_keys=None):
    """The Feebook workbook. ``visible_keys`` limits the columns (Date and Memo No. are always kept)."""
    entries = feebook_service.list_feebook(profile, filters)
    columns = select_columns(FEEBOOK_COLUMNS, FEEBOOK_ALWAYS, visible_keys)
    book = _Book()
    sheet = book.sheet("Feebook", [c[2] for c in columns])
    sheet.header([c[1] for c in columns])
    for entry in entries:
        sheet.row([Money(c[4](entry)) if c[3] else c[4](entry) for c in columns])
    return f"Feebook {_financial_year_label(filters)}.xlsx", book.save()


def export_outstanding(profile, filters=None, visible_keys=None, file_name=None):
    """The Outstanding workbook. ``visible_keys`` limits the columns (Date, Memo Number and Due are kept).

    ``file_name`` replaces the default ``All Outstanding Memos.xlsx`` when it is not blank.
    """
    groups = outstanding_service.list_outstanding(profile, filters)
    columns = select_columns(OUTSTANDING_COLUMNS, OUTSTANDING_ALWAYS, visible_keys)
    keys = [c[0] for c in columns]
    book = _Book()
    sheet = book.sheet("Outstanding", [c[2] for c in columns])
    sheet.header([c[1] for c in columns])
    grand = {"total": _ZERO, "net": _ZERO, "paid": _ZERO, "due": _ZERO}
    for group in groups:
        for entry in group["entries"]:
            sheet.row([Money(c[4](entry)) if c[3] else c[4](entry) for c in columns])
        grand["total"] += group["subtotal_total"]
        grand["net"] += group["subtotal_net_of_tds"]
        grand["paid"] += group["subtotal_paid"]
        grand["due"] += group["subtotal"]
    label_key = "matter" if "matter" in keys else "memo"
    total_row = []
    for key in keys:
        if key == label_key:
            total_row.append("TOTAL")
        elif key in grand:
            total_row.append(Money(grand[key]))
        else:
            total_row.append("")
    sheet.row(total_row, bold=True)
    return _xlsx_name(file_name, DEFAULT_OUTSTANDING_FILENAME), book.save()


def export_outstanding_by_firm(profile, filters=None, sort="amount"):
    """The firm-wise Outstanding summary workbook."""
    rows = outstanding_service.list_outstanding_by_firm(profile, filters, sort)
    book = _Book()
    sheet = book.sheet("Outstanding by Firm", (32, 18, 16))
    sheet.header(["Firm", "Memos Outstanding", "Outstanding"])
    grand = _ZERO
    for row in rows:
        sheet.row([_text(row["firm_name"]), row["memo_count"], Money(row["outstanding"])])
        grand += row["outstanding"]
    sheet.row(["TOTAL", "", Money(grand)], bold=True)
    return OUTSTANDING_FIRM_SUMMARY_FILENAME, book.save()


# ---------------------------------------------------------------------------
# Statistics and annual summary
# ---------------------------------------------------------------------------


def _stat_sheet(book, title, stats, first_width):
    periods = stats["periods"]
    sheet = book.sheet(title, [first_width] + [14] * len(periods))
    sheet.header(["Metric"] + [p["label"] for p in periods])
    for key, label, is_money in STAT_METRIC_ROWS:
        values = [p.get(key, _ZERO) for p in periods]
        sheet.row([label] + [Money(v) if is_money else v for v in values])


def export_statistics(profile, granularity, financial_year=None, options=None):
    """The Statistics workbook: ``Metric`` down the rows, one column per period."""
    stats = get_period_statistics(profile, granularity, financial_year, options or {})
    book = _Book()
    _stat_sheet(book, "Statistics", stats, 22)
    if granularity == "month" and financial_year:
        name = f"Statistics {_safe_name(financial_year)}.xlsx"
    else:
        name = "Statistics.xlsx"
    return name, book.save()


def _detail_sheet(book, title, rows, with_firm):
    widths = [34] + ([28] if with_firm else []) + [10, 14, 14, 10, 14, 14, 12]
    sheet = book.sheet(title, widths)
    sheet.header(
        ["Matter" if with_firm else "Firm"]
        + (["Firm"] if with_firm else [])
        + ["Memos", "Appearances", "Conferences", "Drafts", "Billed", "Received", "TDS"]
    )
    totals = dict.fromkeys(
        ("memos", "appearances", "conferences", "drafts", "billed", "received", "tds"), _ZERO
    )
    for row in rows:
        sheet.row(
            [_text(row["name"])]
            + ([_text(row["firm_name"])] if with_firm else [])
            + [
                row["memos"], row["appearances"], row["conferences"], row["drafts"],
                Money(row["billed"]), Money(row["received"]), Money(row["tds"]),
            ]
        )
        for key in totals:
            totals[key] += row[key]
    sheet.row(
        ["TOTAL"]
        + ([""] if with_firm else [])
        + [
            totals["memos"], totals["appearances"], totals["conferences"], totals["drafts"],
            Money(totals["billed"]), Money(totals["received"]), Money(totals["tds"]),
        ],
        bold=True,
    )


def export_annual_summary(profile, financial_year, options=None):
    """The Annual Summary workbook for one financial year (six sheets)."""
    options = options or {}
    summary = get_year_end_summary(profile, financial_year, options)
    annual = get_period_statistics(profile, "financialYear", None, options)
    monthly = get_period_statistics(profile, "month", financial_year, options)
    quarterly = get_period_statistics(profile, "quarter", financial_year, options)
    by_firm = get_annual_breakdown(profile, financial_year, "firm")
    by_matter = get_annual_breakdown(profile, financial_year, "matter")

    book = _Book()
    head = book.sheet("Annual", (28, 18))
    head.row([f"Annual Summary - {financial_year}"], bold=True, size=14)
    head.blank()
    lines = (
        ("Appearances", summary["num_appearances"], False),
        ("Appearances / Week", summary["appearances_per_week"], False),
        ("Memos", summary["memo_count"], False),
        ("New Matters", summary["new_matters"], False),
        ("Firms Billed", summary["active_firms"], False),
        ("Billed", summary["total_billed"], True),
        ("Received", summary["total_received"], True),
        ("TDS", summary["total_tds"], True),
    )
    for label, value, is_money in lines:
        head.row([label, Money(value) if is_money else value])
    head.blank()
    _stat_sheet(book, "Annual Stats", annual, 24)
    _stat_sheet(book, "Quarter-wise", quarterly, 24)
    _stat_sheet(book, "Month-wise", monthly, 24)
    _detail_sheet(book, "Details by Firm", by_firm, False)
    _detail_sheet(book, "Details by Matter", by_matter, True)
    return f"Annual Summary {_safe_name(financial_year)}.xlsx", book.save()
