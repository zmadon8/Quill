"""Photograph the main pages at phone and desktop widths, for the screenshots workflow.

Run by ``.github/workflows/screenshots.yml`` against a throwaway dev server filled by ``make_screenshot_data``::

    python scripts/screenshots.py --base http://127.0.0.1:8000 --ids ids.json --out screenshots

Credentials come from SCREENSHOT_USER and SCREENSHOT_PASSWORD (set by the workflow). Only requests to the local
server are allowed: anything else is blocked and listed at the end, so a page that reaches for the network shows up.
The script prints file names and failures only, never the environment.
"""
import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

WIDTHS = {"375": {"width": 375, "height": 800}, "1280": {"width": 1280, "height": 900}}


def pages(ids):
    """(file name, path, optional action) for every page. A page whose id is missing is skipped with a note."""
    fee_tabs = ("memos", "payments", "word", "years", "display", "data")
    out = [
        ("home", "/", None),
        ("diary-subjects", "/caselaw/subjects/", None),
        ("diary-reading", "/caselaw/subjects/{subject}/read/", None),
        ("diary-settings", "/caselaw/profile-settings/", None),
        ("fees-dashboard", "/fees/dashboard/", None),
        ("fees-statistics", "/fees/statistics/", None),
        ("fees-memos", "/fees/memos/", None),
        ("fees-new-memo", "/fees/memos/new/", None),
        ("fees-new-payment", "/fees/payments/new/", None),
        ("fees-firm", "/fees/firms/{firm}/", None),
        ("fees-settings", "/fees/settings/", None),
    ]
    out += [(f"fees-settings-{t}", f"/fees/settings/?tab={t}", None) for t in fee_tabs]
    out += [
        ("inv-overview", "/investments/dashboard/", None),
        ("inv-holdings", "/investments/holdings/", None),
        ("inv-investment", "/investments/holdings/{investment}/", None),
        ("inv-buy", "/investments/transactions/buy/", "buy_card"),
        ("inv-add-type", "/investments/holdings/add/", None),
        ("inv-add-investment", "/investments/holdings/add/details/?kind=share", None),
        ("inv-add-fund", "/investments/holdings/add/details/?kind=fund", None),
        ("inv-sell", "/investments/transactions/sell/", None),
        ("inv-reports", "/investments/reports/", None),
        ("inv-settings", "/investments/settings/", None),
        ("settings-my", "/my-settings/", None),
        ("settings-suite", "/settings/", None),
        ("admin-users", "/users/", None),
    ]
    return out


def buy_card(page):
    """The Buy page as a person leaves it: a second card added and the "More" fold open on the first."""
    add = page.locator("#add-row")
    if add.count() and add.is_visible():
        add.click()
    for fold in page.locator("details.more-fields").all():
        fold.evaluate("el => { el.open = true; }")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--ids", default="ids.json")
    parser.add_argument("--out", default="screenshots")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    ids = json.loads(Path(args.ids).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    host = urlparse(args.base).netloc
    blocked, failed, taken = [], [], 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for label, size in WIDTHS.items():
            context = browser.new_context(viewport=size)

            def gate(route, request):
                if urlparse(request.url).netloc == host:
                    route.continue_()
                else:
                    blocked.append(request.url.split("?")[0])
                    route.abort()

            context.route("**/*", gate)
            page = context.new_page()
            page.goto(f"{args.base}/login/")
            page.fill("input[name=username]", os.environ["SCREENSHOT_USER"])
            page.fill("input[name=password]", os.environ["SCREENSHOT_PASSWORD"])
            page.locator("form button[type=submit], form input[type=submit]").first.click()
            page.wait_for_load_state("load")
            if "/login/" in page.url:
                print("Login failed", file=sys.stderr)
                return 1
            for name, path, action in pages(ids):
                try:
                    path = path.format(**ids)
                except KeyError as exc:
                    failed.append(f"{name}: no id {exc}")
                    continue
                if "None" in path:
                    failed.append(f"{name}: id missing")
                    continue
                try:
                    response = page.goto(args.base + path)
                    page.wait_for_load_state("load")
                    try:  # fetch-driven content (Fees KPIs, Investments overview) fills in after load
                        page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    if response is None or response.status >= 400:
                        failed.append(f"{name}: HTTP {response.status if response else 'none'}")
                        continue
                    if action == "buy_card":
                        buy_card(page)
                    page.screenshot(path=str(out / f"{name}-{label}.png"), full_page=True)
                    taken += 1
                except Exception as exc:  # one broken page must not stop the others
                    failed.append(f"{name}: {type(exc).__name__}")
            context.close()
        browser.close()

    print(f"{taken} screenshots written to {out}")
    for item in sorted(set(blocked)):
        print(f"BLOCKED external request: {item}")
    for item in failed:
        print(f"FAILED {item}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
