# ruff: noqa
"""Overview and Holdings pages."""
from lib import *


def tags_for(r):
    t = ""
    if r["flag"] == "alert":
        t += tag("Below cost", "ox")
    if r["flag"] == "prov":
        t += tag("Provisional", "amb")
    if r["flag"] == "stale":
        t += tag("Stale", "amb")
    if r["flag"] == "await":
        t += tag("Awaiting ₹50,000", "amb")
    return t


def dash_rows():
    out, last = [], None
    labels = {"Share": "Shares", "Mutual fund": "Mutual funds", "Alternative": "Alternative investments", "Foreign": "Foreign investments"}
    for r in R:
        if r["typ"] != last:
            out.append(f'<tr class="grp"><td colspan="10">{labels[r["typ"]]}</td></tr>')
            last = r["typ"]
        ud = r["ud"]
        pe = f'{r["pe"]:.1f}' if r["pe"] else '<span class="na">–</span>'
        alpha = r["x"] - r["b"]
        out.append([
            (f'<a href="inv-share.html">{r["name"]}</a>{tags_for(r)}<small>{r["code"]}</small>', "nm"),
            (units(r["u"], ud), "r"),
            (px(r["avg"]) if r["typ"] != "Alternative" or r["u"] > 1 else money(r["avg"]), "r"),
            (px(r["price"]) if r["typ"] != "Alternative" or r["u"] > 1 else money(r["price"]), "r"),
            (money(r["val"]), "r"),
            (pct(r["gp"]), "r"),
            (pct(r["x"], signed=False), "r"),
            (pct(r["b"], signed=False), "r"),
            (pct(alpha), "r"),
            (pe, "r"),
        ])
    return out


def growth_chart():
    N = 61
    inv = [4.0 + (INVESTED / 1e5 - 4.0) * (i / (N - 1)) ** 0.85 for i in range(N)]
    rnd = random.Random(7)
    def rel(end, seed):
        rr = random.Random(seed)
        w = [0.0]
        for _ in range(N - 1):
            w.append(w[-1] + rr.gauss(0, 0.012))
        base = [end * (i / (N - 1)) ** 1.15 + (w[i] - w[-1] * i / (N - 1)) for i in range(N)]
        return [1 + max(b, -0.2) for b in base]
    pr, nr = rel(GAIN / INVESTED, 3), rel(0.17, 11)
    p = [a * b for a, b in zip(inv, pr)]
    n = [a * b for a, b in zip(inv, nr)]
    p[-1] = VALUE / 1e5
    labs = [(0, "Nov 2021"), (12, "Nov 2022"), (24, "Nov 2023"), (36, "Nov 2024"), (48, "Nov 2025"), (60, "Nov 2026")]
    svg = line_chart([("Portfolio", p, "solid"), ("In Nifty", n, "dash")], labs, fmt=lambda v: f"₹{v:.1f} lac", yfmt=lambda v: f"{v:.0f}", h=290)
    leg = '<div class="legend"><span><i></i>Portfolio value</span><span><i class="d"></i>The same money invested in Nifty 50 on the same dates</span></div>'
    return svg + leg


