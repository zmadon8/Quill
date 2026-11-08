# ruff: noqa
"""Reports, alerts, settings, admin pages."""
from lib import *
from pages_a import tags_for


def ctl(label, opts, on):
    seg = "".join(f'<span class="{"on" if o == on else ""}">{o}</span>' for o in opts)
    return f'<div class="sel"><span>{label}</span><div class="radio" style="font-size:14px">{seg}</div></div>'


def alpha_bar(a):
    w = min(abs(a) * 5, 60)
    col = "var(--gain)" if a >= 0 else "var(--loss)"
    side = f"margin-left:60px;" if a >= 0 else f"margin-left:{60 - w}px;"
    return f'<span style="display:inline-block;width:120px;height:8px;position:relative;vertical-align:middle;background:linear-gradient(90deg,transparent 59px,var(--s3) 59px,var(--s3) 60px,transparent 60px)"><i style="position:absolute;top:0;height:8px;width:{w}px;left:{60 if a>=0 else 60-w}px;background:{col}"></i></span>'


def performance():
    rows_ = []
    for r in R:
        a = r["x"] - r["b"]
        from_ = "<span class='tag amb'>from 18 Mar 2026</span>" if r["name"].startswith("Larsen") else ""
        sec = SECT.get(r["name"])
        if sec:
            sname, sx = sec
            sc = [(sname, ""), (pct(sx, signed=False), "r"), (pct(r["x"] - sx), "r")]
        else:
            sc = [('<span class="na">none set</span>', ""), ("–", "r"), ("–", "r")]
        rows_.append([(f'{r["name"]}{from_}<small>{r["typ"]}</small>', "nm"), (pct(r["x"], signed=False), "r"),
                      (pct(r["b"], signed=False), "r"), (pct(a), "r")] + sc)
    t = table([("Investment", "sorted"), ("XIRR", "r"), ("Nifty 50 XIRR", "r"), ("Alpha", "r"),
               ("Sectoral index", ""), ("Sector XIRR", "r"), ("Alpha vs sector", "r")], rows_,
              foot=f'<td>Whole portfolio</td><td class="r">{PORT_XIRR:.1f}%</td><td class="r">{BENCH_XIRR:.1f}%</td><td class="r">{pct(PORT_XIRR-BENCH_XIRR)}</td><td></td><td></td><td></td>')
    body = f"""<div class="sec" style="margin-top:18px"><div style="display:flex;gap:18px;flex-wrap:wrap;align-items:flex-end">{ctl("Measure",["XIRR","CAGR"],"XIRR")}{ctl("Period",["1 yr","3 yr","5 yr","Custom"],"3 yr")}<span class="chk" style="padding-bottom:10px"><i class="on"></i>Include dividends</span></div>
<div class="acts"><span class="btn q">Export to Excel</span></div></div>
<p class="hint" style="margin:0 0 8px">3 years to 6 Nov 2026. The value on 6 Nov 2023 counts as the opening investment. A holding bought inside the period uses only the days it was held, and the indices are shown over the same shorter span. The Default Index is <b style="color:var(--ink)">Nifty 50</b> (Settings > General).</p>
{t}"""
    return page("performance.html", "Performance", "Reports", "Performance", body, h1="Performance", meta="XIRR · 3 years",
                anno=["Every investment is compared with the one Default Index set in Settings. The last three columns exist only because the sectoral index is switched on in Settings; switched off, they and the field on each investment disappear.",
                      "With “CAGR” selected the table shows each investment's own price growth instead, and leaves out alternative investments (no price history).",
                      "Alpha is worked out by replaying your exact cash flows into the index: each buy purchases index units that day, each sale sells them. The XIRR of that replay is the index XIRR. The same replay is done for the sectoral index."])


def charts():
    N = 61
    labs = [(0, "Nov 2021"), (12, "Nov 2022"), (24, "Nov 2023"), (36, "Nov 2024"), (48, "Nov 2025"), (60, "Nov 2026")]
    def rb(seed, end):
        rr = random.Random(seed)
        w = [0.0]
        for _ in range(N - 1):
            w.append(w[-1] + rr.gauss(0.004, 0.02))
        base = [(1 + w[i] * 1.0) for i in range(N)]
        k = end / base[-1]
        return [100 * b * (1 + (k - 1) * (i / (N - 1))) for i, b in enumerate(base)]
    port, n50, mid, sen = rb(1, 1.78), rb(2, 1.62), rb(3, 1.95), rb(4, 1.58)
    comb = line_chart([("Portfolio", port, "solid"), ("Nifty 50", n50, "dash"), ("Midcap 150", mid, "dot"), ("Sensex", sen, "mid")], labs, h=300, fmt=lambda v: f"{v:.0f}", ymin=80)
    leg = '<div class="legend"><span><i></i>Portfolio (money added or withdrawn does not cause jumps)</span><span><i class="d"></i>Nifty 50</span><span><i class="t"></i>Nifty Midcap 150</span><span><i style="border-color:var(--s3)"></i>Sensex</span></div>'
    a, b, c, d = rb(5, 2.1), rb(6, 1.45), rb(7, 1.7), rb(8, 1.62)
    side = line_chart([("HDFC Bank", a, "solid"), ("Infosys", b, "dot"), ("L&T", c, "mid"), ("Nifty 50", d, "dash")], labs, h=260, fmt=lambda v: f"{v:.0f}", ymin=80)
    body = f"""<div class="sec" style="margin-top:18px"><div style="display:flex;gap:18px;flex-wrap:wrap;align-items:flex-end">{ctl("Chart",["Combined","Side by side"],"Combined")}{ctl("Period",["1 mo","6 mo","1 yr","3 yr","5 yr","All","Custom"],"5 yr")}{sel("Compare with","Nifty 50, Midcap 150, Sensex")}</div>
<div class="acts"><span class="btn q">Table view</span><span class="btn q">Export to Excel</span></div></div>
<p class="hint" style="margin:0">All lines are rebased to 100 on the start date. Alternative investments: <span class="tag ink">Averaged out</span> <span class="tag">Unchanged</span> between updates.</p>
<div class="sec"><h2>A. Whole portfolio against indices</h2></div>{comb}{leg}
<div class="sec"><h2>B. Chosen holdings side by side</h2></div>{side}
<p class="hint">A holding with less history than the period starts on its first available date, with a note.</p>"""
    return page("charts.html", "Charts", "Reports", "Charts", body, h1="Charts", meta="Rebased to 100",
                anno=["Hand-drawn SVG, no chart library. Each line has its own pattern as well as its own label, so colour is never the only signal.",
                      "Hovering shows the values on a date. Long ranges are thinned on the server (weekly points) to keep the page small.", "If the Admin has switched pruning on, points before the cutoff are monthly and the page says so, for example “monthly data before Nov 2021”."])


