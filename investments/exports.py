"""Excel exports for the Investments program (plan 17.6): one small writer for every table.

`openpyxl` `write_only`, spooled to a temporary file (imported lazily, so it is never loaded at start-up); exact figures always,
whatever the Auto / Full toggle shows; a text cell that starts like a formula is stored as text; dates are real dates.
"""
import datetime
import re
import tempfile
from decimal import Decimal

from django.http import FileResponse

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _cell(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float, Decimal, datetime.date)):
        return value
    text = _CONTROL.sub("", str(value))
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def workbook(sheets):
    """``sheets`` is ``[(title, header, rows)]``; returns a temporary file positioned at 0 (closing it deletes it)."""
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font

    wb = Workbook(write_only=True)
    for title, header, rows in sheets:
        ws = wb.create_sheet(re.sub(r"[\[\]:*?/\\]", "", title)[:31] or "Sheet")
        bold = []
        for name in header:
            cell = WriteOnlyCell(ws, value=name)
            cell.font = Font(bold=True)
            bold.append(cell)
        ws.append(bold)
        for row in rows:
            ws.append([_cell(v) for v in row])
    handle = tempfile.TemporaryFile()
    wb.save(handle)
    handle.seek(0)
    return handle


def response(file_name, sheets):
    handle = workbook(sheets)
    return FileResponse(handle, as_attachment=True, filename=file_name, content_type=XLSX_TYPE)


def safe_file_name(name, suffix):
    """A file name made from a user's text: letters, digits, spaces, dots, dashes and underscores only."""
    stem = re.sub(r"[^\w .\-]", "", name or "").strip(" .") or "Investment"
    stem = re.sub(r" {2,}", " ", stem)
    return f"{stem[:80]} {suffix}.xlsx"


TXN_HEADER = ["Date", "Allotment date", "Investment", "Code", "ISIN", "Type", "Buy / sell", "Units", "Price", "Charges", "Amount", "Portfolio", "Broker",
              "Folio", "Status", "Opening", "Reference", "Note"]


def _txn_line(t):
    from .models import SIDE_BUY, STATUS_FINAL
    from .services import core

    if t.status == STATUS_FINAL and t.units is not None:
        amount = core.buy_total(t) if t.side == SIDE_BUY else core.sell_total(t)
    else:
        amount = t.amount
    i = t.instrument
    return [t.date, t.allotment_date, i.name, i.code, i.isin, i.get_kind_display(), t.get_side_display(), t.units, t.price, t.charges, amount,
            t.portfolio.name, t.broker.name, t.folio.number if t.folio else "", t.get_status_display(), t.is_opening, t.reference, t.note]


def transaction_sheets(txns, transfers=None, dividends=None, automatic=None):
    """The Transactions sheet, then Transfers and Dividends sheets when those are given (querysets with their related rows selected)."""
    sheets = [("Transactions", TXN_HEADER, (_txn_line(t) for t in txns.iterator()))]
    if transfers is not None:
        sheets.append(("Transfers", ["Date", "Investment", "Units", "From portfolio", "From broker", "From folio", "To portfolio", "To broker", "To folio",
                                     "Note"],
                       ([r.date, r.instrument.name, r.units, r.from_portfolio.name, r.from_broker.name, r.from_folio.number if r.from_folio else "",
                         r.to_portfolio.name, r.to_broker.name, r.to_folio.number if r.to_folio else "", r.note] for r in transfers.iterator())))
    if dividends is not None:
        sheets.append(("Dividends", ["Date received", "Investment", "Portfolio", "Broker", "Folio", "Amount", "Tax deducted", "Note"],
                       ([r.date, r.instrument.name, r.portfolio.name, r.broker.name, r.folio.number if r.folio else "", r.amount, r.tax_deducted,
                         r.note] for r in dividends.iterator())))
    if automatic:
        # Units a bonus or split adds by itself: not transactions, so a separate sheet (they are not part of the Transactions sheet's totals).
        sheets.append(("Added automatically", ["Date", "Investment", "Code", "What", "Units added", "Price", "Portfolio", "Broker", "Folio"],
                       ([r["date"], r["instrument"].name, r["instrument"].code, r["label"], r["units"], 0, r["portfolio"], r["broker"], r["folio"]]
                        for r in automatic)))
    return sheets


HOLDINGS_HEADER = ["Name", "Type", "Code", "ISIN", "Units", "Average cost", "Cost", "Price", "Price date", "Value", "Gain", "Gain %", "XIRR",
                   "First bought", "Status", "Realised gain", "Dividends"]


def holdings_sheet(rows):
    out = []
    for h in rows:
        shown = h.is_held and not h.unpriced and not h.blocked
        status = "Not bought yet" if h.empty else "Sold out" if not h.is_held else "Hidden" if h.is_hidden else "Held"
        out.append([h.instrument.name, h.instrument.get_kind_display(), h.instrument.code, h.instrument.isin, h.units, h.avg_cost, h.cost, h.price,
                    h.price_date, h.value if h.is_held and not h.blocked else None, h.gain if shown else None, h.gain_pct if shown else None,
                    None if h.blocked else h.xirr, h.first_date, status, h.realised, h.dividends])
    return [("Holdings", HOLDINGS_HEADER, out)]