def dashboard():
    strip = f"""<div class="strip">
<div class="f"><div class="lab">Invested</div><div class="fig">{money(INVESTED)}</div></div>
<div class="f"><div class="lab">Current value</div><div class="fig">{money(VALUE)}</div></div>
<div class="f"><div class="lab">Gain</div><div class="fig">{money(GAIN, signed=True)}<small>{pct(GAIN/INVESTED*100)} on cost</small></div></div>
<div class="f"><div class="lab">Portfolio XIRR</div><div class="fig">{PORT_XIRR:.1f}%<small>yearly, on money you put in</small></div></div>
<div class="f"><div class="lab">Nifty 50 XIRR</div><div class="fig">{BENCH_XIRR:.1f}%<small>same dates, same amounts</small></div></div>
<div class="f"><div class="lab">Alpha</div><div class="fig g">+{PORT_XIRR-BENCH_XIRR:.1f}%<small>XIRR minus Nifty XIRR</small></div></div>
</div>
<div class="opts"><span class="chk"><i class="on"></i>Include dividends in XIRR</span>
<span>Dividends received: <b style="color:var(--ink)">{money(DIVIDENDS)}</b> <span class="hint">(not part of Current value)</span></span>
<span class="hint">Index shown is the price index (no dividends)</span></div>
<div class="ban al"><span><b>Alert:</b> Asian Paints is 21% below your cost (Rule B, Ziyad) · trading at ₹2,480 against an average cost of ₹3,150.</span><span class="r"><a href="alerts.html">Open</a><a href="#">Snooze</a></span></div>
<div class="ban wa"><span><b>Corporate action pending:</b> Bajaj Finance, split detected. Figures for this holding may be wrong until you confirm.</span><span class="r"><a href="corporate-actions.html">Confirm</a></span></div>
<div class="ban wa"><span><b>2 purchases are awaiting allotment:</b> ₹60,000 paid, counted at cost until you enter the units and NAV.</span><span class="r"><a href="txn-to-confirm.html">Complete</a></span></div>"""
    hold = table(
        [("Name", "sorted"), ("Units", "r"), ("Avg cost", "r"), ("Price", "r"), ("Value", "r"), ("Gain", "r"),
         ("XIRR", "r"), ("Bench", "r"), ("Alpha", "r"), ("PE", "r")], dash_rows(),
        foot=f'<td>Total</td><td></td><td></td><td></td><td class="r">{money(VALUE)}</td><td class="r">{pct(GAIN/INVESTED*100)}</td><td class="r">{PORT_XIRR:.1f}%</td><td class="r">{BENCH_XIRR:.1f}%</td><td class="r">{pct(PORT_XIRR-BENCH_XIRR)}</td><td></td>')
    ins = """<aside class="ins"><h3>Insights</h3><div class="hint" style="font-size:12.5px">Worked out from your data by fixed rules. Not advice.</div>
<ol>
<li>Portfolio XIRR is 14.2%, 2.4 points above Nifty 50. <a class="go" href="performance.html">HDFC Bank led it.</a><span class="x">×</span></li>
<li>Asian Paints is 21% below cost and trails its benchmark by 16.3 points. <a class="go" href="alerts.html">See alert</a><span class="x">×</span></li>
<li>3 purchases turn long-term within 60 days. <a class="go" href="reports.html">View lots</a><span class="x">×</span></li>
<li>Dividends this year are ₹1.12 lac against ₹0.94 lac last year. <a class="go" href="dividends.html">Dividend report</a><span class="x">×</span></li>
<li>2 holdings have stale prices. <a class="go" href="reports.html">Data check</a><span class="x">×</span></li>
</ol><a class="more" href="#">Show all 8</a></aside>"""
    alloc = f"""<div class="sec"><h2>Allocation</h2><div class="acts"><span class="tag ink">Asset class</span><span class="tag">Type</span><span class="tag">Sector</span></div></div>
{stacked([("Equity", A_EQ), ("Debt", A_DEBT), ("Gold", A_GOLD)])}
<div style="height:12px"></div>
{bars_rows([("Shares", T_SHARE), ("Mutual funds", T_FUND), ("Alternative", T_ALT), ("Foreign", T_FOR)], total=50)}"""
    body = f"""{strip}
<div class="cols"><div>
<div class="sec"><h2>Holdings</h2><div class="acts"><span class="btn sm q">Export to Excel</span><span class="btn sm q">Add investment</span></div></div>
{hold}
<div class="sec"><h2>Value against the same money in Nifty</h2><a class="lk" href="charts.html">Charts</a></div>
{growth_chart()}
{alloc}
</div>{ins}</div>"""
    return page("dashboard.html", "Dashboard", "Overview", None, body, h1="Dashboard", meta="All portfolios · 6 November 2026",
                anno=["The figures sit in a ruled strip with no boxed cards. Gain and loss use a sign first, then colour.",
                      "The Auto / Full control at top right changes every rupee amount on this page (try it). Prices per unit, units and percentages never change. Pointing at an amount shows the exact figure.",
                      "Insights are a narrow right-hand column on wide screens and drop below the chart on narrow screens (resize the window to see).",
                      "Pending corporate action: Bajaj Finance is still calculated, carries a Provisional tag, and a banner explains why. A Settings choice can switch this to blocking."])