def value():
    N = 61
    pts = [8 + (VALUE / 1e5 - 8) * (i / (N - 1)) ** 1.2 + random.Random(i).gauss(0, 1.1) for i in range(N)]
    pts[-1] = VALUE / 1e5
    labs = [(0, "Nov 2021"), (12, "Nov 2022"), (24, "Nov 2023"), (36, "Nov 2024"), (48, "Nov 2025"), (60, "Nov 2026")]
    ch = line_chart([("Value", pts, "solid")], labs, h=250, fmt=lambda v: f"₹{v:.1f} lac", yfmt=lambda v: f"{v:.0f}")
    body = f"""<div class="strip"><div class="f"><div class="lab">Total Portfolio Value</div><div class="fig">{money(VALUE)}</div></div>
<div class="f"><div class="lab">As at</div><div class="fig" style="font-size:24px;padding-top:6px">6 Nov 2026</div></div>
<div class="f"><div class="lab">Dividends</div><div class="fig" style="font-size:20px;padding-top:9px;color:var(--muted)">not included</div></div></div>
<p class="hint">Holdings at the saved price on or before the date, plus alternative investments at their value for that date (averaged out between updates). Change the date in the strip above to see any past day.</p>
<div class="cols th"><div><div class="sec"><h2>By type</h2></div>{bars_rows([("Shares",T_SHARE),("Mutual funds",T_FUND),("Alternative",T_ALT),("Foreign",T_FOR)],total=50)}</div>
<div><div class="sec"><h2>By portfolio</h2></div>{bars_rows([("Ziyad",87.4),("Spouse",12.6)],total=100)}</div>
<div><div class="sec"><h2>By broker</h2></div>{bars_rows([(k, v/VALUE*100) for k, v in sorted(BV.items(), key=lambda kv: -kv[1])],total=40)}</div></div>
<div class="sec"><h2>Over time</h2><div class="acts"><span class="btn q">Export to Excel</span></div></div>{ch}"""
    return page("value.html", "Total Portfolio Value", "Reports", "Total Portfolio Value", body, h1="Total Portfolio Value", meta="Formerly net worth",
                anno=["Report shows which treatment of alternative investments was used, because it changes the value between updates."])


def annual():
    gains = table([("Bought", ""), ("Sold", ""), ("Investment", ""), ("Days held", "r"), ("Cost", "r"), ("Proceeds", "r"), ("Gain", "r"), ("Term", "")],
                  [["3 Jun 2022", "12 Dec 2025", ("Infosys", "nm"), ("1,288", "r"), (money(52000), "r"), (money(60700), "r"), (money(8700, signed=True), "r"), "Long-term"],
                   ["1 Apr 2018 " + tag("Estimated", "dash"), "30 Oct 2025", ("ITC", "nm"), ("2,760", "r"), (money(26200), "r"), (money(42800), "r"), (money(16600, signed=True), "r"), "Long-term" + tag("Cost override", "amb")],
                   ["14 Aug 2025", "22 Jan 2026", ("SBI Small Cap Fund", "nm"), ("161", "r"), (money(40000), "r"), (money(45600), "r"), (money(5600, signed=True), "r"), "Short-term"]])
    body = f"""<div class="sec" style="margin-top:18px"><div style="display:flex;gap:14px;flex-wrap:wrap;align-items:flex-end">{sel("Financial year","2025-26")}{sel("Long-term cutoff for this year","12 months (default from Settings)")}<span class="chk" style="padding-bottom:8px"><i class="on"></i>Include dividends</span></div>
<div class="acts"><span class="btn q">Export to Excel</span></div></div>
{table([("", ""), ("2025-26", "r")], [
 ["1. Starting portfolio value, 31 Mar 2025", (money(7240000), "r")], ["2. Amount invested", (money(680000), "r")], ["3. Amount sold", (money(149100), "r")],
 ["4. Amount re-invested (2 less 3)", (money(531000), "r")],
 ["5. Capital gains, short-term", (money(5600, signed=True), "r")], ["&nbsp;&nbsp;&nbsp;Capital gains, long-term", (money(25300, signed=True), "r")],
 ["6. XIRR for the year", ("15.1%", "r")], ["&nbsp;&nbsp;&nbsp;Nifty 50 return for the year", ("12.4%", "r")],
 ["7. Ending portfolio value, 31 Mar 2026", (money(8630000), "r")]],
 foot='<td>Unrealised gain at year end</td><td class="r">'+money(2040000, signed=True)+'</td>')}
<div class="sec"><h2>Sale by sale</h2></div>{gains}
<div class="cols eq"><div class="panel"><h3>Also in this report</h3><ul class="hint" style="margin:0;padding-left:18px"><li>Dividends received {money(94000)}, tax deducted {money(9400)}</li><li>Holdings at year end, with allocation</li><li>The year's transaction report</li><li>A breakdown by portfolio (All Portfolios view)</li></ul></div>
<div class="panel"><h3>Per-lot cost override</h3><p class="hint" style="margin:0">For special cases such as grandfathered holdings, a lot can have its cost overridden with a note. Overridden lots are tagged in every table. The program is a record-keeping aid, not tax advice; confirm treatment with your CA.</p></div></div>"""
    return page("annual.html", "Annual Report", "Reports", "Annual Report", body, h1="Annual Report", meta="Financial year 2025-26",
                anno=["The seven numbered lines follow your plan exactly. A completed year is as at the end of 31 March; the current year is as at today."])


