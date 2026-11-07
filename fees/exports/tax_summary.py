"""The Tax Summary text file (T5.4, requirements R-EX-4, PORTING_BRIEF 7.3, ``electron/ipc/statistics.ts``).

``tax_summary_text(profile, financial_year, options=None)`` returns the file text; ``export_tax_summary``
returns ``(file_name, file)`` with ``file`` a binary ``TemporaryFile`` at position 0 holding the UTF-8
text. File name ``Tax Summary {fy}.txt``. A pure READ built on ``get_year_end_summary``.

Lines, in order: the title, a blank line, then Appearances, Appearances / Week, Memos, New Matters, Firms
Billed, then Billed, Received and TDS with the rupee sign and Indian digit grouping (``12,34,567``,
rounded to a whole number). The text ends with a newline.

One difference from the desktop: the title uses a hyphen (``Tax Summary - 2026-27``) where the original
used an em dash, because the project forbids em dashes in written content.
"""

import tempfile
from decimal import Decimal

from fees.exports.filenames import sanitize_value
from fees.services.money import format_currency
from fees.services.statistics import get_year_end_summary

RUPEE = "\u20b9"


def _plain(value):
    """A number as the original prints it: no trailing zeros (``2.5``, ``3``, ``0``)."""
    if isinstance(value, Decimal):
        text = format(value.normalize(), "f")
        return "0" if text in ("-0", "") else text
    return str(value)


def tax_summary_lines(summary):
    """The lines (no newlines) for a ``get_year_end_summary`` dict."""
    return [
        f"Tax Summary - {summary['financial_year']}",
        "",
        f"Appearances: {_plain(summary['num_appearances'])}",
        f"Appearances / Week: {_plain(summary['appearances_per_week'])}",
        f"Memos: {_plain(summary['memo_count'])}",
        f"New Matters: {_plain(summary['new_matters'])}",
        f"Firms Billed: {_plain(summary['active_firms'])}",
        f"Billed: {RUPEE} {format_currency(summary['total_billed'])}",
        f"Received: {RUPEE} {format_currency(summary['total_received'])}",
        f"TDS: {RUPEE} {format_currency(summary['total_tds'])}",
    ]


def tax_summary_text(profile, financial_year, options=None):
    """The whole file text for one financial year."""
    summary = get_year_end_summary(profile, financial_year, options or {})
    return "\n".join(tax_summary_lines(summary)) + "\n"


def export_tax_summary(profile, financial_year, options=None):
    """``(file_name, TemporaryFile)`` for the Tax Summary of ``financial_year``."""
    text = tax_summary_text(profile, financial_year, options)
    out = tempfile.TemporaryFile()
    try:
        out.write(text.encode("utf-8"))
        out.seek(0)
    except BaseException:
        out.close()
        raise
    return f"Tax Summary {sanitize_value(financial_year) or 'Export'}.txt", out