def start():
    steps = [("Add a portfolio", "For example “Ziyad” and “Spouse”. Every transaction belongs to one portfolio.", True, "Done: 2 added"),
             ("Add your brokers", "Stockbrokers, fund platforms, or “Direct”. Set a default broker for each type of investment.", True, "Done: 5 added"),
             ("Load price history", "Optional, Admin only. Upload years of daily prices once, then only new days are fetched.", False, "Upload"),
             ("Add your investments", "Shares, mutual funds, alternative and foreign investments.", False, "Add investment"),
             ("Enter transactions or opening balances", "Opening balance is the shortcut for things you already owned.", False, "Enter")]
    items = ""
    for i, (t, d, done, b) in enumerate(steps, 1):
        mark = '<span class="sq f"></span>' if done else '<span class="sq"></span>'
        btn = f'<span class="hint">{b}</span>' if done else f'<span class="btn {"p" if i==4 else "q"} sm">{b}</span>'
        items += f'<div class="ch" style="display:flex;justify-content:space-between;gap:20px;padding:18px 0;border-bottom:1px solid var(--hair)"><div><h3 style="font:400 22px var(--font-serif);margin:0">{mark}{i}. {t}</h3><p class="hint" style="margin:4px 0 0 24px">{d}</p></div><div>{btn}</div></div>'
    body = f"""<p class="lead">This is what a new profile sees instead of a dashboard full of zeros. Each step ticks itself off, and the Dashboard fills in as data arrives.</p>
<div style="border-top:1px solid var(--ink);max-width:900px">{items}</div>
<div class="ban" style="max-width:900px;margin-top:22px"><span>No prices yet. <b>Update Prices</b> or ask an Admin to upload history.</span></div>"""
    return page("start.html", "Getting started", "Overview", None, body, h1="Getting started", meta="New profile · Madon",
                anno=["Shown on the Dashboard until the first investments and transactions exist. Real empty states say what to do next."])


def search():
    body = """<p class="lead">The Search icon at the top right opens a search panel under the header (Option-F does the same). Results appear as you type, grouped. Arrow keys move through them and Enter opens one.</p>
<div style="max-width:700px">
<div class="res">
<div style="background:var(--panel);font-size:10.5px;letter-spacing:.15em;text-transform:uppercase;color:var(--muted)"><span>Investments</span></div>
<div class="hl"><span><b>Reli</b>ance Industries <small>RELIANCE.NS · Share</small></span><small>Open page</small></div>
<div><span><b>Reli</b>ance Power <small>RPOWER.NS · sold out</small></span><small>Open page</small></div>
<div style="background:var(--panel);font-size:10.5px;letter-spacing:.15em;text-transform:uppercase;color:var(--muted)"><span>Transactions</span></div>
<div><span>12 Mar 2021 · Buy 100 <b>Reli</b>ance Industries · Zerodha</span><small>Highlight in list</small></div>
<div style="background:var(--panel);font-size:10.5px;letter-spacing:.15em;text-transform:uppercase;color:var(--muted)"><span>Pages</span></div>
<div><span><b>Reli</b>ability data check</span><small>Other reports</small></div>
</div></div>"""
    return page("search.html", "Search", "Overview", None, body, h1="Search", meta="Panel open", search_open=True,
                anno=["Same pattern as the other programs: a magnifier icon in the header, no box around it, opening a panel under the header.",
                      "Searches investments (name, ticker, scheme code, ISIN), folio numbers, brokers, transactions and visible pages. At least two characters. Command + F still finds text on the current page."])


# ------------------------------------------------------------------ holdings list
def holdings():
    body_rows = []
    for r in R:
        status = '<span class="sq f"></span>Held'
        body_rows.append([
            (f'<a href="inv-share.html">{r["name"]}</a>{tags_for(r)}', "nm"),
            (r["typ"], ""), (f'<span class="na">{r["code"]}</span>', ""),
            (units(r["u"], r["ud"]), "r"), (money(r["val"]), "r"), (money(r["gain"], signed=True), "r"),
            ("5 Nov" if r["flag"] != "stale" else "12 Sep", "r"), (status, "")])
    body_rows += [
        ('<tr class="sub"><td class="nm" style="color:var(--muted)">Wipro</td><td>Share</td><td>WIPRO.NS</td><td class="r">0</td><td class="r">–</td><td class="r">–</td><td class="r">5 Nov</td><td><span class="sq"></span>Sold out</td></tr>'),
        ('<tr class="sub"><td class="nm" style="color:var(--muted)">Axis Bluechip Fund – Direct Growth</td><td>Mutual fund</td><td>AMFI 120465</td><td class="r">0.000</td><td class="r">–</td><td class="r">–</td><td class="r">5 Nov</td><td><span class="sq"></span>Sold out</td></tr>')]
    t = table([("Name", "sorted"), ("Type", ""), ("Code", ""), ("Units", "r"), ("Value", "r"), ("Gain", "r"), ("Price date", "r"), ("Status", "")], body_rows)
    body = f"""<div class="sec" style="margin-top:22px"><div class="filters" style="display:flex;gap:16px;flex-wrap:wrap">{sel("Type","All types")}{sel("Status","Held")}{sel("Portfolio","All Portfolios")}</div>
<div class="acts"><span class="btn q">Import statement</span><span class="btn q">Export to Excel</span><span class="btn p">Add investment</span></div></div>
{t}"""
    return page("holdings.html", "Investments", "Holdings", "Investments", body, h1="Investments", meta="16 held · 2 sold out",
                anno=["Every investment this profile has ever held. Sold-out ones can be hidden by an Editor; only an Admin can delete one that has records (see the delete page).",
                      "Tags: Stale (price older than expected), Provisional (a corporate action is waiting for confirmation), Below cost (alert)."], ctx="pb")


