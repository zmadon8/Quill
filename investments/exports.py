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