def reports():
    items = [("Year-by-year returns", "Each financial year's return next to the benchmark's", "report-yearly.html"),
             ("Best and worst performers", "Top and bottom five for a period, with rupees contributed", ""),
             ("Benchmark scoreboard", "How many holdings beat their own benchmark", ""),
             ("Dividend report", "By year and holding, with yield on cost", ""),
             ("Total income summary", "Dividends plus realised gains for each year", ""),
             ("Lots turning long-term soon", "Within 30, 60 or 90 days", ""),
             ("Unrealised gains and losses by lot", "An “if sold today” view; check with your CA", ""),
             ("Concentration", "Top 10 share and a limit you set", ""),
             ("Cost of funds", "Expense ratios and the weighted average", ""),
             ("Data check", "Stale prices, missing prices, holdings with no code or benchmark", ""),
             ("Compare portfolios", "Two portfolio owners side by side", ""),
             ("Compare brokers", "Performance of everything held with each broker", "report-compare-brokers.html")]
    lis = "".join(f'<li><a href="{h or "#"}"><b style="font:400 18px var(--font-serif)">{t}</b></a><span>{d}</span></li>' for t, d, h in items)
    return page("reports.html", "Other reports", "Reports", "Other reports", f'<div class="idx"><ul>{lis}</ul></div>', h1="Other reports", meta="All export to Excel", ctx="pb")


def report_yearly():
    cats = ["22-23", "23-24", "24-25", "25-26", "26-27 to date"]
    ch = grouped_bars(cats, [4, 28, 11, 15, 9], [0, 29, 6, 12, 7])
    body = f"""{ch}<div style="height:16px"></div>
{table([("Financial year", ""), ("Portfolio", "r"), ("Nifty 50", "r"), ("Difference", "r")], [["2022-23", ("4.1%", "r"), ("0.6%", "r"), (pct(3.5), "r")], ["2023-24", ("27.6%", "r"), ("28.6%", "r"), (pct(-1.0), "r")], ["2024-25", ("11.0%", "r"), ("5.9%", "r"), (pct(5.1), "r")], ["2025-26", ("15.1%", "r"), ("12.4%", "r"), (pct(2.7), "r")], ["2026-27 to date", ("9.0%", "r"), ("7.1%", "r"), (pct(1.9), "r")]])}"""
    return page("report-yearly.html", "Year-by-year returns", "Reports", "Other reports", body, h1="Year-by-year returns", meta="Portfolio against Nifty 50", ctx="pb",
                anno=["Solid bar and hatched bar differ by pattern as well as shade. Every chart has a table underneath it."], crumb='<a href="reports.html">Other reports</a> / Year-by-year returns')


def report_brokers():
    N = 61
    labs = [(0, "Nov 2021"), (12, "Nov 2022"), (24, "Nov 2023"), (36, "Nov 2024"), (48, "Nov 2025"), (60, "Nov 2026")]
    def rb(seed, end):
        rr = random.Random(seed)
        w = [0.0]
        for _ in range(N - 1):
            w.append(w[-1] + rr.gauss(0.004, 0.018))
        base = [1 + x for x in w]
        k = end / base[-1]
        return [100 * b * (1 + (k - 1) * (i / (N - 1))) for i, b in enumerate(base)]
    ch = line_chart([("Zerodha", rb(11, 1.9), "solid"), ("Groww", rb(12, 1.55), "dot"), ("Direct", rb(13, 2.05), "mid"), ("Nifty 50", rb(14, 1.62), "dash")], labs, h=260, fmt=lambda v: f"{v:.0f}", ymin=80)
    t = table([("Broker", ""), ("Invested", "r"), ("Current value", "r"), ("Gain", "r"), ("XIRR", "r"), ("Benchmark XIRR", "r"), ("Alpha", "r")],
              [[("Zerodha", "nm"), (money(BC["Zerodha"]), "r"), (money(BV["Zerodha"]), "r"), (money(BV["Zerodha"]-BC["Zerodha"], signed=True), "r"), ("15.3%", "r"), ("11.6%", "r"), (pct(3.7), "r")],
               [("Groww", "nm"), (money(BC["Groww"]), "r"), (money(BV["Groww"]), "r"), (money(BV["Groww"]-BC["Groww"], signed=True), "r"), ("10.2%", "r"), ("11.4%", "r"), (pct(-1.2), "r")],
               [("Direct (fund house)", "nm"), (money(BC["Direct"]), "r"), (money(BV["Direct"]), "r"), (money(BV["Direct"]-BC["Direct"], signed=True), "r"), ("17.4%", "r"), ("12.1%", "r"), (pct(5.3), "r")]])
    body = f"""<div class="sec" style="margin-top:18px"><div style="display:flex;gap:14px;flex-wrap:wrap">{sel("Period","3 years")}{sel("Compare","Zerodha, Groww, Direct")}</div><div class="acts"><span class="btn q">Export to Excel</span></div></div>{t}
<div class="sec"><h2>Rebased to 100</h2></div>{ch}
<div class="ban wa"><span>Differences mostly reflect <b>which investments</b> each broker holds and <b>when</b> they were bought, not the quality of the broker. A transfer between brokers counts as money leaving one and arriving at the other at that day's market value.</span></div>"""
    return page("report-compare-brokers.html", "Compare brokers", "Reports", "Other reports", body, h1="Compare brokers", meta="Benchmark replays the same cash flows", ctx="pb",
                crumb='<a href="reports.html">Other reports</a> / Compare brokers')


def history():
    t = table([("When", "sorted d"), ("Who", ""), ("Record", ""), ("What changed", ""), ("", "")],
              [["6 Nov 2026, 11:42", "Ziyad", "Transaction · Reliance Industries", "Added: buy 20 units at ₹1,320.00, Zerodha", ""],
               ["5 Nov 2026, 19:05", "Ziyad", "Corporate action · Infosys", "Confirmed bonus 1 : 1 as applied", ""],
               ["3 Nov 2026, 09:18", "Spouse", "Transaction · ITC", "Units <s>1,000</s> to 900; price <s>₹262.00</s> to ₹262.00; date marked estimated", ""],
               ["30 Oct 2026, 14:30", "Ziyad", "Transaction · ITC", "<b>Deleted:</b> buy 40 units, 12 Jan 2024, Groww", ("<span class='btn q sm'>Restore</span>", "act")],
               ["14 Oct 2026, 08:02", "Ziyad", "Value · Gold", "Value <s>₹9,150</s> to ₹9,400 a gram", ""]])
    body = f"""<div class="sec" style="margin-top:18px"><div style="display:flex;gap:14px;flex-wrap:wrap">{sel("Investment","All")}{sel("Record type","All")}{sel("Dates","All dates")}</div><div class="acts"><span class="btn q">Export to Excel</span></div></div>{t}
<p class="hint">History entries cannot be changed or removed. A restore is refused, and the reason shown, if it would break the selling limits.</p>"""
    return page("history.html", "History", "Reports", "History", body, h1="History", meta="Every edit and deletion, kept permanently", ctx="none",
                anno=["Kept in its own table, so the nightly clean-up that trims the Case Law Diary's edit history never touches it."])


