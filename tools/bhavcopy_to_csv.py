#!/usr/bin/env python3
"""Turn NSE or BSE daily bhavcopy files into one compact price-history CSV for the history upload (plan 29.2). Standard library only.
Run it on your own computer, not on the server.

    python3 bhavcopy_to_csv.py --symbols RELIANCE,TCS,INFY --out history.csv bhavcopies/*.csv bhavcopies/*.zip

It reads both the old NSE layout (SYMBOL, SERIES, CLOSE, TIMESTAMP) and the layout NSE introduced on 8 July 2024 (TckrSymb, SctySrs,
ClsPric, TradDt), and BSE's (SC_CODE/SC_NAME or FinInstrmId, CLOSE or ClsPric). Only the EQ series (or what --series says) is kept.
The output columns are those of the upload: symbol, date, close, basis (always raw: bhavcopy closes are as traded). NSE symbols get .NS
so they match the codes in the program; BSE rows get .BO.
"""
import argparse
import csv
import io
import sys
import zipfile
from datetime import datetime

NEW = {"symbol": "TckrSymb", "series": "SctySrs", "close": "ClsPric", "date": "TradDt"}
OLD = {"symbol": "SYMBOL", "series": "SERIES", "close": "CLOSE", "date": "TIMESTAMP"}
DATE_FORMATS = ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y%m%d")


def _date(text):
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def rows_of(handle, wanted, series):
    reader = csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8-sig") if not isinstance(handle, io.TextIOBase) else handle)
    fields = [f.strip() for f in (reader.fieldnames or [])]
    reader.fieldnames = fields
    cols = NEW if "TckrSymb" in fields else OLD if "SYMBOL" in fields else None
    suffix = ".NS"
    if cols is None and ("SC_CODE" in fields or "FinInstrmId" in fields):
        cols = {"symbol": "SC_NAME" if "SC_NAME" in fields else "TckrSymb", "series": None, "close": "CLOSE" if "CLOSE" in fields else "ClsPric",
                "date": "TradDt" if "TradDt" in fields else None}
        suffix = ".BO"
    if cols is None:
        raise ValueError(f"not a bhavcopy layout I know (columns: {', '.join(fields[:8])})")
    for row in reader:
        sym = (row.get(cols["symbol"]) or "").strip().upper()
        if wanted and sym not in wanted:
            continue
        if cols.get("series") and (row.get(cols["series"]) or "").strip().upper() not in series:
            continue
        day = _date(row.get(cols["date"]) or "") if cols.get("date") else None
        try:
            close = float(row.get(cols["close"]) or 0)
        except ValueError:
            continue
        if day and close > 0:
            yield sym + suffix, day, close


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("files", nargs="+")
    parser.add_argument("--symbols", default="", help="Comma separated symbols to keep (without .NS); all if empty.")
    parser.add_argument("--series", default="EQ")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    wanted = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}
    series = {s.strip().upper() for s in args.series.split(",")}
    seen = {}
    problems = 0
    for path in args.files:
        try:
            if path.lower().endswith(".zip"):
                with zipfile.ZipFile(path) as z:
                    for name in z.namelist():
                        if name.lower().endswith(".csv"):
                            with z.open(name) as handle:
                                for sym, day, close in rows_of(handle, wanted, series):
                                    seen[(sym, day)] = close
            else:
                with open(path, "rb") as handle:
                    for sym, day, close in rows_of(handle, wanted, series):
                        seen[(sym, day)] = close
        except (ValueError, zipfile.BadZipFile, OSError) as exc:
            problems += 1
            print(f"skipped {path}: {exc}", file=sys.stderr)
    with open(args.out, "w", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(["symbol", "date", "close", "basis"])
        for (sym, day), close in sorted(seen.items()):
            writer.writerow([sym, day, f"{close:.2f}", "raw"])
    print(f"{len(seen)} rows written to {args.out}; {problems} file(s) skipped")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
