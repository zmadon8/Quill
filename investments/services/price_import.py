"""One-off price history upload (plan section 29): CSV or Excel, a dry run first, then apply all-or-nothing.

File format: one row per instrument per day with a header row. Columns (guessed by name): symbol / ISIN / scheme code, date
(`YYYY-MM-DD` or `DD.MM.YYYY`), close, and optionally `basis` (`raw` or `split_adjusted`; if absent the caller supplies one for the
whole file). Other columns are ignored. The file is read as a stream (the Fee Register's reader) and never held whole: the dry run
keeps only counters and the previous row of each investment, so it assumes the rows of one investment are in date order.

Blocking problems (bad date, future date, price of zero or below, basis different from the investment's) stop the apply, because
"applying is all-or-nothing per file" (29.4). Unknown symbols are listed and skipped, never created.
"""
import contextlib
import datetime
import io
import re
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction

from investments.errors import InvestmentsError
from investments.models import Instrument, Price, SourceSymbol
from investments.services import fetch, locks, source_formats

BATCH = 500
GAP_DAYS = 10
BIG_MOVE = Decimal("0.40")
DIFF_TOLERANCE = Decimal("0.005")



@dataclass
class Report:
    rows: int = 0
    per_instrument: dict = field(default_factory=dict)      # id -> {name, count, first, last}
    unknown: dict = field(default_factory=dict)             # symbol -> rows
    blocking: list = field(default_factory=list)            # [(line, message)] first few
    blocking_count: int = 0
    gaps: list = field(default_factory=list)                # [(name, from, to)]
    big_moves: list = field(default_factory=list)           # [(name, date, old, new)]
    duplicates: int = 0
    out_of_order: int = 0
    differences: list = field(default_factory=list)         # [(name, date, stored, uploaded)]
    difference_count: int = 0
    basis: str = ""

    @property
    def can_apply(self):
        return self.blocking_count == 0 and bool(self.per_instrument)


def _guess(headers, wanted):
    """The index of the first heading equal to one of the names ``wanted`` (tried in order), else of one that contains a name."""
    lowered = [source_formats.norm(h) for h in headers]
    names = [source_formats.norm(n) for n in wanted]
    for name in names:
        if name in lowered:
            return lowered.index(name)
    for name in names:
        for i, h in enumerate(lowered):
            if name and name in h:
                return i
    return None


def header_columns(headers, columns=None):
    """``{field: column index or None}`` for symbol, date, close and basis, by the alias lists of the ``price_import`` format."""
    columns = columns or source_formats.get("price_import")["columns"]
    return {field: _guess(headers, aliases) for field, aliases in columns.items()}


def _mapped(header):
    """``(symbol, date, close, basis)`` column indexes of the header row; a missing required column is a readable error naming what the file has."""
    found = header_columns(header)
    missing = [f for f in ("symbol", "date", "close") if found[f] is None]
    if missing:
        raise InvestmentsError("BAD_FILE", "The header row needs a symbol (or ISIN or scheme code), a date and a close column. "
                               f"No column found for: {', '.join(missing)}. Headings in the file: {', '.join(h for h in header[:15] if h) or 'none'}. "
                               "An Admin can add other heading names under Catalogue > Price sources > Data source formats.")
    return found["symbol"], found["date"], found["close"], found["basis"]


def _parse_date(text):
    from fees.services.imports import parse_date

    iso, _impossible = parse_date(text)
    return datetime.date.fromisoformat(iso) if iso else None


def _number(text):
    try:
        value = Decimal(re.sub(r"[\u20b9,\s]", "", str(text)))
    except Exception:
        return None
    return value if value.is_finite() else None