def alerts():
    body = f"""<div class="tabs"><a class="on">Active (3)</a><a>Guardrails (4)</a><a>Dismissed</a></div>
<div style="border-top:1px solid var(--ink)">
<div style="padding:16px 0;border-bottom:1px solid var(--hair)"><div style="display:flex;justify-content:space-between;gap:20px"><div><h3 style="font:400 22px var(--font-serif);margin:0">Asian Paints <span class="tag ox">Rule B · Below cost</span> <span class="tag">Ziyad</span></h3>
<p class="hint" style="margin:6px 0 0">Triggered 4 Nov 2026 at ₹2,480. Loss against your average cost of ₹3,150 is <span class="l">−21.3%</span> (−₹60,300). A sale now would be <b style="color:var(--ink)">long-term</b> for all 90 units. Trails its benchmark by 16.3 points a year.</p></div>
<div class="acts"><span class="btn q sm">Dismiss</span><span class="btn q sm">Snooze</span><span class="btn q sm">Re-arm at …</span></div></div></div>
<div style="padding:16px 0;border-bottom:1px solid var(--hair)"><div style="display:flex;justify-content:space-between;gap:20px"><div><h3 style="font:400 22px var(--font-serif);margin:0">HDFC Bank FD <span class="tag amb">Maturity</span></h3>
<p class="hint" style="margin:6px 0 0">Matures on 14 Mar 2027, in 128 days. Alternative investments can only use alerts based on their last entered value.</p></div><div class="acts"><span class="btn q sm">Dismiss</span><span class="btn q sm">Snooze</span></div></div></div>
<div style="padding:16px 0;border-bottom:1px solid var(--hair)"><div style="display:flex;justify-content:space-between;gap:20px"><div><h3 style="font:400 22px var(--font-serif);margin:0">Larsen & Toubro <span class="tag ink">Rule A · Fall</span></h3>
<p class="hint" style="margin:6px 0 0">Fell 38.0% on 4 Nov 2026 against the previous close. No corporate action is recorded. <a href="corporate-actions.html" style="text-decoration:underline">Possible split? Check.</a></p></div><div class="acts"><span class="btn q sm">Dismiss</span><span class="btn q sm">Snooze</span></div></div></div></div>
<div class="sec"><h2>Guardrails on specific investments</h2><div class="acts"><span class="btn p sm">Add guardrail</span></div></div>
{table([("Investment", ""), ("Portfolio", ""), ("Rule", ""), ("Level", "r"), ("Status", "")],
 [[("Reliance Industries", "nm"), "Ziyad", "Stop-loss", ("₹1,150.00", "r"), '<span class="sq"></span>Armed'], [("HDFC Bank", "nm"), "Ziyad", "Target gain", ("+40% on cost", "r"), '<span class="sq"></span>Armed'],
  [("Infosys", "nm"), "Ziyad", "Fall from peak since purchase", ("−15%", "r"), '<span class="sq"></span>Armed'], [("Asian Paints", "nm"), "Ziyad", "Price level", ("₹2,600.00", "r"), '<span class="sq f"></span>Triggered']])}
<p class="hint">A specific guardrail replaces the global rule for that holding. Global rules are in <a href="settings-alerts.html" style="text-decoration:underline">Settings</a>. An alert is a prompt; the decision to sell stays with you.</p>"""
    return page("alerts.html", "Alerts", "Alerts", None, body, h1="Alerts", meta="Based on daily prices", ctx="none",
                anno=["Alerts are worked out after each price update and when a page is opened. Proposed: an optional daily email for alerts that triggered overnight."])


# ------------------------------------------------------------------ settings
def settings(fn, tab, title, inner, anno=None):
    return page(fn, "Settings · " + title, "Settings", tab, f'<div class="form">{inner}</div>', h1="Settings", meta=f"{title} · profile Madon", ctx="none", anno=anno)


def sw(on):
    return f'<span class="sw"><span class="{"on" if on else ""}">On</span><span class="{"" if on else "on"}">Off</span></span>'


