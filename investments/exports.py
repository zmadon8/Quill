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
    units, price, charges = (None, None, None) if i.lump_sum else (t.units, t.price, t.charges)   # a Lump Sum is money only (D192)
    return [t.date, t.allotment_date, i.name, i.code, i.isin, i.get_kind_display(), t.get_side_display(), units, price, charges, amount,
            t.portfolio.name, t.broker.name, t.folio.number if t.folio else "", t.get_status_display(), t.is_opening, t.reference, t.note]


def transaction_sheets(txns, transfers=None, dividends=None, automatic=None):
    """The Transactions sheet, then Transfers and Dividends sheets when those are given (querysets with their related rows selected)."""
    sheets = [("Transactions", TXN_HEADER, (_txn_line(t) for t in txns.iterator()))]
    if transfers is not None:
        sheets.append(("Transfers", ["Date", "Investment", "Units", "From portfolio", "From broker", "From folio", "To portfolio", "To broker", "To folio",
                                     "Note"],
                       ([r.date, r.instrument.name, None if r.instrument.lump_sum else r.units, r.from_portfolio.name, r.from_broker.name, r.from_folio.number if r.from_folio else "",
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


HOLDINGS_HEADER = ["Name", "Type", "Code", "ISIN", "Units", "Average cost", "Cost", "Price", "Price date", "Value", "Gain", "Gain %", "XIRR %", "Index XIRR %", "Alpha (XIRR − Index XIRR) %",
                   "First bought", "Status", "Realised gain", "Other income", "Dividends"]


def holdings_sheet(rows):
    out = []
    for h in rows:
        shown = h.is_held and not h.unpriced and not h.blocked
        status = "Not bought yet" if h.empty else "Sold out" if not h.is_held else "Held"
        lump = getattr(h.instrument, "lump_sum", False)   # money only: no units, average cost or price per unit (D192)
        out.append([h.instrument.name, h.instrument.get_kind_display(), h.instrument.code, h.instrument.isin, None if lump else h.units,
                    None if lump else h.avg_cost, h.cost, None if lump else h.price, h.price_date, h.value if h.is_held and not h.blocked else None, h.gain if shown else None, h.gain_pct if shown else None,
                    None if h.blocked else h.xirr, None if h.blocked else h.index_xirr, None if h.blocked else h.alpha, h.first_date, status, h.realised, h.interest_income, h.dividends])
    return [("Holdings", HOLDINGS_HEADER, out)]


def annual_sheets(r):
    """The Annual Report workbook's sheets for ``annual.Report`` ``r`` (the Annual Report page's Excel button and the annual report email)."""
    pct = (lambda v: None if v is None else round(v * 100, 2))
    summary = [["Starting portfolio value", r.opening_value], ["Amount invested", r.invested], ["Amount sold", r.sold], ["Fresh investments (invested less sold)", r.reinvested],
               ["Short-term capital gains", r.short_gain], ["Long-term capital gains", r.long_gain], ["Other income", r.interest_income], ["XIRR % for the year", pct(r.xirr)],
               [f"{r.index_name} change over the year %", pct(r.index_return)], ["Ending portfolio value", r.closing_value], ["Dividends received", r.dividends],
               ["Tax deducted on dividends", r.dividend_tax], ["Unrealised gain at year end", r.unrealised], ["Long-term after (days held)", r.cutoff],
               ["Note", "A record-keeping aid, not tax advice. Check the treatment with your CA."]]
    sales = [[s["name"], s["bought"], s["sold"], s["days"], s["units"], s["cost"], s["proceeds"], s["gain"], "Long-term" if s["term"] == "long" else "Short-term",
              "; ".join(x for x in ("Estimated date" if s["estimated"] else "", "Bonus" if s["bonus"] else "",
                                    "Split units" if s["origin"] == "split" else "",
                                    f"Cost adjusted for a demerger (cost from the original transactions: {s['original_cost']:.2f})" if s["adjusted"] else "") if x)]
             for s in r.sales]
    interest_sales = [row for s, row in zip(r.sales, sales) if s["interest"]]
    sales = [row for s, row in zip(r.sales, sales) if not s["interest"]]
    held = [[h.instrument.name, h.instrument.get_kind_display(), h.units, h.cost, h.value, h.value - h.cost, "Provisional" if (h.provisional or h.awaiting) else ""]
            for h in r.holdings]
    txns = [[t.date, t.instrument.name, t.get_side_display(), t.units, t.price, t.charges, t.amount if t.status == "awaiting" else None, t.broker.name, t.portfolio.name,
             t.get_status_display()] for t in r.transactions]
    by_pf = [[name, s.opening_value, s.invested, s.sold, s.short_gain, s.long_gain, s.interest_income, pct(s.xirr), s.closing_value] for name, s in r.by_portfolio]
    return [
        ("Summary", ["Item", r.label], summary),
        ("Capital gains", ["Investment", "Bought (held from)", "Sold", "Days held", "Units", "Cost", "Proceeds", "Gain", "Term", "Note"], sales),
        ("Other income", ["Investment", "Bought (held from)", "Sold", "Days held", "Units", "Cost", "Proceeds", "Gain", "Term", "Note"], interest_sales),
        ("Holdings at year end", ["Investment", "Type", "Units", "Cost", "Value", "Unrealised gain", ""], held),
        ("Transactions", ["Date", "Investment", "Buy / sell", "Units", "Price", "Charges", "Amount awaiting", "Broker", "Portfolio", "Status"], txns),
        ("By portfolio", ["Portfolio", "Starting value", "Invested", "Sold", "Short-term gains", "Long-term gains", "Other income", "XIRR %", "Ending value"], by_pf)]


def holdings_transactions_sheets(profile, *, as_of=None, held_only=False):
    """One profile's Holdings sheet and its Transactions, Transfers, Dividends and Added automatically sheets: the same rows as the Excel
    buttons on Holdings > Investments and Holdings > Transactions with no filters. ``as_of`` (a date) values the holdings on that day and leaves
    out anything dated after it; ``held_only`` keeps only the investments still held (the report emails), else every status is listed."""
    from .models import Dividend, Transaction, Transfer
    from .services import corporate, holdings_page

    rows, _held, _sold = holdings_page.load(profile, None, None, as_of)
    if held_only:
        rows = [h for h in rows if h.is_held]
    rows.sort(key=lambda h: (h.empty, not h.is_held, h.instrument.name.lower()))
    txns = Transaction.objects.filter(profile=profile).select_related("instrument", "portfolio", "broker", "folio")
    transfers = Transfer.objects.filter(profile=profile).select_related(
        "instrument", "from_broker", "to_broker", "from_portfolio", "to_portfolio", "from_folio", "to_folio")
    dividends = Dividend.objects.filter(profile=profile).select_related("instrument", "portfolio", "broker", "folio")
    if as_of:
        txns, transfers, dividends = txns.filter(date__lte=as_of), transfers.filter(date__lte=as_of), dividends.filter(date__lte=as_of)
    return holdings_sheet(rows) + transaction_sheets(txns.order_by("-date", "-id"), transfers.order_by("-date", "-id"), dividends.order_by("-date", "-id"),
                                                     corporate.automatic_unit_rows(profile, None, None, as_of, ""))


def workbook_bytes(sheets):
    """The workbook for ``sheets`` as bytes (for an email attachment)."""
    handle = workbook(sheets)
    try:
        return handle.read()
    finally:
        handle.close()
