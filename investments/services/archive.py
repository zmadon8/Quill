"""The price archive (plan 17.4): every stored price and the pinned prices as CSV files inside zip files, made on demand and never kept.

* Columns match the history upload (symbol, date, close, basis) plus source; `pins.csv` also has reason. So restoring is the same
  dry-run-then-apply upload (`price_import`, which reads these zips), or `manage.py import_prices --file archive.zip`.
* Streamed: rows are read with `iterator(chunk_size=2000)`, one instrument at a time, each instrument's file is compressed on its own
  and written into the current part; parts are split on instrument boundaries so each is within the size limit. Peak memory is about
  one instrument's rows plus the part being written.
* `pruned=True` thins old prices (before the cutoff) to one per month, as pruning would, but only in the file.
"""
import csv
import io
import tempfile
import zipfile
import zlib
from datetime import datetime
from pathlib import Path

from django.utils import timezone

from investments.models import Instrument, PinnedPrice, Price
from investments.services import pruning

FORMAT_VERSION = "1"
MAX_EMAIL_PARTS = 5


def _symbol(inst):
    return inst.code or inst.isin or str(inst.pk)


def _csv_bytes(header, rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _manifest(entries, pruned, cutoff, parts, now, pin_count):
    lines = [f"Quill Investments price archive, format {FORMAT_VERSION}", f"Made: {timezone.localtime(now):%Y-%m-%d %H:%M} IST",
             f"Parts: {parts}", f"Pruned: {'yes, daily prices before ' + cutoff.isoformat() + ' are one per month' if pruned else 'no (full)'}",
             f"Pinned prices: {pin_count}", "", "symbol | name | rows | first | last | basis"]
    for e in entries:
        lines.append(f"{e['symbol']} | {e['name']} | {e['rows']} | {e['first']} | {e['last']} | {e['basis'] or 'none'}")
    return "\n".join(lines) + "\n"


def build(*, pruned=False, max_part_bytes=None, workdir=None, now=None, today=None):
    """Write the archive into ``workdir`` (a temporary directory by default) and return ``[Path, ...]`` (one per part, numbered)."""
    now = now or timezone.now()
    cfg = pruning.get_settings()
    cutoff = pruning.cutoff_date(cfg.years_kept, today)
    workdir = Path(workdir or tempfile.mkdtemp(prefix="quill_archive_"))
    workdir.mkdir(parents=True, exist_ok=True)
    pins = list(PinnedPrice.objects.select_related("instrument").order_by("instrument_id", "asked_date", "reason").iterator(chunk_size=2000))
    pin_bytes = _csv_bytes(["symbol", "asked_date", "date", "close", "basis", "source", "reason", "approximate"],
                           [(_symbol(p.instrument), p.asked_date, p.trading_date, p.close, p.basis, p.source, p.reason, int(p.approximate)) for p in pins])
    members, entries = [], []          # members: (name, compressed size, raw bytes) per instrument
    for inst in Instrument.objects.filter(prices__isnull=False).distinct().order_by("id").iterator(chunk_size=200):
        rows = list(Price.objects.filter(instrument=inst).order_by("date").values_list("date", "close", "basis", "source").iterator(chunk_size=2000))
        if pruned:
            rows = pruning.apply_to_rows(rows, cutoff)
        if not rows:
            continue
        data = _csv_bytes(["symbol", "date", "close", "basis", "source"], [(_symbol(inst), d, c, b, s) for d, c, b, s in rows])
        spool = workdir / f"member-{inst.pk}.csv"           # on disk, so memory holds one instrument at a time
        spool.write_bytes(data)
        members.append((f"prices-{inst.pk}.csv", len(zlib.compress(data, 6)), spool))
        del data
        entries.append({"symbol": _symbol(inst), "name": inst.name, "rows": len(rows), "first": rows[0][0], "last": rows[-1][0], "basis": inst.price_basis})
    # share the instruments out over parts on instrument boundaries
    parts, current, size = [], [], len(zlib.compress(pin_bytes, 6)) + 2000
    for index, member in enumerate(members):
        if max_part_bytes and current and size + member[1] > max_part_bytes:
            parts.append(current)
            current, size = [], 2000
        current.append(index)
        size += member[1]
    parts.append(current)
    paths = []
    stamp = f"{timezone.localtime(now):%Y%m%d}"
    for number, indexes in enumerate(parts, start=1):
        name = f"price-archive-{stamp}-part{number}of{len(parts)}.zip" if len(parts) > 1 else f"price-archive-{stamp}.zip"
        path = workdir / name
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.txt", _manifest([entries[i] for i in indexes], pruned, cutoff, f"{number} of {len(parts)}", now, len(pins) if number == 1 else 0))
            if number == 1:
                archive.writestr("pins.csv", pin_bytes)
            for i in indexes:
                archive.write(members[i][2], members[i][0])
        paths.append(path)
    for _name, _size, spool in members:
        spool.unlink(missing_ok=True)
    return paths


def effective_pruned(version="full"):
    """The archive is pruned when the live database is pruned (it can only hold what exists), else as the person chose."""
    cfg = pruning.get_settings()
    return bool(cfg.prune_live or (version == "pruned" and cfg.prune_archive))


def read_pins(path):
    """Yield dict rows of ``pins.csv`` from an archive zip (empty if there is none)."""
    with zipfile.ZipFile(path) as archive:
        if "pins.csv" not in archive.namelist():
            return
        with archive.open("pins.csv") as handle:
            yield from csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8"))


def restore_pins(path):
    """Restore pins from an archive only where none exists; a difference from an existing pin is listed, never overwritten silently.
    Returns ``(restored, differences, unknown)``."""
    from datetime import date

    restored, differences, unknown = 0, [], 0
    by_symbol = {}
    for inst in Instrument.objects.filter(profile=None):
        by_symbol[_symbol(inst).upper()] = inst
    for row in read_pins(path):
        inst = by_symbol.get(row["symbol"].upper())
        if inst is None:
            unknown += 1
            continue
        asked, trading = date.fromisoformat(row["asked_date"]), date.fromisoformat(row["date"])
        existing = PinnedPrice.objects.filter(instrument=inst, asked_date=asked, reason=row["reason"]).first()
        if existing is None:
            PinnedPrice.objects.create(instrument=inst, asked_date=asked, trading_date=trading, close=row["close"], basis=row["basis"],
                                       source=row["source"] or "api", reason=row["reason"], approximate=row["approximate"] == "1")
            restored += 1
        elif str(existing.close) != str(row["close"]) and existing.close != type(existing.close)(row["close"]):
            differences.append((inst.name, asked, existing.close, row["close"]))
    return restored, differences, unknown


__all__ = ["build", "effective_pruned", "read_pins", "restore_pins", "datetime", "MAX_EMAIL_PARTS"]