def settings_all():
    settings("settings-general.html", "General", "General", f"""
<div class="panel"><h3>Indices</h3>
<div class="row" style="margin:0 0 14px">{fld("Default Index","Nifty 50","w2 sel2","The main index for every investment in the program. Changing it recalculates every comparison.")}</div>
<div class="row" style="margin:0"><div class="fld"><label>Use a sectoral index as well</label>{sw(True)}<span class="note" style="max-width:520px">When on, each investment can have a second, sectoral index (for example Nifty Bank for HDFC Bank), set on its details page, and comparisons against it appear beside the Default Index. When off, that field and those columns are not available anywhere.</span></div></div></div>
<div class="row">{fld("Long-term cutoff, default for future years","12 months","sel2","Chosen manually for each year in the Annual Report")}</div>
<div class="row">{fld("Alternative investments between updates","Averaged out","w2 sel2","Or: unchanged until the next update")}</div>
<div class="row">{fld("SIP entries","Pending until I confirm","w2 sel2","Or: created as final (still editable)")}</div>
<div class="row">{fld("Pending corporate actions","Tag and banner","w2 sel2","Or: block that holding's value and XIRR until confirmed")}</div>
<div class="row"><div class="fld"><label>Include dividends in XIRR, by default</label>{sw(True)}</div></div>
<div class="acts-row"><span class="btn p">Save settings</span></div>""",
             ["Default Index and the sectoral switch are the owner decisions of 6 Nov 2026. SIP entries pending, and pending corporate actions shown as a tag and banner, are the defaults recorded in the spec."])
    settings("settings-brokers.html", "Brokers", "Brokers", f"""
<h3 style="font:400 22px var(--font-serif);margin:0 0 8px">Default broker for each type of investment</h3>
{table([("Type of investment", ""), ("Default broker", ""), ("", "")],
 [["Shares and ETFs", fld("", "Zerodha", "sel2 sm", "") , ""], ["Mutual funds", fld("", "Direct (fund house)", "sel2", ""), ""], ["Alternative investments", fld("", "None", "sel2 sm", "You choose on each entry"), ""], ["Foreign investments", fld("", "Interactive Brokers", "sel2", ""), ""]])}
<p class="hint">A default is pre-filled on new purchases of that type and can be changed on any entry. <b>None</b> leaves the field empty so you must choose. Every purchase and sale must record a broker.</p>
<div class="sec"><h2>Your brokers</h2><div class="acts"><span class="btn p sm">Add broker</span></div></div>
{table([("Broker", ""), ("Used on", "r"), ("Status", ""), ("", "")],
 [[("Zerodha", "nm"), ("48", "r"), "Shown", ("<a>rename</a><a>hide</a>", "act")], [("Groww", "nm"), ("22", "r"), "Shown", ("<a>rename</a><a>hide</a>", "act")], [("Direct (fund house)", "nm"), ("71", "r"), "Shown", ("<a>rename</a><a>hide</a>", "act")],
  [("Interactive Brokers", "nm"), ("6", "r"), "Shown", ("<a>rename</a><a>hide</a>", "act")], [("Self (PPF, FD, gold)", "nm"), ("9", "r"), "Shown", ("<a>rename</a><a>hide</a>", "act")], [("HDFC Securities", "nm"), ("0", "r"), "Hidden", ("<a>show</a>", "act")]])}""",
             ["There is no built-in “no broker” option: add a broker of your own (like “Self”) where none applies."])
    settings("settings-alerts.html", "Alerts", "Alerts", f"""
<div class="panel"><h3>Rule A · against the previous close {sw(True)}</h3>
<div class="row" style="margin:0">{fld("Fall in a day","−5%","sm")}{fld("Rise in a day","+8%","sm")}{fld("Over a longer window (optional)","−15% over 7 days","w2")}</div></div>
<div class="panel"><h3>Rule B · against your cost {sw(True)}</h3>
<div class="row" style="margin:0">{fld("Loss against average cost","20%","sm")}{fld("Gain against average cost","40%","sm")}</div>
<p class="hint" style="margin:8px 0 0">Uses the average cost of units still held after first-in-first-out sales. In the All Portfolios view it is checked per portfolio.</p></div>
<div class="row"><div class="fld"><label>A guardrail on one investment replaces the global rule for it</label>{sw(True)}</div></div>
<div class="row"><div class="fld"><label>Email me about alerts that triggered overnight</label>{sw(False)}<span class="note">Uses the suite's email settings.</span></div></div>
<div class="acts-row"><span class="btn p">Save settings</span></div>""")
    settings("settings-display.html", "Display", "Display", f"""
<div class="row"><div class="fld"><label>Number display, starting choice</label><div class="radio"><span class="on">Auto</span><span>Full numbers</span></div><span class="note">Auto shows ₹2.41 cr, ₹24.13 lac, ₹85.40 k. Full shows ₹2,41,26,000. Exact figures appear on hover and in every export.</span></div></div>
<div class="row">{fld("Page to open after login","Dashboard","w2 sel2")}</div>
<div class="row"><div class="fld"><label>Table density</label><div class="radio"><span class="on">Comfortable</span><span>Compact</span></div></div></div>
<div class="acts-row"><span class="btn p">Save settings</span></div>""")
    pg = ["Dashboard", "Performance", "Charts", "Investments", "Transactions", "Dividends", "Corporate actions", "Total Portfolio Value", "Annual Report", "Alerts", "Brokers", "History", "Other reports"]
    rows_ = [[(p, "nm"), ('<span class="chk"><i class="on"></i>Shown</span>' if p not in ("Corporate actions",) else '<span class="chk"><i></i>Hidden</span>'), ""] for p in pg]
    rows_.append([("Settings", "nm"), '<span class="hint">Always shown</span>', ""])
    settings("settings-pages.html", "Pages", "Pages", f"""<p class="lead">Hiding a page only removes it from the menu and from links. The data is still recorded, calculated and backed up, and you can show the page again at any time.</p>
{table([("Page", ""), ("Menu", ""), ("", "")], rows_)}
<div class="acts-row"><span class="btn p">Save</span></div>""")
    kinds = ["Portfolio XIRR above or below the benchmark, and what led it", "A holding well below cost and trailing its benchmark", "Purchases turning long-term within 60 days",
             "A holding above the concentration limit", "Dividends this year against last year", "Holdings with stale prices", "Maturing alternative investments"]
    settings("settings-insights.html", "Insights", "Insights", f"""<p class="lead">Insights are short statements worked out from your data by fixed rules, not AI. They describe what the data shows and never say whether to buy or sell.</p>
{table([("Type of insight", ""), ("", "")], [[(k, ""), '<span class="chk"><i class="on"></i>On</span>'] for k in kinds])}
<div class="row" style="margin-top:14px">{fld("Concentration limit for one holding","15% of portfolio","w2")}</div><div class="acts-row"><span class="btn p">Save</span></div>""")