# ------------------------------------------------------------------ add investment wizard
def stepper(n):
    names = ["Type", "Find it", "Confirm", "Details"]
    out = ""
    for i, nm in enumerate(names, 1):
        cls = "done" if i < n else ("on" if i == n else "")
        out += f'<div class="{cls}"><b>{i}</b>{nm}</div>'
    return f'<div class="stepper">{out}</div>'


def add1():
    ch = [("Share or ETF", "Exchange-traded. Priced from Yahoo, daily."), ("Mutual fund", "Daily NAV from AMFI. You pick the exact plan."),
          ("Alternative investment", "PPF, deposits, property, unlisted, gold. You enter the values."), ("Foreign investment", "Priced in another currency.")]
    c = "".join(f'<div class="ch"><div><h3>{t}</h3><p>{d}</p></div><span class="btn q sm">Choose</span></div>' for t, d in ch)
    body = f'{stepper(1)}<p class="lead">What kind of investment is it?</p><div class="choices">{c}</div>'
    return page("add-1.html", "Add investment", "Holdings", "Investments", body, h1="Add investment", meta="Step 1 of 4",
                anno=["You never type a source code from memory. The next step searches for it.",
                      "The transaction form also has an “Investment not listed? Add it” link that opens this wizard and returns you to the form."], ctx="none")


def add2():
    body = f"""{stepper(2)}
<div class="form"><div class="row">{fld("Company name or NSE symbol","reliance<span style='border-left:1.5px solid var(--ink);height:20px'></span>","w3")}
{fld("Exchange","NSE (.NS)","sm sel2")}</div>
<div class="res">
<div class="hl"><span>Reliance Industries Ltd <small>RELIANCE.NS · NSE · Equity</small></span><span class="tag ink">Already in the system</span></div>
<div><span>Reliance Industries Ltd <small>RELIANCE.BO · BSE · Equity</small></span><small>Use BSE instead</small></div>
<div><span>Reliance Power Ltd <small>RPOWER.NS · NSE · Equity</small></span><small></small></div>
<div><span>Reliance Infrastructure Ltd <small>RELINFRA.NS · NSE · Equity</small></span><small></small></div></div>
<p class="hint">“Already in the system” means another profile added it. You pick it and no copy is made.</p>
<div class="acts-row"><span class="btn q">Back</span><span class="btn p">Use the highlighted match</span></div></div>"""
    return page("add-2.html", "Add investment", "Holdings", "Investments", body, h1="Add share or ETF", meta="Step 2 of 4",
                anno=["If Yahoo's search is refused, you can type the code and confirm it by the price check on the next step."], ctx="none")


def add2f():
    body = f"""{stepper(2)}
<div class="form"><div class="row">{fld("Fund name","parag parikh flexi<span style='border-left:1.5px solid var(--ink);height:20px'></span>","w3")}</div>
<p class="hint">From AMFI's list of every scheme. Each plan and option has its own scheme code, so pick the exact one.</p>
<div class="res">
<div class="hl"><span>Parag Parikh Flexi Cap Fund – <b>Direct Plan – Growth</b> <small>AMFI 122639 · ISIN INF879O01027</small></span><small>Choose</small></div>
<div><span>Parag Parikh Flexi Cap Fund – Direct Plan – IDCW <small>AMFI 122640</small></span><small>Choose</small></div>
<div><span>Parag Parikh Flexi Cap Fund – Regular Plan – Growth <small>AMFI 120843</small></span><small>Choose</small></div>
<div><span>Parag Parikh Flexi Cap Fund – Regular Plan – IDCW <small>AMFI 120844</small></span><small>Choose</small></div></div>
<div class="acts-row"><span class="btn q">Back</span><span class="btn p">Use the highlighted plan</span></div></div>"""
    return page("add-2-fund.html", "Add investment", "Holdings", "Investments", body, h1="Add mutual fund", meta="Step 2 of 4",
                anno=["Statement imports are later matched to the fund on ISIN or scheme name. Scheme codes and ISINs here are illustrative."], ctx="none")


