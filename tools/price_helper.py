#!/usr/bin/env python3
"""Quill Investments local price helper (plan 28). Standard library only: no packages to install.

It asks the site which symbols need prices, fetches them from THIS computer's internet connection (Yahoo for shares, indices and
foreign; the AMFI daily file and mfapi.in for funds), and posts the prices back in small batches. It never sees any holdings or
transactions: it receives only symbols and dates and sends only prices.

    python3 price_helper.py --config ~/.quill-helper.json

The config file is JSON: {"site": "https://your-site.onrender.com", "token": "the token from Catalogue > Price sources",
"sources": ["yahoo", "amfi", "mfapi"]}. It exits non-zero if anything failed. See docs/PRICE_HELPER.md (and its launchd sample).
"""
import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

UA = "Mozilla/5.0"
BATCH = 1000


def http(url, data=None, headers=None, timeout=30):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def with_retry(fn, tries=3):
    for attempt in range(tries):
        try:
            return fn()
        except urllib.error.HTTPError as exc:
            if exc.code != 429 and exc.code < 500 or attempt == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == tries - 1:
                raise
        time.sleep(2 * (2 ** attempt) + random.random())


def yahoo_rows(symbol, since):
    start = (date.fromisoformat(since) - timedelta(days=5)) if since else date.today() - timedelta(days=3650)
    p1 = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp())
    p2 = int(time.time()) + 86400
    body = with_retry(lambda: http(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(symbol, safe='^.-=')}?period1={p1}&period2={p2}&interval=1d"))
    item = json.loads(body)["chart"]["result"][0]
    offset = int(item["meta"].get("gmtoffset") or 0)
    rows = []
    for stamp, close in zip(item.get("timestamp") or [], item["indicators"]["quote"][0].get("close") or []):
        if close and close > 0:
            day = (datetime.fromtimestamp(stamp, tz=timezone.utc) + timedelta(seconds=offset)).date()
            rows.append((day.isoformat(), round(close, 4)))
    return rows


def mfapi_rows(code, since):
    data = json.loads(with_retry(lambda: http(f"https://api.mfapi.in/mf/{code}")))
    rows = []
    for item in data.get("data", []):
        d, m, y = item["date"].split("-")
        day = f"{y}-{m}-{d}"
        if (not since or day > since) and float(item["nav"]) > 0:
            rows.append((day, item["nav"]))
    return rows


def amfi_rows(codes):
    body = with_retry(lambda: http("https://www.amfiindia.com/spages/NAVAll.txt", timeout=90)).decode("utf-8", "replace")
    found = {}
    for line in body.splitlines():
        parts = line.split(";")
        if len(parts) >= 6 and parts[0].strip() in codes:
            # the NAV and date are the last two fields (AMFI now puts the plan and option in columns of their own after the name)
            try:
                nav = float(parts[-2])
                day = datetime.strptime(parts[-1].strip(), "%d-%b-%Y").date().isoformat()
            except ValueError:
                continue
            if nav > 0:
                found[parts[0].strip()] = [(day, parts[-2].strip())]
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", required=True)
    parser.add_argument("--dry-run", action="store_true", help="Fetch but do not send.")
    args = parser.parse_args()
    cfg = json.load(open(args.config))
    site, token = cfg["site"].rstrip("/"), cfg["token"]
    sources = set(cfg.get("sources") or ["yahoo", "amfi", "mfapi"])
    auth = {"Authorization": f"Bearer {token}"}
    wanted = json.loads(http(f"{site}/investments/api/prices/wanted/", headers=auth))["wanted"]
    print(f"{len(wanted)} symbol(s) wanted")
    rows, failures = [], []
    funds = {w["symbol"]: w for w in wanted if w["source"] in ("amfi", "mfapi")}
    if "amfi" in sources and funds:
        try:
            for code, found in amfi_rows(set(funds)).items():
                rows += [{"source": "helper", "symbol_or_code": code, "date": d, "close": c, "basis": funds[code]["basis"]} for d, c in found]
        except Exception as exc:
            failures.append(f"AMFI file: {exc}")
    for n, w in enumerate(wanted):
        if n:
            time.sleep(1 + random.random())
        try:
            if w["source"] == "yahoo" and "yahoo" in sources:
                got = yahoo_rows(w["symbol"], w["last"])
            elif w["source"] in ("amfi", "mfapi") and "mfapi" in sources and not w["last"]:
                got = mfapi_rows(w["symbol"], w["last"])
            else:
                continue
            rows += [{"source": "helper", "symbol_or_code": w["symbol"], "date": d, "close": c, "basis": w["basis"]} for d, c in got]
        except Exception as exc:
            failures.append(f"{w['symbol']}: {exc}")
    print(f"{len(rows)} price(s) fetched, {len(failures)} failure(s)")
    written = 0
    if not args.dry_run:
        for start in range(0, len(rows), BATCH):
            body = json.dumps({"rows": rows[start:start + BATCH]}).encode()
            answer = json.loads(http(f"{site}/investments/api/prices/ingest/", data=body, headers={**auth, "Content-Type": "application/json"}, timeout=120))
            written += answer.get("written", 0)
            for item in answer.get("rejected", []):
                failures.append(f"rejected row {item['row']}: {item['error']}")
    for f in failures:
        print("  -", f)
    print(f"{written} price(s) written by the site")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