# ------------------------------------------------------------------ admin
def admin_prices():
    t = table([("Source", ""), ("Used for", ""), ("Last run", ""), ("Tried", "r"), ("Updated", "r"), ("Failed", "r"), ("Mode", "")],
              [[("Yahoo", "nm"), "Shares, ETFs, indices, foreign, rates", "6 Nov, 2:00 am", ("41", "r"), ("39", "r"), ('<span class="l">2</span>', "r"), "Server"],
               [("AMFI daily file", "nm"), "Mutual fund NAV", "6 Nov, 2:01 am", ("5", "r"), ("5", "r"), ("0", "r"), "Server"],
               [("mfapi.in", "nm"), "Mutual fund history", "12 Oct, backfill", ("1", "r"), ("1", "r"), ("0", "r"), "Server"],
               [("Exchange rates", "nm"), "USD to INR", "6 Nov, 2:00 am", ("1", "r"), ("1", "r"), ("0", "r"), "Server"]])
    fails = table([("Symbol", ""), ("Reason", ""), ("Tried", ""), ("Kept price", "")],
                  [["BAJFINANCE.NS", "Refused (HTTP 429) after 3 tries", "6 Nov, 2:00 am", "5 Nov, stale"], ["Gold – physical", "Manual only: last value 12 Sep", "–", "12 Sep, stale"]])
    body = f"""<div class="sec" style="margin-top:18px"><div></div><div class="acts"><span class="btn q"><a href="admin-price-history.html">Price history: pruning, archive, pins</a></span><span class="btn q"><a href="admin-upload.html">Upload price history</a></span><span class="btn p">Run the update now</span></div></div>{t}
<div class="sec"><h2>Failures in the last run</h2></div>{fails}
<div class="panel"><h3>Local helper <span class="tag">Off</span></h3><p class="hint" style="margin:0">Built but switched off. If the server's fetching proves unreliable, an Admin can switch it on (server setting PRICE_HELPER_ENABLED) and then choose “Helper” or “Either” as the mode for a source. While off, nothing here changes.</p></div>"""
    return page("admin-prices.html", "Price sources", "Settings", "Price sources", body, h1="Price sources", meta="Admin only", ctx="none",
                anno=["Prices are shared by everyone and are kept out of the suite backup, because they can be fetched again. Manual and uploaded prices are never overwritten by an update.",
                      "With the helper on, this page also shows the last helper upload and lets an Admin create or revoke a helper token (shown once, only a hash is stored)."])


def admin_upload():
    t = table([("Instrument", ""), ("Rows", "r"), ("First date", "r"), ("Last date", "r"), ("Basis", ""), ("Problems", "")],
              [[("RELIANCE.NS", "nm"), ("1,731", "r"), ("2 Jan 2020", "r"), ("31 Oct 2026", "r"), "Raw", "None"],
               [("TCS.NS", "nm"), ("1,731", "r"), ("2 Jan 2020", "r"), ("31 Oct 2026", "r"), "Raw", "None"],
               [("BAJFINANCE.NS", "nm"), ("1,729", "r"), ("2 Jan 2020", "r"), ("31 Oct 2026", "r"), "Raw", tag("1-day move of −50% on 3 Nov, no corporate action recorded", "amb")],
               [("NIFTY 50", "nm"), ("1,731", "r"), ("2 Jan 2020", "r"), ("31 Oct 2026", "r"), "Raw", "None"],
               [("XYZ.NS", "nm"), ("–", "r"), ("–", "r"), ("–", "r"), "–", tag("Unknown instrument, skipped", "ox")]])
    body = f"""<div class="stepper"><div class="done"><b>1</b>Upload</div><div class="done"><b>2</b>Map columns</div><div class="on"><b>3</b>Dry run</div><div><b>4</b>Apply</div></div>
<p class="lead">File: <b>history-2020-2026.csv</b> · 6.8 MB · 7,200 rows read. <b>Nothing has been saved.</b></p>
{t}
<div class="ban wa"><span>Where uploaded days overlap fetched days, the two were compared: 3 differences listed in the downloadable report. The uploaded row wins and is marked <i>upload</i>. Nothing marked <i>manual</i> is touched.</span></div>
<div class="acts-row"><span class="btn q">Download report</span><span class="btn q">Cancel</span><span class="btn p">Apply (all or nothing)</span></div>"""
    return page("admin-upload.html", "Upload price history", "Settings", "Price sources", body, h1="Upload price history", meta="Dry run", ctx="none",
                anno=["For files above about 10 MB, an Admin runs the same import from the Render Shell, because a web request is limited to 60 seconds.",
                      "A row whose price basis (raw or split-adjusted) differs from the instrument's is rejected."])