def add3():
    body = f"""{stepper(3)}
<div class="form"><p class="lead">The latest price was fetched. Is this the right company?</p>
<div class="panel"><dl class="kv">
<dt>Name</dt><dd><b style="font:22px var(--font-serif)">Reliance Industries Ltd</b></dd>
<dt>Code</dt><dd>RELIANCE.NS</dd><dt>Exchange</dt><dd>National Stock Exchange of India (NSE)</dd>
<dt>Currency</dt><dd>INR</dd><dt>Latest price</dt><dd><b>₹1,320.00</b> <span class="hint">closing price of 5 Nov 2026</span></dd>
<dt>Sector</dt><dd>Energy</dd></dl></div>
<div class="ban wa"><span><b>Look-alike check:</b> Reliance Power and Reliance Infrastructure also exist. Confirm this is the one you mean.</span></div>
<div class="acts-row"><span class="btn q">No, search again</span><span class="btn p">Yes, this is it</span></div></div>"""
    return page("add-3.html", "Add investment", "Holdings", "Investments", body, h1="Confirm the investment", meta="Step 3 of 4",
                anno=["If the price fetch fails, this step shows “No price data, check code” and lets the user search again.",
                      "For a mutual fund, saving also starts a one-time history backfill from mfapi.in."], ctx="none")


def add4():
    body = f"""{stepper(4)}
<div class="form"><div class="row">{fld("Main index","Nifty 50","w2 ro","Set once for the whole program in Settings > General")}{fld("Sector","Energy","sel2")}</div>
<div class="row">{fld("Sectoral index","Nifty Energy (suggested for Energy)","w2 sel2","Shown only because the sectoral index is switched on in Settings")}</div>
<div class="row">{fld("Website link","https://www.ril.com/investors","w3","Add as many as you like, each with a label")}{fld("Label","Annual report","")}</div>
<div class="row">{fld("Notes","Optional","w3 ph")}</div>
<div class="panel"><h3>After saving</h3><div class="acts"><span class="btn p">Add the first transaction</span> <span class="btn q">Add another investment</span> <span class="btn q">Back to list</span></div></div>
<div class="acts-row"><span class="btn q">Back</span><span class="btn p">Save investment</span></div></div>"""
    return page("add-4.html", "Add investment", "Holdings", "Investments", body, h1="Details (all optional)", meta="Step 4 of 4",
                anno=["Everything on this page is optional and can be changed later on the investment's own page."], ctx="none")


def addalt():
    body = f"""<div class="form"><p class="lead">For things with no public price: PPF, fixed deposits, property, unlisted shares, gold, private funds. You enter the values yourself.</p>
<div class="row">{fld("Name","HDFC Bank FD (7.1%)","w3")}</div>
<div class="row">{fld("Asset class","Debt","sel2")}{fld("Portfolio","Ziyad","sel2")}{fld("Broker","Direct","sel2","Default for alternative investments: none, so you choose")}</div>
<div class="row">{fld("Starting date","14 Mar 2025","")}{fld("Amount invested","₹5,00,000","")}{fld("Fixed interest rate","7.1% a year","","Optional. Values then grow by this rate between updates.")}</div>
<div class="row">{fld("Maturity or renewal date","14 Mar 2027","","The app alerts you before this date")}</div>
<div class="panel"><h3>Between value updates</h3><p class="hint" style="margin:0">Default (from Settings): <b style="color:var(--ink)">averaged out</b>, so the change between two updates is spread over the days between them. The alternative is “unchanged until the next update”. Charts and the Total Portfolio Value report have a switch.</p></div>
<div class="acts-row"><span class="btn q">Cancel</span><span class="btn p">Save investment</span></div></div>"""
    return page("add-alt.html", "Add alternative investment", "Holdings", "Investments", body, h1="Add alternative investment", meta="Private to this profile", ctx="none",
                anno=["Alternative investments belong to one profile. They are never added to the shared list.",
                      "Broker has no pre-filled value here because the default for this type is set to None in Settings."])
