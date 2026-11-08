# ruff: noqa
import re, sys, os
sys.path.insert(0, os.path.dirname(__file__))
for _f in ("lib.py", "pages_a.py", "pages_b.py", "pages_c.py"):
    p = os.path.join(os.path.dirname(__file__), _f)
    s = open(p, encoding="utf-8").read()
    s2 = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)
    if s2 != s:
        open(p, "w", encoding="utf-8").write(s2)

from lib import *
import pages_a as A, pages_b as B, pages_c as C

made = []
for fn in (A.dashboard, A.start, A.search, A.holdings, A.add1, A.add2, A.add2f, A.add3, A.add4, A.addalt,
           B.inv_share, B.inv_fund, B.inv_alt, B.inv_foreign, B.inv_delete,
           B.txn_list, B.txn_buy, B.txn_sell, B.txn_refused, B.txn_opening, B.txn_transfer, B.txn_switch, B.txn_confirm, B.txn_awaiting, B.txn_complete, B.import_statement,
           B.dividends, B.dividend_new, B.corp, B.brokers, B.broker_detail,
           C.performance, C.charts, C.value, C.annual, C.reports, C.report_yearly, C.report_brokers, C.history, C.alerts,
           C.admin_prices, C.admin_upload, C.admin_history, C.admin_catalogue, C.admin_catalogue_item):
    made.append(fn())
C.settings_all()
made += ["settings-general.html", "settings-brokers.html", "settings-alerts.html", "settings-display.html", "settings-pages.html", "settings-insights.html"]

groups = [
    ("Overview", [("dashboard.html", "Dashboard (Statement layout, insights in a right-hand column)"), ("start.html", "Getting started (new profile, empty state)"), ("search.html", "Header search, open")]),
    ("Holdings: investments", [("holdings.html", "Investments list"), ("add-1.html", "Add investment, step 1: type"), ("add-2.html", "Step 2: find a share"), ("add-2-fund.html", "Step 2: find a mutual fund plan"),
                               ("add-3.html", "Step 3: confirm"), ("add-4.html", "Step 4: details and what next"), ("add-alt.html", "Add an alternative investment"),
                               ("inv-share.html", "One investment: a share"), ("inv-fund.html", "One investment: a mutual fund (folios, SIP)"), ("inv-alt.html", "One investment: alternative (dated values)"),
                               ("inv-foreign.html", "One investment: foreign (dollars and rupees)"), ("inv-delete.html", "Admin: delete an investment")]),
    ("Holdings: transactions", [("transactions.html", "Transactions list"), ("txn-new-buy.html", "Add a purchase"), ("txn-new-sell.html", "Add a sale (limits, first in first out)"), ("txn-edit-refused.html", "An edit that is refused"),
                                ("txn-opening.html", "Opening balance"), ("txn-transfer.html", "Transfer"), ("txn-switch.html", "Fund switch"), ("txn-new-awaiting.html", "Add a purchase awaiting allotment"), ("txn-complete.html", "Complete a purchase awaiting allotment"), ("txn-to-confirm.html", "To complete (awaiting allotment, SIP entries)"), ("import-statement.html", "Import a statement (review)")]),
    ("Holdings: other", [("dividends.html", "Dividends"), ("dividend-new.html", "Add a dividend"), ("corporate-actions.html", "Corporate actions"), ("brokers.html", "Brokers"), ("broker-detail.html", "One broker")]),
    ("Reports", [("performance.html", "Performance"), ("charts.html", "Charts"), ("value.html", "Total Portfolio Value"), ("annual.html", "Annual Report"), ("reports.html", "Other reports (index)"),
                 ("report-yearly.html", "Year-by-year returns"), ("report-compare-brokers.html", "Compare brokers"), ("history.html", "History")]),
    ("Alerts and settings", [("alerts.html", "Alerts and guardrails"), ("settings-general.html", "Settings: General"), ("settings-brokers.html", "Settings: Brokers and default brokers"),
                             ("settings-alerts.html", "Settings: Alerts"), ("settings-display.html", "Settings: Display"), ("settings-pages.html", "Settings: Pages"), ("settings-insights.html", "Settings: Insights"),
                             ("admin-prices.html", "Admin: Price sources"), ("admin-upload.html", "Admin: Upload price history (dry run)"), ("admin-price-history.html", "Admin: Price history (pruning, archive, pins)"), ("admin-catalogue.html", "Admin: Investment catalogue (all profiles)"), ("admin-catalogue-item.html", "Admin: one investment, details and price history")]),
]
sections = ""
for g, items in groups:
    li = "".join(f'<li><a href="{h}">{t}</a><span>{h}</span></li>' for h, t in items)
    sections += f"<h2>{g}</h2><ul>{li}</ul>"
total = sum(len(i) for _, i in groups)
html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Investments: mockups</title><link rel="stylesheet" href="mockup.css"></head>
<body><div class="page"><header class="top"><div class="brand">Investments<small>Mockups</small></div></header>
<div class="titlebar"><h1 class="t">Mockups: every page</h1><div class="meta">{total} pages \u00b7 6 November 2026</div></div>
<p class="lead">Static pages in the suite's Chambers design. All people, holdings, prices and amounts are invented. Nothing here saves anything. The Auto / Full control works (it changes every rupee amount on the page).</p>
<div class="idx">{sections}</div>
<div class="anno"><h4>Design notes</h4><ul><li>Colours and type are the suite's own tokens. Two <b>proposed</b> new tokens: gain green <code>#2d5a3d</code> and loss brick <code>#a8441f</code>, both distinct from the oxblood used for actions and alerts.</li>
<li>No web fonts are loaded, as in the live suite, so serif and sans fall back to fonts already on the device.</li><li>Charts are inline SVG with no library. Every chart distinguishes lines by pattern as well as shade.</li></ul></div></div></body></html>"""
html = html.replace("\\u00b7", "\u00b7")
open(OUT + "index.html", "w", encoding="utf-8").write(html)
print(len(made) + 1, "pages written;", total, "listed")