def admin_history():
    cutoff_rows = table([("What", ""), ("Stored now", "r"), ("After pruning", "r"), ("Removed", "r")],
                        [["Daily prices, shares and funds", ("412,860", "r"), ("246,240", "r"), ("166,620", "r")],
                         ["Daily index levels", ("14,310", "r"), ("8,640", "r"), ("5,670", "r")],
                         ["Daily exchange rates", ("5,170", "r"), ("3,010", "r"), ("2,160", "r")],
                         ["Pinned prices (never pruned)", ("6,942", "r"), ("6,942", "r"), ("0", "r")]],
                        foot='<td>Database space freed</td><td></td><td></td><td class="r">about 21 MB of 48 MB</td>')
    pins = table([("Reason", ""), ("Pins", "r"), ("Missing", "r"), ("Approximate", "r")],
                 [["Index value on a transaction date", ("4,418", "r"), ("0", "r"), ("0", "r")],
                  ["Price or index on 31 March", ("2,524", "r"), ("0", "r"), ('<span class="l">3</span>', "r")]])
    body = f"""<div class="cols eq" style="gap:0 36px">
<div>
<div class="panel"><h3>Pruning old daily prices</h3>
<p class="hint" style="margin:0 0 12px">Daily prices older than the years kept below are reduced to one figure a month (the last trading day). Pinned prices are never touched. This setting is for the whole program, because prices are shared by every profile.</p>
<div class="row" style="margin:0 0 12px"><div class="fld"><label>Prune the live database</label>{sw(False)}</div><div class="fld"><label>Prune the price archive</label>{sw(True)}<span class="note">Applies to the archive only while the live database is not pruned.</span></div></div>
<div class="row" style="margin:0">{fld("Years kept in daily detail","5","sm","At least 2")}{fld("Cutoff today","6 Nov 2021","sm ro")}</div></div>
<div class="panel"><h3>Preview: if the live database were pruned now</h3>{cutoff_rows}
<div class="ban wa" style="margin-bottom:0"><span><b>It cannot be undone from inside the program.</b> Detail comes back only by uploading history again. Before the first prune you must download a full archive and confirm you are keeping it.</span></div>
<div class="row" style="margin:14px 0 0"><div class="fld"><label class="chk" style="text-transform:none;letter-spacing:0;font-size:15px;color:var(--ink)"><i></i>&nbsp;I have downloaded the full archive and am keeping it</label></div></div>
<div class="acts-row" style="margin-top:12px"><span class="btn q">Download full archive first</span><span class="btn p dis">Switch pruning on</span></div></div>
</div>
<div>
<div class="panel"><h3>Price archive</h3>
<p class="hint" style="margin:0 0 10px">Every stored price and exchange rate, plus the pinned prices, as compressed files in one zip. Made when you ask and deleted afterwards; it is never kept on the server.</p>
<dl class="kv"><dt>Last made</dt><dd>1 Nov 2026, 2:05 am (emailed, 1 part, 4.7 MB)</dd><dt>Now would be</dt><dd>about 5.2 MB, 1 part · {tag("Full","ink")} {tag("Pruned","")}</dd><dt>Restore</dt><dd>Upload it on the history upload page, with a dry run first</dd></dl>
<div class="acts-row" style="margin-top:8px"><span class="btn p">Make and download now</span></div></div>
<div class="panel"><h3>Email the price archive <span class="tag">Backups &gt; Email backups</span></h3>
<div class="row" style="margin:0 0 12px"><div class="fld"><label>Include the price archive</label>{sw(True)}</div>{fld("How often","Every month","sel2")}{fld("Version","Full","sel2 sm")}</div>
<p class="hint" style="margin:0">Sent as its own email, never combined with the normal backup. Each part stays within the email size limit (15 MB here); a larger archive is split into numbered parts, up to 5. If it still does not fit, nothing is sent and the Backups warning bar tells you. Last sent: 1 Nov 2026, 1 part.</p></div>
<div class="panel"><h3>Pinned prices</h3>{pins}
<p class="hint" style="margin:8px 0">The index value on every transaction date, and the price and indices on every 31 March for each year an investment was held. They are in the normal nightly backup, so a restore reproduces every report even with no daily prices.</p>
<div class="ban wa"><span><b>3 pins are approximate:</b> the exact day was not available from the source, so the nearest month-end was used. Reports that use them show a marker.</span><span class="r"><a href="#">List</a></span></div>
<div class="acts-row" style="margin-top:8px"><span class="btn q">Check pins</span><span class="btn q">Re-pin from stored prices</span></div></div>
</div></div>
<div class="sec"><h2>Recent runs</h2></div>
{table([("When", ""), ("Run", ""), ("Result", "")],
 [["6 Nov, 2:03 am", "Pin prices", "9 new pins (4 transaction dates, 5 index values); 0 missing"], ["1 Nov, 2:05 am", "Price archive emailed", "1 part, 4.7 MB, sent to 2 addresses"], ["1 Apr, 2:04 am", "Year-end pins", "2026 financial year end: 211 pins"]])}"""
    return page("admin-price-history.html", "Price history", "Settings", "Price sources", body, h1="Price history", meta="Admin only · pruning, archive and pins", ctx="none",
                crumb='<a href="admin-prices.html">Price sources</a> / Price history',
                anno=["Pruning is off here, so the live database keeps full daily detail. The archive switch is on, so the archive keeps daily prices for the last 5 years and one figure a month before that.",
                      "The email option lives on the existing Backups > Email backups screen and is shown here for convenience.",
                      "Figures are invented."])


def admin_catalogue():
    X = [
        ("Reliance Industries Ltd", "Share", "RELIANCE.NS", "Yahoo", "Adjusted", "5 Nov 2026", "2,612", "3 profiles", ""),
        ("Tata Consultancy Services Ltd", "Share", "TCS.NS", "Yahoo", "Adjusted", "5 Nov 2026", "2,612", "3 profiles", ""),
        ("Bajaj Finance Ltd", "Share", "BAJFINANCE.NS", "Yahoo", "Adjusted", "5 Nov 2026", "2,612", "2 profiles", tag("Split detected", "amb")),
        ("Larsen & Toubro Ltd", "Share", "LT.NS", "Yahoo", "Adjusted", "5 Nov 2026", "2,611", "2 profiles", tag("Large 1-day fall", "amb")),
        ("Wipro Ltd", "Share", "WIPRO.NS", "Yahoo", "Adjusted", "5 Nov 2026", "2,612", "1 profile", ""),
        ("Parag Parikh Flexi Cap Fund – Direct Growth", "Mutual fund", "AMFI 122639", "AMFI + mfapi.in", "n/a", "5 Nov 2026", "1,903", "2 profiles", ""),
        ("Nippon India Small Cap Fund – Direct Growth", "Mutual fund", "AMFI 118778", "AMFI + mfapi.in", "n/a", "5 Nov 2026", "1,903", "1 profile", tag("Possible duplicate", "amb")),
        ("Nippon India Small Cap Fund (Direct) – Growth", "Mutual fund", "AMFI 118778", "AMFI + mfapi.in", "n/a", "5 Nov 2026", "310", "1 profile", tag("Possible duplicate", "amb")),
        ("Gold – physical (grams)", "Shared note", "no code", "Manual", "n/a", "12 Sep 2026", "14", "1 profile", tag("Stale", "amb")),
        ("Nifty 50", "Index", "^NSEI", "Yahoo", "Price index", "5 Nov 2026", "4,880", "all profiles", ""),
        ("Nifty Bank", "Index", "^NSEBANK", "Yahoo", "Price index", "5 Nov 2026", "4,880", "sectoral", ""),
        ("Apple Inc", "Foreign", "AAPL", "Yahoo", "Adjusted", "5 Nov 2026", "2,598", "1 profile", ""),
    ]
    rr = [[(f'<a href="admin-catalogue-item.html">{n}</a><small>{c}</small>', "nm"), ty, so, ba, (la, "r"), (rows, "r"), (hb, ""), fl] for n, ty, c, so, ba, la, rows, hb, fl in X]
    t = table([("Name", "sorted"), ("Type", ""), ("Price source", ""), ("Basis", ""), ("Last price", "r"), ("Rows stored", "r"), ("Held by", ""), ("Flags", "")], rr)
    body = f"""<div class="sec" style="margin-top:20px"><div style="display:flex;gap:14px;flex-wrap:wrap">{sel("Search","Name, code or ISIN…")}{sel("Type","All")}{sel("Source","All")}{sel("Show","Everything")}</div>
<div class="acts"><span class="btn q">Find duplicates</span><span class="btn q">Export</span><span class="btn p">Add investment</span></div></div>
<div class="ban"><span><b>Every investment in the program</b>, whichever profile holds it. You can manage names, codes, price sources and price histories here. <b>Transactions, units, costs, dividends, folios and alerts are never shown on this page.</b></span></div>
{t}"""
    return page("admin-catalogue.html", "Catalogue", "Settings", "Catalogue", body, h1="Investment catalogue", meta="Admin only · all profiles", ctx="none",
                anno=["“Held by” shows only how many profiles hold the investment (names are on the investment's own page). Private alternative investments (for example a PPF) belong to one profile and are not listed here.",
                      "Two entries with the same AMFI code are flagged as a possible duplicate and can be merged (see the investment page)."])