def build_lookup(instrument=None):
    """``{normalised symbol: Instrument}`` from codes, ISINs and source symbols; an ambiguous symbol maps to None (skipped)."""
    table = {}

    def put(key, inst):
        key = (key or "").strip().upper()
        if not key:
            return
        table[key] = inst if table.get(key, inst) is inst else None

    qs = Instrument.objects.filter(profile=None) if instrument is None else Instrument.objects.filter(pk=instrument.pk)
    for inst in qs.iterator(chunk_size=500):
        put(inst.code, inst)
        put(inst.isin, inst)
    for sym in SourceSymbol.objects.filter(instrument__in=qs).select_related("instrument").iterator(chunk_size=500):
        put(sym.symbol, sym.instrument)
    return table


def _zip_rows(source):
    """Rows of every `prices-*.csv` member of a price archive (plan 17.4); `pins.csv` and the manifest are handled separately."""
    import csv
    import io
    import zipfile

    with zipfile.ZipFile(source) as archive:
        for name in archive.namelist():
            if not (name.startswith("prices-") and name.endswith(".csv")):
                continue
            with archive.open(name) as handle:
                reader = csv.reader(io.TextIOWrapper(handle, encoding="utf-8"))
                next(reader, None)
                for number, cells in enumerate(reader, start=2):
                    if len(cells) >= 4:
                        yield (number, cells[0], cells[1], cells[2], cells[3])