def admin_catalogue_item():
    prices = table([("Date", ""), ("Close", "r"), ("Source", ""), ("Notes", ""), ("", "")],
                   [["5 Nov 2026", (px(1320), "r"), "Yahoo", "", ("<a>edit</a><a>delete</a>", "act")],
                    ["4 Nov 2026", (px(1313.40), "r"), "Yahoo", "", ("<a>edit</a><a>delete</a>", "act")],
                    ["31 Mar 2026", (px(1402.15), "r"), "Yahoo", tag("Pinned", "ink") + " year end", ("<a>edit</a>", "act")],
                    ["12 Sep 2025", (px(1421.50), "r"), "Manual" + tag("Corrected", "amb"), "was ₹1,412.50 · corrected by Ziyad, 3 Oct 2025", ("<a>edit</a><a>restore original</a>", "act")],
                    ['<tr class="hi"><td>14 Aug 2025</td><td class="r">₹132.00</td><td>Yahoo</td><td><span class="tag ox">Unusual</span> fell 90% in one day, then recovered. Probably a bad tick.</td><td class="act"><a>edit</a><a>delete</a></td></tr>'],
                    ["13 Aug 2025", (px(1311.00), "r"), "Yahoo", "", ("<a>edit</a><a>delete</a>", "act")],
                    ["12 Mar 2021", (px(702.40), "r"), "Upload", tag("Pinned", "ink") + " transaction date", ("<a>edit</a>", "act")]])
    held = table([("Profile", ""), ("Status", "")], [["Madon", "Holds it"], ["Junior", "Holds it"], ["Spouse", "Sold out"]])
    log = table([("When", ""), ("Who", ""), ("Change", "")],
                [["3 Oct 2025, 10:12", "Ziyad", "Price 12 Sep 2025: ₹1,412.50 to ₹1,421.50 (reason: matches the exchange file)"],
                 ["28 Jul 2025, 09:40", "Ziyad", "Fallback price source: none to NSE bhavcopy"],
                 ["6 Jan 2025, 18:05", "System", "Re-fetched full history after the bonus 1 : 1 of 28 Oct 2024; 2,380 rows replaced (basis: adjusted)"]])
    body = f"""<div class="invhead"><div><div class="lab">Share · NSE · Energy · Admin view</div><h1>Reliance Industries Ltd</h1>
<div class="sub">RELIANCE.NS · ISIN INE002A01018 · 2,612 daily prices stored, 2 Jan 2016 to 5 Nov 2026</div></div>
<div class="acts"><span class="btn q">Merge into…</span><span class="btn p">Save details</span></div></div>
<div class="ban wa"><span><b>Changes here affect every profile that holds this investment (3 profiles).</b> They are written to the change log below and cannot be removed from it.</span></div>
<div class="cols eq" style="gap:0 36px"><div>
<div class="sec"><h2>Details</h2></div>
<div class="row">{fld("Name","Reliance Industries Ltd","w2")}{fld("Type","Share","sel2 sm")}</div>
<div class="row">{fld("ISIN","INE002A01018","")}{fld("Exchange","NSE","sel2 sm")}{fld("Currency","INR","sel2 sm")}</div>
<div class="row">{fld("Asset class","Equity","sel2")}{fld("Sector","Energy","sel2")}</div>
<div class="row">{fld("Price source","Yahoo","sel2")}{fld("Fallback source","NSE bhavcopy","sel2")}{fld("Price basis","Split-adjusted","sel2","Changing it needs a re-fetch")}</div>
<div class="row"><div class="fld"><label>Fetch prices every night</label>{sw(True)}</div></div>
<div class="sec"><h2>Symbol at each source</h2></div>
{table([("Source", ""), ("Symbol", ""), ("Checked", "")], [["Yahoo", "RELIANCE.NS", "6 Nov 2026"], ["NSE bhavcopy", "RELIANCE", "28 Jul 2025"], ["Twelve Data", '<span class="na">not set</span>', ""]])}
</div><div>
<div class="sec"><h2>Held by</h2></div>{held}
<p class="hint">Only the profile names and whether it is still held. Units, costs, dates and transactions are not shown to anyone but the profile's own users.</p>
<div class="sec"><h2>Corporate actions</h2></div>
{table([("Ex-date", ""), ("Action", ""), ("Status", "")], [["28 Oct 2024", "Bonus 1 : 1", "Madon: not applicable · Junior: applied · Spouse: applied"]])}
</div></div>
<div class="sec"><h2>Price history</h2><div class="acts"><span class="btn q">Re-fetch a date range</span><span class="btn q">Upload history for this investment</span><span class="btn q">Add a price</span></div></div>
<div style="display:flex;gap:14px;flex-wrap:wrap;margin:0 0 12px">{sel("From","1 Jan 2025")}{sel("To","5 Nov 2026")}{sel("Source","All")}{sel("Show","Everything")}</div>
{prices}
<p class="hint">A price you edit becomes a <b>Manual</b> row. The nightly update never overwrites it, and the original value is kept in the change log. Editing a price on a pinned date updates the pin and lists the reports that will change. A deleted price can be put back from the change log.</p>
<div class="sec"><h2>Change log</h2></div>{log}"""
    return page("admin-catalogue-item.html", "Reliance Industries Ltd (catalogue)", "Settings", "Catalogue", body, titlebar=False, ctx="none",
                crumb='<a href="admin-catalogue.html">Catalogue</a> / Reliance Industries Ltd',
                anno=["Only an Admin sees this page. An Editor sees the shared details as read-only on the investment's own page, and can change only their profile's own details (their sectoral index, links, notes).",
                      "Merging two entries for the same investment points every profile's records at the one you keep, after a forced backup and a preview that shows counts only. It is refused if the type or currency differ."])