def _csv_rows(source):
    import csv

    try:
        handle = open(source, "r", encoding="utf-8-sig", newline="") if not hasattr(source, "read") else io.TextIOWrapper(source, encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise InvestmentsError("BAD_FILE", "The file could not be read.") from exc
    with handle:
        header = cols = None
        for number, cells in enumerate(csv.reader(handle), start=1):
            cells = [c.strip() for c in cells]
            if not any(cells):
                continue
            if header is None:
                header = cells
                cols = _mapped(header)
                continue
            cells = cells + [""] * (len(header) - len(cells))
            yield (number, cells[cols[0]], cells[cols[1]], cells[cols[2]], cells[cols[3]] if cols[3] is not None else "")
        if header is None:
            raise InvestmentsError("BAD_FILE", "The file is empty.")


def read_rows(source):
    """Stream ``(line number, symbol, date text, close text, basis text)`` from a CSV, Excel or price-archive zip file (path or uploaded file)."""
    from fees.services import imports

    name = str(getattr(source, "name", source)).lower()
    if name.endswith(".zip"):
        yield from _zip_rows(source)
        return
    if name.endswith(".csv"):
        # Own streaming CSV reader: the Fee Register's reader stops at 50,000 rows, far fewer than a ten-year price history.
        yield from _csv_rows(source)
        return

    try:
        rows = imports.iter_rows(source)
    except Exception as exc:  # the Fee Register reader raises its own error type with a readable message
        raise InvestmentsError("BAD_FILE", str(getattr(exc, "message", exc)) or "The file could not be read.") from exc
    with contextlib.closing(rows):
        header = None
        cols = None
        for number, cells in enumerate(rows, start=1):
            if header is None:
                header = cells
                cols = _mapped(header)
                continue
            cells = cells + [""] * (len(header) - len(cells))
            yield (number, cells[cols[0]], cells[cols[1]], cells[cols[2]], cells[cols[3]] if cols[3] is not None else "")


def _check_row(inst, line, day, close, basis, file_basis, today, report):
    """Returns True when the row is clean. Blocking problems are counted."""
    problem = None
    if day is None:
        problem = "unreadable date"
    elif day > today:
        problem = "date in the future"
    elif close is None or close <= 0:
        problem = "price of zero or below"
    else:
        used = (basis or file_basis or "").strip().lower()
        if used and inst.price_basis and used != inst.price_basis:
            problem = f"basis '{used}' differs from the investment's '{inst.price_basis}'"
    if problem:
        report.blocking_count += 1
        if len(report.blocking) < 20:
            report.blocking.append((line, f"{inst.name}: {problem}"))
        return False
    return True


def dry_run(source, *, default_basis="", instrument=None, today=None):
    """Read the whole file and report; nothing is written."""
    today = today or datetime.date.today()
    lookup = build_lookup(instrument)
    report = Report(basis=default_basis)
    prev = {}
    pending = defaultdict(list)       # instrument id -> [(date, close)] to compare with what is stored
    seen = set()
    for line, symbol, day_text, close_text, basis_text in read_rows(source):
        report.rows += 1
        inst = lookup.get((symbol or "").strip().upper())
        if inst is None:
            key = (symbol or "").strip() or "(blank)"
            report.unknown[key] = report.unknown.get(key, 0) + 1
            continue
        day, close = _parse_date(day_text), _number(close_text)
        if not _check_row(inst, line, day, close, basis_text, default_basis, today, report):
            continue
        info = report.per_instrument.setdefault(inst.pk, {"name": inst.name, "count": 0, "first": day, "last": day})
        info["count"] += 1
        info["first"], info["last"] = min(info["first"], day), max(info["last"], day)
        if (inst.pk, day) in seen:
            report.duplicates += 1
        seen.add((inst.pk, day))
        before = prev.get(inst.pk)
        if before:
            if day < before[0]:
                report.out_of_order += 1
            else:
                if (day - before[0]).days > GAP_DAYS and len(report.gaps) < 20:
                    report.gaps.append((inst.name, before[0], day))
                if before[1] and abs(close - before[1]) / before[1] > BIG_MOVE and len(report.big_moves) < 20:
                    report.big_moves.append((inst.name, day, before[1], close))
        prev[inst.pk] = (day, close)
        pending[inst.pk].append((day, close))
        if len(pending[inst.pk]) >= BATCH:
            _compare(inst, pending.pop(inst.pk), report)
    for iid, rows in pending.items():
        _compare(Instrument.objects.get(pk=iid), rows, report)
    # Dates the file shares with a corporate action are only known once actions exist (Phase 4); the move is listed regardless.
    return report


def _compare(inst, rows, report):
    stored = dict(Price.objects.filter(instrument=inst, date__in=[d for d, _ in rows]).values_list("date", "close"))
    for day, close in rows:
        old = stored.get(day)
        if old is not None and old != close and abs(close - old) / old > DIFF_TOLERANCE:
            report.difference_count += 1
            if len(report.differences) < 20:
                report.differences.append((inst.name, day, old, close))


def apply(source, *, default_basis="", instrument=None, today=None, report=None):
    """Write the file's rows as source `upload` (the uploaded row wins over a fetched one; hand-entered prices are separate and untouched).
    All or nothing: one transaction, and the dry run must have found nothing blocking. Runs inside ``heavy_operation("price_import")``."""
    today = today or datetime.date.today()
    with locks.heavy("price_import"):
        report = report or dry_run(source, default_basis=default_basis, instrument=instrument, today=today)
        if not report.can_apply:
            raise InvestmentsError("NOT_APPLICABLE", "The file has problems and was not applied. Fix them and try again.", 409)
        lookup = build_lookup(instrument)
        written = 0
        with transaction.atomic():
            batch = defaultdict(dict)
            for _line, symbol, day_text, close_text, basis_text in read_rows(source):
                inst = lookup.get((symbol or "").strip().upper())
                if inst is None:
                    continue
                batch[inst.pk][_parse_date(day_text)] = (_number(close_text), (basis_text or default_basis or inst.price_basis or "").strip().lower())
                if sum(len(v) for v in batch.values()) >= BATCH:
                    written += _flush(batch)
            written += _flush(batch)
        return written


def _flush(batch):
    total = 0
    for iid, rows in list(batch.items()):
        inst = Instrument.objects.get(pk=iid)
        basis = next(iter(rows.values()))[1] or inst.price_basis
        _added, _changed, _kept = fetch.upsert_prices(inst, [(d, c) for d, (c, _b) in rows.items()], "upload", basis)
        total += len(rows)
    batch.clear()
    if total:
        fetch.bump_version()
    return total
