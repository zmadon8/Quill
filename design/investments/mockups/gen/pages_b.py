# ruff: noqa
"""Investment pages, transactions, dividends, corporate actions, brokers."""
from datetime import date
from lib import *
from pages_a import stepper, tags_for

TODAY = date(2026, 11, 6)


def anchored(points, n, noise=0.018, seed=1):
    """Interpolate between (index, value) anchors and add small noise, so markers sit on believable prices."""
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        for (i0, v0), (i1, v1) in zip(points, points[1:]):
            if i0 <= i <= i1:
                v = v0 + (v1 - v0) * (i - i0) / (i1 - i0)
                break
        out.append(v * (1 + rnd.gauss(0, noise)))
    out[-1] = points[-1][1]
    return out


def price_series(seed, n, end, vol=0.045, drift=0.012):
    s = series(seed, n, 100, drift, vol)
    k = end / s[-1]
    return [v * k for v in s]


def yrs(d):
    return (TODAY - d).days / 365.25


def cagr(cur, cost, d):
    return ((cur / cost) ** (1 / yrs(d)) - 1) * 100


# ------------------------------------------------------------------ one investment: share
def inv_share():
    rel = anchored([(0, 620), (4, 700), (21, 1000), (27, 1150), (40, 1250), (55, 1650), (64, 1570), (72, 1320)], 73, 0.02, 5)
    labs = [(0, "Nov 2020"), (12, "Nov 2021"), (24, "Nov 2022"), (36, "Nov 2023"), (48, "Nov 2024"), (60, "Nov 2025"), (72, "Nov 2026")]
    chart = line_chart([("Price", rel, "solid")], labs, markers=[(4, "b"), (21, "b"), (27, "s"), (64, "b")], fmt=lambda v: f"₹{v:,.0f}", h=280)
    chart += '<div class="legend"><span><i></i>Closing price</span><span><i class="tri up"></i>your purchases</span><span><i class="tri dn"></i>your sale</span></div>'
    lots = [(date(2021, 3, 12), 100, 700.0, "Zerodha", 11.4), (date(2022, 8, 4), 100, 1000.0, "Zerodha", 12.9),
            (date(2026, 3, 18), 100, 1570.0, "Groww", None)]
    lr = []
    for d, u, c, b, idx in lots:
        val, cost = u * 1320, u * c
        held = (TODAY - d).days
        if held >= 365:
            ret = f"{cagr(1320, c, d):.1f}% a yr"
            ic = f"{idx:.1f}% a yr"
            diff = pct(cagr(1320, c, d) - idx)
            lt = '<span class="g">Long-term</span>'
        else:
            r = (1320 / c - 1) * 100
            ret = pct(r) + " <span class='hint'>(under a year)</span>"
            ic = pct(2.1)
            diff = pct(r - 2.1)
            lt = f"{365 - held} days"
        lr.append([(d.strftime("%-d %b %Y") + " " + tag(b, "dash"), ""), (str(u), "r"), (money(cost), "r"), (money(val), "r"),
                   (money(val - cost, signed=True), "r"), (ret, "r"), (ic, "r"), (diff, "r"), (lt, "r")])
    lr.append('<tr class="sub"><td>2 Sep 2019 to sold 10 Feb 2023</td><td class="r">50</td><td class="r">' + money(28000) +
              '</td><td class="r">' + money(57500) + '</td><td class="r">' + money(29500, signed=True) +
              '</td><td class="r" colspan="4">Realised, long-term · Zerodha</td></tr>')
    lt = table([("Purchase", ""), ("Units", "r"), ("Cost", "r"), ("Value now", "r"), ("Gain", "r"), ("Return", "r"), ("Index", "r"), ("Difference", "r"), ("Long-term", "r")], lr)
    tx = table([("Date", ""), ("", ""), ("Units", "r"), ("Price", "r"), ("Broker", ""), ("Portfolio", "")],
               [["18 Mar 2026", "Buy", ("100", "r"), (px(1570), "r"), "Groww", "Ziyad"],
                ["4 Aug 2022", "Buy", ("100", "r"), (px(1000), "r"), "Zerodha", "Ziyad"],
                ["10 Feb 2023", "Sell", ("50", "r"), (px(1150), "r"), "Zerodha", "Ziyad"],
                ["12 Mar 2021", "Buy", ("100", "r"), (px(700), "r"), "Zerodha", "Ziyad"],
                ["2 Sep 2019", "Buy <span class='tag'>Opening</span>", ("50", "r"), (px(560), "r"), "Zerodha", "Ziyad"]])
    body = f"""<div class="invhead"><div><div class="lab">Share · NSE · Energy</div><h1>Reliance Industries</h1>
<div class="sub">RELIANCE.NS · Portfolio: Ziyad · Folios: none · Links: <a style="text-decoration:underline" href="#">Annual report</a> · <a href="#" style="color:var(--muted)">+ add link</a></div></div>
<div class="acts"><span class="btn q">Edit details</span><span class="btn p">Add transaction</span></div></div>
<div class="kvs">
<div><div class="lab">Price, 5 Nov</div><div class="v">{px(1320)}</div></div>
<div><div class="lab">Units</div><div class="v">300 <small>Zerodha 200 · Groww 100</small></div></div>
<div><div class="lab">Value</div><div class="v">{money(300*1320)}</div></div>
<div><div class="lab">Gain</div><div class="v">{money(300*(1320-1090), signed=True)} <small>{pct(21.1)}</small></div></div>
<div><div class="lab">Average cost</div><div class="v">{px(1090)}</div></div>
<div><div class="lab">XIRR</div><div class="v">13.1% <small>Nifty 50 11.0% · Nifty Energy 9.2%</small></div></div>
<div><div class="lab">PE now</div><div class="v">24.1 <small>no history kept</small></div></div>
<div><div class="lab">52-week range</div><div class="v">1,152 – 1,612</div></div>
</div>
<div class="opts"><span>Next results: <b style="color:var(--ink)">14 Nov 2026</b></span><span>Alerts: <b style="color:var(--ink)">none</b></span><span class="chk"><i class="on"></i>Include dividends</span>
<span>Price on any day: <span class="tag ink">12 Mar 2021</span> <b style="color:var(--ink)">₹702.40</b> <span class="hint">value of 100 units ₹70,240</span></span></div>
<div class="cols"><div>
<div class="sec"><h2>Price</h2></div>{chart}
</div><aside class="ins"><h3>Insights</h3><ol>
<li>Trails Nifty 50 on the August 2022 purchase by 6.2 points a year.<span class="x">×</span></li>
<li>The March 2026 purchase turns long-term in 133 days (18 Mar 2027).<span class="x">×</span></li>
<li>Held for 5.7 years: weighted average holding period 3.3 years.<span class="x">×</span></li></ol></aside></div>
<div class="sec"><h2>Purchase by purchase</h2></div>{lt}
<div class="tabs"><a class="on">Transactions</a><a>Dividends</a><a>Corporate actions</a><a>Folios</a><a>Notes</a></div>{tx}"""
    return page("inv-share.html", "Reliance Industries", "Holdings", "Investments", body, titlebar=False, ctx="pb",
                crumb='<a href="holdings.html">Investments</a> / Reliance Industries',
                anno=["Opened by clicking an investment anywhere in the program. The portfolio and broker selectors still apply.",
                      "For purchases under a year the plain percentage return is shown instead of an annualised figure.",
                      "Sold portions show the realised result. A date picker shows the price and value on any earlier day."])


def inv_fund():
    nav = price_series(9, 73, 81.46, vol=0.035, drift=0.012)
    labs = [(0, "Nov 2020"), (12, "Nov 2021"), (24, "Nov 2022"), (36, "Nov 2023"), (48, "Nov 2024"), (60, "Nov 2025"), (72, "Nov 2026")]
    chart = line_chart([("NAV", nav, "solid")], labs, markers=[(i, "b") for i in range(30, 73, 3)], fmt=lambda v: f"₹{v:.2f}", h=260)
    chart += '<div class="legend"><span><i></i>NAV</span><span><i class="tri up"></i>monthly SIP purchases</span></div>'
    fol = table([("Folio", ""), ("Portfolio", ""), ("Note", ""), ("Units", "r"), ("Value", "r")],
                [["12345678/90", "Ziyad", "", ("3,120.412", "r"), (money(3120.412 * 81.46), "r")],
                 ["98765432/10", "Spouse", "joint holding", ("1,700.100", "r"), (money(1700.1 * 81.46), "r")],
                 ["<span class='na'>no folio</span>", "–", "", ("0.000", "r"), ("–", "r")]])
    sip = """<div class="panel"><h3>SIP schedule</h3><dl class="kv"><dt>Amount</dt><dd>₹10,000 on the 5th of each month</dd><dt>Goes to</dt><dd>Ziyad · Direct · folio 12345678/90</dd>
<dt>Next entry</dt><dd>5 Dec 2026 (created by the nightly job once the NAV is stored)</dd>
<dt>Pending</dt><dd><span class="tag amb">Pending</span> 5 Nov 2026: 122.760 units at ₹81.46 · <a href="txn-to-confirm.html" style="text-decoration:underline">Confirm or correct</a></dd></dl></div>"""
    body = f"""<div class="invhead"><div><div class="lab">Mutual fund · Flexi cap</div><h1>Parag Parikh Flexi Cap Fund</h1>
<div class="sub">Direct Plan – Growth · AMFI 122639 · ISIN INF879O01027 · Links: <a style="text-decoration:underline" href="#">Factsheet</a></div></div>
<div class="acts"><span class="btn q">Edit details</span><span class="btn q">Add SIP</span><span class="btn p">Add transaction</span></div></div>
<div class="kvs">
<div><div class="lab">NAV, 5 Nov</div><div class="v">{px(81.46)}</div></div>
<div><div class="lab">Units</div><div class="v">4,820.512 <small>all with Direct</small></div></div>
<div><div class="lab">Value</div><div class="v">{money(4820.512*81.46)}</div></div>
<div><div class="lab">Gain</div><div class="v">{money(4820.512*(81.46-52.30), signed=True)} <small>{pct((81.46/52.30-1)*100)}</small></div></div>
<div><div class="lab">Average cost</div><div class="v">{px(52.30)}</div></div>
<div><div class="lab">XIRR</div><div class="v">18.6% <small>Nifty 50: 12.9%</small></div></div>
<div><div class="lab">Expense ratio</div><div class="v">0.63% <small>entered by hand</small></div></div>
<div><div class="lab">Benchmark</div><div class="v">Nifty 500 TRI</div></div></div>
<div class="ban wa"><span><b>₹50,000 paid on 4 Nov 2026 is awaiting allotment.</b> Counted at cost in the value above (₹50,000), left out of units and average cost. Waiting 2 days.</span><span class="r"><a href="txn-complete.html">Complete</a><a href="#">Edit</a></span></div>
<div class="sec"><h2>NAV</h2></div>{chart}
<div class="cols eq"><div><div class="sec"><h2>Units by folio</h2></div>{fol}
<p class="hint">Units recorded without a folio form a group of their own. A sale of this fund asks which folio to sell from.</p></div><div>{sip}</div></div>"""
    return page("inv-fund.html", "Parag Parikh Flexi Cap Fund", "Holdings", "Investments", body, titlebar=False, ctx="pb",
                crumb='<a href="holdings.html">Investments</a> / Parag Parikh Flexi Cap Fund',
                anno=["Funds show NAV instead of price, no PE, and the folios section is prominent. The same fund can have different folios in different portfolios.",
                      "SIP entries are created as pending and count only after you confirm them (the default; a Settings choice can create final entries instead)."])


def inv_alt():
    pts = [500000 + (546000 - 500000) * (i / 40) ** 0.9 for i in range(41)]
    labs = [(0, "Mar 2025"), (13, "Sep 2025"), (27, "Mar 2026"), (40, "Nov 2026")]
    chart = line_chart([("Value", pts, "solid")], labs, fmt=lambda v: f"₹{v/1e5:.2f} lac", yfmt=lambda v: f"{v/1e5:.1f}", h=240)
    chart += '<div class="legend"><span><i></i>Value, averaged out between your updates</span><span>Switch: <span class="tag ink">Averaged out</span> <span class="tag">Unchanged</span></span></div>'
    vals = table([("Date", ""), ("Total value", "r"), ("Unit price", "r"), ("Entered by", ""), ("", "")],
                 [["5 Nov 2026", (money(546000), "r"), ("–", "r"), "Ziyad", ("<a>edit</a>", "act")],
                  ["31 Mar 2026", (money(536300), "r"), ("–", "r"), "Ziyad", ("<a>edit</a>", "act")],
                  ["30 Sep 2025", (money(518200), "r"), ("–", "r"), "Ziyad", ("<a>edit</a>", "act")],
                  ["14 Mar 2025 <span class='tag'>Purchase</span>", (money(500000), "r"), ("–", "r"), "Ziyad", ""]])
    body = f"""<div class="invhead"><div><div class="lab">Alternative investment · Debt</div><h1>HDFC Bank FD (7.1%)</h1>
<div class="sub">No price feed · Portfolio: Ziyad · Broker: Direct · Interest 7.1% a year</div></div>
<div class="acts"><span class="btn q">Edit details</span><span class="btn p">Add value update</span></div></div>
<div class="ban wa"><span><b>Matures on 14 Mar 2027</b> · 128 days from today. You will be reminded before it arrives.</span></div>
<div class="kvs">
<div><div class="lab">Latest value, 5 Nov</div><div class="v">{money(546000)}</div></div>
<div><div class="lab">Invested</div><div class="v">{money(500000)}</div></div>
<div><div class="lab">Gain</div><div class="v">{money(46000, signed=True)} <small>{pct(9.2)}</small></div></div>
<div><div class="lab">XIRR</div><div class="v">7.1% <small>FD benchmark 7.0%</small></div></div></div>
<div class="cols eq"><div><div class="sec"><h2>Value over time</h2></div>{chart}</div>
<div><div class="sec"><h2>Dated values</h2></div>{vals}
<div class="panel"><h3>Add a value</h3><div class="row" style="margin:0">{fld("Date","6 Nov 2026","sm")}{fld("Total value","₹","sm ph")}{fld("Unit price (optional)","","sm ph")}</div><div class="acts"><span class="btn p sm">Save value</span></div></div></div></div>"""
    return page("inv-alt.html", "HDFC Bank FD", "Holdings", "Investments", body, titlebar=False, ctx="pb",
                crumb='<a href="holdings.html">Investments</a> / HDFC Bank FD (7.1%)',
                anno=["Alternative investments replace the price chart and PE with dated values, interest rate and maturity date.",
                      "They count in Total Portfolio Value and portfolio XIRR but are left out of the CAGR view, which needs price history."])


def inv_foreign():
    body = f"""<div class="invhead"><div><div class="lab">Foreign investment · NASDAQ · USD</div><h1>Apple Inc</h1>
<div class="sub">AAPL · Portfolio: Ziyad · Broker: Interactive Brokers · rate today ₹88.00 to the dollar</div></div>
<div class="acts"><span class="btn q">Edit details</span><span class="btn p">Add transaction</span></div></div>
<p class="lead" style="max-width:none">Every value is shown twice: in dollars (the investment's own performance) and in rupees (what you actually gained, including exchange-rate movement).</p>
{table([("", ""), ("In dollars", "r"), ("In rupees", "r")],
 [["Units", ("40", "r"), ("40", "r")], ["Average cost", ("$168.00", "r"), (px(168*83.5), "r")], ["Price, 5 Nov", ("$228.00", "r"), (px(228*88), "r")],
  ["Cost", ("$6,720", "r"), (money(40*168*83.5), "r")], ["Value", ("$9,120", "r"), (money(40*228*88), "r")],
  ["Gain", ("+$2,400 " + pct(35.7), "r"), (money(40*228*88 - 40*168*83.5, signed=True) + " " + pct((40*228*88/(40*168*83.5)-1)*100), "r")],
  ["XIRR", ("12.9%", "r"), ("15.7%", "r")], ["S&P 500 over the same cash flows", ("12.5%", "r"), ("15.1%", "r")],
  ["<b>Currency effect</b>", ("", "r"), ("<b>+7.3 points of gain, +2.8 points of XIRR</b>", "r")]])}
<div class="panel" style="max-width:820px"><h3>Rate used on each purchase</h3><p class="hint" style="margin:0">Each purchase uses that day's stored rate, which you can override with the actual rate or the rupee amount actually paid. Capital gains are worked out in rupees. Tax treatment of foreign investments: to be checked with your CA.</p></div>"""
    return page("inv-foreign.html", "Apple Inc", "Holdings", "Investments", body, titlebar=False, ctx="pb",
                crumb='<a href="holdings.html">Investments</a> / Apple Inc', anno=["Charts for foreign investments can be drawn in dollars or rupees with a switch. In Auto, dollar amounts use k and m; the cr and lac units apply to rupees only."])


def inv_delete():
    body = f"""<div class="form"><div class="ban al"><span><b>Admin only.</b> This removes the investment's records from this profile. It cannot be undone from the History screen.</span></div>
<h2 style="font:400 28px var(--font-serif);margin:20px 0 6px">Delete Wipro?</h2>
<div class="panel"><h3>What will be removed from profile Madon</h3>
<dl class="kv"><dt>Transactions</dt><dd>2</dd><dt>Dividends</dt><dd>3</dd><dt>Folios</dt><dd>0</dd><dt>SIP schedules</dt><dd>0</dd><dt>Corporate action confirmations</dt><dd>1</dd><dt>Alert rules</dt><dd>1</dd></dl></div>
<div class="ban wa"><span><b>Shared investment.</b> Another profile still holds Wipro, so the shared instrument and its prices stay. Only this profile's records go.</span></div>
<div class="panel"><h3>Before it is deleted</h3><p class="hint" style="margin:0">A backup called “Before deleting investment” is taken first and kept until an Admin removes it. If it cannot be made, nothing is deleted. The deletion is written to the permanent removal log. To bring the records back, restore from that backup.</p></div>
<div class="row">{fld("Type the investment's name to confirm","Wipro","w2")}</div>
<div class="acts-row"><span class="btn q">Cancel</span><span class="btn dng">Delete Wipro</span></div></div>"""
    return page("inv-delete.html", "Delete investment", "Holdings", "Investments", body, h1="Delete investment", meta="Admin", ctx="none",
                anno=["An Editor can delete an investment only when it has no records, or hide it once sold out. Only an Admin sees this screen for one with records."])


# ------------------------------------------------------------------ transactions
def txn_list():
    T = [
        ("6 Nov 2026", "Buy", "Reliance Industries", "Ziyad", "Zerodha", "", "20", px(1320), 42, "", ""),
        ("5 Nov 2026", "Buy", "Parag Parikh Flexi Cap – Direct Growth", "Ziyad", "Direct", "12345678/90", "122.760", px(81.46), 0, "pending", ""),
        ("30 Oct 2026", "Sell", "ITC", "Spouse", "Groww", "", "100", px(428), 25, "", ""),
        ("12 Oct 2026", "Buy", "SBI Small Cap Fund – Direct Growth", "Ziyad", "Direct", "55001122/3", "59.210", px(168.90), 0, "", ""),
        ("18 Mar 2026", "Buy", "Reliance Industries", "Ziyad", "Groww", "", "100", px(1570), 118, "", ""),
        ("2 Feb 2026", "Transfer in", "HDFC Bank", "Ziyad", "Zerodha", "", "150", "–", 0, "transfer", "from Groww, original dates kept"),
        ("9 Aug 2023", "Sell", "Wipro", "Ziyad", "Zerodha", "", "100", px(402), 31, "", ""),
        ("10 Feb 2023", "Sell", "Reliance Industries", "Ziyad", "Zerodha", "", "50", px(1150), 29, "", ""),
        ("4 Aug 2022", "Buy", "Reliance Industries", "Ziyad", "Zerodha", "", "100", px(1000), 52, "", ""),
        ("5 Jan 2022", "Buy", "Wipro", "Ziyad", "Zerodha", "", "100", px(610), 30, "", ""),
        ("12 Mar 2021", "Buy", "Reliance Industries", "Ziyad", "Zerodha", "", "100", px(700), 41, "", ""),
        ("2 Sep 2019", "Buy", "Reliance Industries", "Ziyad", "Zerodha", "", "50", px(560), 0, "opening", ""),
        ("1 Apr 2018", "Buy", "ITC", "Spouse", "Groww", "", "900", px(262), 0, "opening", "estimated date"),
    ]
    rows_ = []
    for d, t, inv, pf, br, fo, u, p, ch, fl, n in T:
        tg = {"pending": tag("Pending", "amb"), "opening": tag("Opening", ""), "transfer": tag("Transfer", "ink")}.get(fl, "")
        if "estimated" in n:
            tg += tag("Estimated date", "dash")
        amt = float(u.replace(",", "")) * float(p.replace("₹", "").replace(",", "")) if p != "–" else 0
        sg = -1 if t == "Sell" else 1
        cell = money(amt + ch * sg) if amt else "–"
        rows_.append([(d, "nw"), (f'<b style="font-weight:500">{t}</b>' + tg, "nw"), (f'<span style="font-family:var(--font-serif);font-size:16px">{inv}</span>', ""), pf, br,
                      (fo or '<span class="na">–</span>', ""), (u, "r"), (p, "r"), (money(ch) if ch else "–", "r"), (cell, "r"),
                      ("<a>edit</a><a>delete</a>", "act")])
    aw = lambda d, inv, fo, amt: [(d, "nw"), ('<b style="font-weight:500">Buy</b>' + tag("Awaiting allotment", "amb"), "nw"), (f'<span style="font-family:var(--font-serif);font-size:16px">{inv}</span>', ""),
                                  "Ziyad", "Direct", (fo, ""), ("–", "r"), ("–", "r"), ("–", "r"), (money(amt) + ' <span class="hint">paid</span>', "r"), ("<a>complete</a><a>edit</a><a>cancel</a>", "act")]
    rows_.insert(2, aw("4 Nov 2026", "Parag Parikh Flexi Cap – Direct Growth", "12345678/90", 50000))
    rows_.insert(3, aw("3 Nov 2026", "HDFC Index Fund – Nifty 50 – Direct Growth", "98765432/10", 10000))
    t = table([("Date", "sorted d"), ("Type", ""), ("Investment", ""), ("Portfolio", ""), ("Broker", ""), ("Folio", ""), ("Units", "r"), ("Price", "r"), ("Charges", "r"), ("Amount", "r"), ("", "")], rows_)
    body = f"""<div class="ban"><span><b>4 entries need completing:</b> 2 SIP entries to confirm and 2 purchases awaiting allotment (₹60,000, counted at cost).</span><span class="r"><a href="txn-to-confirm.html">Review</a></span></div>
<div class="acts" style="justify-content:flex-end;margin:16px 0 6px"><span class="btn q"><a href="txn-opening.html">Opening balance</a></span><span class="btn q"><a href="txn-transfer.html">Transfer</a></span><span class="btn q"><a href="txn-switch.html">Switch</a></span><span class="btn q"><a href="import-statement.html">Import statement</a></span><span class="btn q">Export</span><span class="btn p"><a href="txn-new-buy.html">Add transaction</a></span></div>
<div style="display:flex;gap:14px;flex-wrap:wrap;margin:0 0 14px">{sel("Search","Find in transactions…")}{sel("Investment","All")}{sel("Type","Buy and sell")}{sel("Dates","All dates")}</div>
{t}"""
    return page("transactions.html", "Transactions", "Holdings", "Transactions", body, h1="Transactions", meta="15 shown · sorted newest first",
                anno=["Tags: Opening (an opening balance), Estimated date, Transfer, Pending (a SIP entry not yet confirmed).",
                      "Opening a search result from the header lands here with that row highlighted.",
                      "Amount for a sale is proceeds after charges; for a purchase it is cost including charges.", "Awaiting allotment: money has left, but the units and NAV are not known yet (section 6, Awaiting allotment). Counted at cost; cannot be sold; completed from the To complete page."])


def txn_buy():
    body = f"""<div class="form"><div class="row">{fld("Date","6 Nov 2026","")}<div class="fld"><label>Type</label><div class="radio"><span class="on">Buy</span><span>Sell</span></div></div></div>
<div class="row">{fld("Investment","Reliance Industries · RELIANCE.NS","w3 sel2","Investment not listed? <u>Add it</u>")}</div>
<div class="row">{fld("Portfolio","Ziyad","sel2")}{fld("Broker","Zerodha","sel2","Default for shares")}{fld("Folio","Not used for shares","ro")}</div>
<div class="row">{fld("Units","20","sm")}{fld("Price per unit","1,320.00","sm","<u>Use the latest price</u> (5 Nov)")}{fld("Charges","42","sm","Brokerage and other charges")}
<div class="fld"><label>Amount</label><div class="calc">{money(20*1320+42)}</div><span class="note">units × price + charges</span></div></div>
<div class="ban wa" style="display:none"></div>
<div class="acts-row"><span class="btn q">Cancel</span><span class="btn q">Save and add another</span><span class="btn p">Save</span></div></div>"""
    return page("txn-new-buy.html", "Add transaction", "Holdings", "Transactions", body, h1="Add transaction", meta="Purchase", ctx="none",
                anno=["The broker is pre-filled from the default for this type of investment (Settings > Brokers). If the default for a type is None, the field starts empty and you must choose.",
                      "Warnings appear for a missing price or a date before the first purchase."])


def txn_sell():
    body = f"""<div class="form"><div class="row">{fld("Date","6 Nov 2026","")}<div class="fld"><label>Type</label><div class="radio"><span>Buy</span><span class="on">Sell</span></div></div></div>
<div class="row">{fld("Investment","Reliance Industries · RELIANCE.NS","w3 sel2")}</div>
<div class="panel"><h3>Available to sell on 6 Nov 2026</h3>
{table([("Total", "r"), ("Zerodha", "r"), ("Groww", "r")], [[("300", "r"), ("200", "r"), ("100", "r")]])}
<p class="hint" style="margin:8px 0 0">With units at more than one broker you must choose which broker's holding to sell. A sale cannot exceed the total or the chosen broker's units. On the same date, purchases count before sales.</p></div>
<div class="row">{fld("Portfolio","Ziyad","sel2")}{fld("Broker to sell from","Zerodha (200 available)","w2 sel2")}</div>
<div class="row">{fld("Units","150","sm")}{fld("Price per unit","1,320.00","sm")}{fld("Charges","58","sm")}
<div class="fld"><label>Proceeds</label><div class="calc">{money(150*1320-58)}</div><span class="note">units × price − charges</span></div></div>
<div class="panel"><h3>First in, first out will use</h3>
{table([("Lot bought", ""), ("Units used", "r"), ("Cost per unit", "r"), ("Gain on these", "r"), ("Term", "")],
 [["12 Mar 2021", ("100", "r"), (px(700), "r"), (money(62000, signed=True), "r"), "Long-term"], ["4 Aug 2022", ("50", "r"), (px(1000), "r"), (money(16000, signed=True), "r"), "Long-term"]],
 foot=f'<td>Estimated gain before tax</td><td></td><td></td><td class="r">{money(78000, signed=True)}</td><td></td>')}</div>
<div class="acts-row"><span class="btn q">Cancel</span><span class="btn p">Save sale</span></div></div>"""
    return page("txn-new-sell.html", "Add transaction", "Holdings", "Transactions", body, h1="Add transaction", meta="Sale", ctx="none",
                anno=["If folios exist too, the sale must also pick a folio, and cannot exceed the units matching both the broker and the folio.",
                      "The tax result is a record-keeping aid. Confirm treatment with your CA."])


def txn_refused():
    body = f"""<div class="form"><div class="form-errors ban al"><span><b>This change was not saved.</b></span></div>
<div class="ban al" style="display:block"><b>It would leave Zerodha with −40 units of Wipro on 9 Aug 2023.</b>
<ul><li>You changed the purchase of 5 Jan 2022 from 100 units to 60.</li><li>The later sale on <a href="#" style="text-decoration:underline">9 Aug 2023 (100 units, Zerodha)</a> relies on those units.</li></ul>
<p style="margin:8px 0 0">Fix the sale first, or choose different units, then try again.</p></div>
<div class="row">{fld("Date","5 Jan 2022","")}<div class="fld"><label>Type</label><div class="radio"><span class="on">Buy</span><span>Sell</span></div></div></div>
<div class="row">{fld("Investment","Wipro","w2 sel2")}{fld("Broker","Zerodha","sel2")}</div>
<div class="row">{fld("Units","60","sm err","Cannot be below 100 while the sale of 9 Aug 2023 stands")}{fld("Price per unit","610.00","sm")}{fld("Charges","30","sm")}</div>
<div class="acts-row"><span class="btn q">Cancel</span><span class="btn p">Save</span></div></div>"""
    return page("txn-edit-refused.html", "Edit transaction", "Holdings", "Transactions", body, h1="Edit transaction", meta="Refused", ctx="none",
                anno=["After every edit the program re-checks the whole history. If any broker or folio would go negative on any date, the edit is refused and the conflicting entry is shown."])


def txn_opening():
    lots = table([("Original purchase date", ""), ("Units", "r"), ("Cost per unit", "r"), ("Date known?", "")],
                 [[("5 Jun 2018", ""), ("400", "r"), ("385.00", "r"), "Exact"], [("Mar 2019 (approx.)", ""), ("500", "r"), ("372.00", "r"), tag("Estimated", "dash") + " note: after Q4 results"],
                  [("<span class='na'>add another lot…</span>", ""), "", "", ""]])
    body = f"""<div class="form"><p class="lead">For things you already owned before using the program. Enter the original purchase dates, since they decide short or long term and feed XIRR.</p>
<div class="row">{fld("Investment","ITC · ITC.NS","w3 sel2")}</div>
<div class="row">{fld("Portfolio","Spouse","sel2")}{fld("Broker","Groww","sel2")}{fld("Folio","Not used for shares","ro")}</div>
<div class="panel"><h3>Lots</h3>{lots}<p class="hint" style="margin:8px 0 0">No charges on this form. Each lot is saved as an ordinary purchase labelled “Opening” and follows every normal rule.</p></div>
<div class="acts-row"><span class="btn q">Cancel</span><span class="btn p">Save 2 lots</span></div></div>"""
    return page("txn-opening.html", "Opening balance", "Holdings", "Transactions", body, h1="Opening balance", meta="Several lots in one go", ctx="none",
                anno=["If the exact date is unknown, an approximate one is allowed, marked “estimated”, and reports that depend on it show the marker."])


def txn_transfer():
    body = f"""<div class="form"><p class="lead">Move units between brokers, folios or portfolios. Original purchase dates and cost move with the units.</p>
<div class="row">{fld("Investment","HDFC Bank · HDFCBANK.NS","w3 sel2")}{fld("Date","2 Feb 2026","")}</div>
<div class="row">{fld("From","Groww · Ziyad","w2 sel2","150 units available")}{fld("To","Zerodha · Ziyad","w2 sel2")}{fld("Units","150","sm")}</div>
<div class="panel"><h3>Lots that will move (oldest first)</h3>
{table([("Bought", ""), ("Units", "r"), ("Cost per unit", "r")], [["8 Jul 2022", ("100", "r"), (px(1380), "r")], ["15 Mar 2023", ("50", "r"), (px(1540), "r")]])}
<p class="hint" style="margin:8px 0 0">In the broker comparison, a transfer counts as money leaving Groww and arriving at Zerodha at the market value on 2 Feb 2026, so neither result is distorted.</p></div>
<div class="acts-row"><span class="btn q">Cancel</span><span class="btn p">Save transfer</span></div></div>"""
    return page("txn-transfer.html", "Transfer", "Holdings", "Transactions", body, h1="Transfer", meta="Between brokers", ctx="none")


def txn_switch():
    body = f"""<div class="form"><p class="lead">A switch is a sale of one fund and a purchase of another, saved together as one linked entry.</p>
<div class="row">{fld("Date","6 Nov 2026","")}{fld("Portfolio","Ziyad","sel2")}{fld("Broker","Direct","sel2")}</div>
<div class="cols eq" style="gap:30px"><div class="panel"><h3>Sell</h3><div class="row">{fld("Fund","SBI Small Cap Fund – Direct Growth","w2 sel2")}</div><div class="row">{fld("Units","500.000","sm")}{fld("NAV","168.90","sm")}{fld("Folio","55001122/3","sel2")}</div></div>
<div class="panel"><h3>Buy</h3><div class="row">{fld("Fund","HDFC Index Fund – Nifty 50 – Direct Growth","w2 sel2")}</div><div class="row">{fld("Amount","₹"+group_indian(500*168.9),"sm")}{fld("NAV","214.35","sm")}{fld("Units","393.969","sm ro")}</div></div></div>
<div class="acts-row"><span class="btn q">Cancel</span><span class="btn p">Save switch</span></div></div>"""
    return page("txn-switch.html", "Switch", "Holdings", "Transactions", body, h1="Switch between funds", meta="Linked sale and purchase", ctx="none")


def txn_confirm():
    sip = table([("Date", ""), ("Fund", ""), ("Schedule", ""), ("NAV", "r"), ("Units", "r"), ("Amount", "r"), ("", "")],
                [[("5 Nov 2026", ""), ("Parag Parikh Flexi Cap – Direct Growth", "nm"), "₹10,000 on the 5th", ("81.46", "r"), ("122.760", "r"), (money(10000), "r"), ("<a>confirm</a><a>correct</a>", "act")],
                 [("5 Nov 2026", ""), ("HDFC Index Fund – Nifty 50 – Direct", "nm"), "₹5,000 on the 5th", ("214.35", "r"), ("23.327", "r"), (money(5000), "r"), ("<a>confirm</a><a>correct</a>", "act")]])
    aw = table([("Paid on", ""), ("Investment", ""), ("Broker · folio", ""), ("Amount paid", "r"), ("Waiting", "r"), ("Suggestion from stored NAV", ""), ("", "")],
               [[("4 Nov 2026", ""), ("Parag Parikh Flexi Cap – Direct Growth", "nm"), "Direct · 12345678/90", (money(50000), "r"), ("2 days", "r"), "NAV of 5 Nov ₹81.90 gives about 610.470 units", ("<a href='txn-complete.html'>complete</a><a>edit</a><a>cancel</a>", "act")],
                [("3 Nov 2026", ""), ("HDFC Index Fund – Nifty 50 – Direct Growth", "nm"), "Direct · 98765432/10", (money(10000), "r"), ("3 days", "r"), "NAV of 4 Nov ₹213.80 gives about 46.770 units", ("<a>complete</a><a>edit</a><a>cancel</a>", "act")]])
    body = f"""<div class="sec" style="margin-top:20px"><h2>Awaiting allotment (2)</h2><div class="acts"><span class="btn q">Add a purchase awaiting allotment</span></div></div>
<p class="hint" style="margin:0 0 8px">Money has left your account but the units and NAV are not known yet. These count at cost, cannot be sold, and stay out of average cost and alerts until you complete them. A reminder appears after 7 days (a Settings choice).</p>{aw}
<div class="sec"><h2>SIP entries to confirm (2)</h2><div class="acts"><span class="btn p">Confirm all</span></div></div>
<p class="hint" style="margin:0 0 8px">Created by the nightly job from your SIP schedules, using each day's NAV. They do not count until you confirm them.</p>{sip}"""
    return page("txn-to-confirm.html", "To complete", "Holdings", "Transactions", body, h1="To complete", meta="4 entries", ctx="none",
                anno=["One page for everything that is not final yet: purchases awaiting allotment, and SIP entries waiting for your confirmation.",
                      "The suggestion appears only when a stored NAV exists on or after the payment date. It is a suggestion; nothing is completed for you."])


def txn_awaiting():
    body = f"""<div class="form"><div class="row">{fld("Date paid","4 Nov 2026","","The day the money left your account")}<div class="fld"><label>Type</label><div class="radio"><span class="on">Buy</span><span>Sell</span></div></div></div>
<div class="row">{fld("Investment","Parag Parikh Flexi Cap Fund – Direct Growth","w3 sel2")}</div>
<div class="row">{fld("Portfolio","Ziyad","sel2")}{fld("Broker","Direct","sel2","Default for mutual funds")}{fld("Folio","12345678/90","sel2")}</div>
<div class="panel"><h3>Do you know the units and price yet?</h3>
<div class="radio" style="margin-bottom:14px"><span>Yes, enter units and price</span><span class="on">Not yet: awaiting allotment</span></div>
<div class="row" style="margin:0">{fld("Amount paid","₹50,000","sm","The full amount debited")}{fld("Expected allotment date (optional)","5 Nov 2026","","Used to suggest units from the NAV")}{fld("Reference (optional)","Order 20261104-77213","w2")}</div></div>
<div class="panel"><h3>Until you complete it</h3><ul class="hint" style="margin:0;padding-left:18px"><li>The ₹50,000 counts as <b style="color:var(--ink)">invested</b> from 4 Nov 2026, and in XIRR as money paid on that day.</li><li>It is valued <b style="color:var(--ink)">at cost</b> (₹50,000), so it adds nothing to gain.</li><li>It has no units, so it cannot be sold and is left out of average cost and alerts.</li><li>It appears on the Dashboard and in <b style="color:var(--ink)">To complete</b>, with a reminder after 7 days.</li></ul></div>
<div class="acts-row"><span class="btn q">Cancel</span><span class="btn q">Save and add another</span><span class="btn p">Save as awaiting</span></div></div>"""
    return page("txn-new-awaiting.html", "Add transaction", "Holdings", "Transactions", body, h1="Add transaction", meta="Awaiting allotment", ctx="none",
                anno=["Units, price and the allotment date are left out. Everything else is as for an ordinary purchase.",
                      "Works for mutual funds, alternative investments with units, and foreign purchases (rupees paid known, dollars received later)."])


def txn_complete():
    amt, stamp, nav = 50000.0, 2.50, 81.90
    units = round((amt - stamp) / nav, 3)
    diff = amt - (units * nav + stamp)
    navs = [("4 Nov 2026", 81.46), ("5 Nov 2026", 81.90), ("6 Nov 2026", 82.15)]
    rows_ = []
    for i, (d, n) in enumerate(navs):
        u = (amt - stamp) / n
        cls = "hi" if d.startswith("5") else ""
        mark = '<span class="sq f"></span>' if cls else '<span class="sq"></span>'
        rows_.append(f'<tr class="{cls}"><td>{mark}{d}</td><td class="r">{px(n)}</td><td class="r">{units_fmt(u)}</td></tr>')
    ntab = table([("NAV date", ""), ("NAV", "r"), ("Units, after ₹2.50 stamp duty", "r")], rows_)
    body = f"""<div class="form"><div class="panel"><dl class="kv"><dt>Investment</dt><dd><b style="font:20px var(--font-serif)">Parag Parikh Flexi Cap Fund – Direct Growth</b></dd><dt>Paid on</dt><dd>4 Nov 2026 · {money(50000)} · Direct · folio 12345678/90</dd><dt>Reference</dt><dd>Order 20261104-77213</dd></dl></div>
<div class="sec" style="margin-top:6px"><h2>Pick the NAV the units were allotted at</h2></div>
<p class="hint" style="margin:0 0 6px">Stored NAVs on and after the payment date, with the units each would give. The right day depends on the fund and the cut-off time, so check your statement or confirmation.</p>{ntab}
<div class="sec"><h2>Confirm</h2></div>
<div class="row">{fld("Allotment date","5 Nov 2026","")}{fld("NAV","81.90","sm")}{fld("Units",f"{units:.3f}","sm","Worked out from the amount and NAV; type over it if your statement differs")}{fld("Charges (stamp duty)","2.50","sm")}</div>
<div class="ban"><span><b>Check:</b> units × NAV + charges = ₹{group_indian(int(units*nav+stamp))}.{int(round(((units*nav+stamp)%1)*100)):02d}, against ₹50,000.00 paid. Difference ₹{abs(diff):.2f} (rounding of units to three places).</span></div>
<p class="hint">After saving it becomes an ordinary purchase. The transaction date stays 4 Nov 2026 (when the money left), and the allotment date of 5 Nov 2026 is recorded for the holding period and first-in-first-out order.</p>
<div class="acts-row"><span class="btn q">Cancel</span><span class="btn p">Complete purchase</span></div></div>"""
    return page("txn-complete.html", "Complete purchase", "Holdings", "Transactions", body, h1="Complete purchase", meta="Awaiting allotment", ctx="none",
                crumb='<a href="txn-to-confirm.html">To complete</a> / Parag Parikh Flexi Cap',
                anno=["If units and NAV differ from the amount paid by more than a small tolerance, the check turns amber and you must tick that the difference is right (for example a partial allotment).",
                      "Stamp duty and the exact NAV day are illustrative. You can also enter only the units, and the NAV is then worked out."])


def units_fmt(x):
    return f"{x:,.3f}"


def import_statement():
    rows_ = [[("12 Oct 2026", ""), ("Buy", ""), ("SBI Small Cap Fund – Direct Growth", "nm"), ("59.210", "r"), ("168.90", "r"), tag("Ready", "ink"), ("", "")],
             [("14 Oct 2026", ""), ("Buy", ""), ("Nippon India Small Cap", "nm"), ("40.100", "r"), ("182.40", "r"), tag("Unknown investment", "amb"), ("<a>match or add</a>", "act")],
             [("5 Nov 2026", ""), ("Buy", ""), ("Parag Parikh Flexi Cap – Direct Growth", "nm"), ("122.760", "r"), ("81.46", "r"), tag("Duplicate of a pending SIP", "amb"), ("<a>skip</a>", "act")],
             [("4 Nov 2026", ""), ("Buy", ""), ("Parag Parikh Flexi Cap – Direct Growth", "nm"), ("610.470", "r"), ("81.90", "r"), tag("Completes the awaiting entry of 4 Nov (₹50,000)", "ink"), ("<a>complete it</a>", "act")],
             [("6 Nov 2026", ""), ("Sell", ""), ("ITC", "nm"), ("5,000", "r"), ("428.00", "r"), tag("More than held", "ox"), ("<a>fix</a>", "act")]]
    body = f"""<div class="stepper"><div class="done"><b>1</b>Upload</div><div class="done"><b>2</b>Map columns</div><div class="on"><b>3</b>Review</div><div><b>4</b>Save</div></div>
<p class="lead">File: <b>groww-statement-oct-nov-2026.xlsx</b> · 5 entries read · columns were guessed and you confirmed them. Nothing is saved until you approve.</p>
{table([("Date", ""), ("Type", ""), ("Investment", ""), ("Units", "r"), ("Price", "r"), ("Check", ""), ("", "")], rows_)}
<div class="acts-row"><span class="btn q">Back</span><span class="btn p">Save 1 ready entry and complete 1 awaiting entry</span></div>"""
    return page("import-statement.html", "Import statement", "Holdings", "Transactions", body, h1="Import statement", meta="Review step", ctx="none",
                anno=["Each broker or fund-house format needs its own small adapter. Folio numbers are picked up where the file has them.",
                      "Over-sales, duplicates and unknown investments are flagged here, never saved silently."])


# ------------------------------------------------------------------ dividends
def dividends():
    d = table([("Date received", "sorted d"), ("Investment", ""), ("Portfolio", ""), ("Broker", ""), ("Amount", "r"), ("Tax deducted", "r"), ("Net", "r"), ("", "")],
              [["28 Oct 2026", ("ITC", "nm"), "Spouse", "Groww", (money(7500), "r"), (money(0), "r"), (money(7500), "r"), ("<a>edit</a><a>delete</a>", "act")],
               ["14 Sep 2026", ("Infosys", "nm"), "Ziyad", "Zerodha", (money(5000), "r"), (money(500), "r"), (money(4500), "r"), ("<a>edit</a>", "act")],
               ["22 Aug 2026", ("HDFC Bank", "nm"), "Ziyad", "Zerodha", (money(8800), "r"), (money(880), "r"), (money(7920), "r"), ("<a>edit</a>", "act")],
               ["11 Jul 2026", ("HDFC Index Fund – IDCW payout", "nm"), "Ziyad", "Direct", (money(3100), "r"), (money(0), "r"), (money(3100), "r"), ("<a>edit</a>", "act")]])
    body = f"""<div class="strip"><div class="f"><div class="lab">This financial year</div><div class="fig">{money(DIVIDENDS)}</div></div>
<div class="f"><div class="lab">Last financial year</div><div class="fig">{money(94000)}</div></div>
<div class="f"><div class="lab">Yield on cost</div><div class="fig">2.3%</div></div>
<div class="f"><div class="lab">Tax deducted</div><div class="fig">{money(11240)}</div></div></div>
<div class="ban"><span><b>Due soon:</b> Infosys ex-dividend on 21 Nov · TCS ex-dividend on 28 Nov</span><span class="r"><a href="#">Remind me</a></span></div>
<div class="sec"><h2>Dividends received</h2><div class="acts"><span class="btn q">By year and holding</span><span class="btn q">Export</span><span class="btn p"><a href="dividend-new.html">Add dividend</a></span></div></div>{d}
<p class="hint">Dividends are never added to Total Portfolio Value. They count in XIRR only when “Include dividends” is ticked.</p>"""
    return page("dividends.html", "Dividends", "Holdings", "Dividends", body, h1="Dividends", meta="Financial year 2026-27", ctx="pb")


def dividend_new():
    body = f"""<div class="form"><div class="row">{fld("Investment","Infosys · INFY.NS","w3 sel2")}</div>
<div class="panel"><h3>Suggestion</h3><p style="margin:0">Yahoo shows <b>₹20.00 per share</b> with record date 21 Nov 2026. You held 250 units that day, so the expected amount is <b>₹5,000</b>. <span class="btn q sm" style="margin-left:8px">Use this</span></p></div>
<div class="row">{fld("Date received","–","","Enter the day the money arrived","ph")}{fld("Amount actually received","₹","sm ph")}{fld("Tax deducted (optional)","₹","sm ph")}</div>
<div class="row">{fld("Portfolio","Ziyad","sel2")}{fld("Broker","Zerodha","sel2")}{fld("Folio","Not used for shares","ro")}</div>
<div class="acts-row"><span class="btn q">Cancel</span><span class="btn p">Save dividend</span></div></div>"""
    return page("dividend-new.html", "Add dividend", "Holdings", "Dividends", body, h1="Add dividend", meta="", ctx="none",
                anno=["Mutual fund payouts (IDCW) have no suggestion and are typed by hand."])


# ------------------------------------------------------------------ corporate actions
def corp():
    pend = table([("Investment", ""), ("Action", ""), ("Ex-date", ""), ("Effect on this profile", ""), ("", "")],
                 [[("Bajaj Finance", "nm"), "Split 1 : 2" + tag("Detected from Yahoo", ""), "3 Nov 2026", "150 units to 300 units; cost per unit ₹780.00 to ₹390.00; total cost unchanged; purchase dates kept", ("<span class='btn p sm'>Apply</span> <span class='btn q sm'>Not applicable</span>", "act")],
                  [("Larsen & Toubro", "nm"), "Possible split? Check" + tag("Large one-day fall", "amb"), "4 Nov 2026", "Price fell 38% in a day with no recorded action. If it was a split, record it; if not, mark not applicable.", ("<span class='btn q sm'>Record action</span> <span class='btn q sm'>Not applicable</span>", "act")]])
    rec = table([("Investment", ""), ("Action", ""), ("Ex-date", ""), ("Confirmed", "")],
                [[("Infosys", "nm"), "Bonus 1 : 1", "6 Sep 2024", "Applied by Ziyad, 8 Sep 2024"], [("HDFC Bank", "nm"), "Split 1 : 2", "27 Aug 2019", "Applied by Ziyad, 1 Oct 2019"],
                 [("Reliance Industries", "nm"), "Bonus 1 : 1", "28 Oct 2024", "Marked not applicable by Ziyad"]])
    body = f"""<div class="ban wa"><span><b>Why this matters:</b> the price has already changed but your units have not, so these holdings are tagged Provisional until you decide.</span></div>
<div class="tabs"><a class="on">To confirm (2)</a><a>Recorded (3)</a></div>{pend}
<div class="sec"><h2>Recorded</h2><div class="acts"><span class="btn q">Record an action</span></div></div>{rec}"""
    return page("corporate-actions.html", "Corporate actions", "Holdings", "Corporate actions", body, h1="Corporate actions", meta="Split · Bonus · Merger · Other", ctx="none",
                anno=["Each action is recorded once for everyone because it is a fact about the company, but your profile must confirm it before it changes your holdings.",
                      "Original trades are never altered. A merger or demerger opens a lot-and-cost override with a note."])


# ------------------------------------------------------------------ brokers
def brokers():
    t = table([("Broker", "sorted"), ("Holdings", "r"), ("Current value", "r"), ("Transactions", "r"), ("Last transaction", "r")],
              [[("<a href='broker-detail.html'>Zerodha</a>", "nm"), ("9", "r"), (money(BV["Zerodha"]), "r"), ("48", "r"), ("6 Nov 2026", "r")],
               [("Groww", "nm"), ("4", "r"), (money(BV["Groww"]), "r"), ("22", "r"), ("30 Oct 2026", "r")],
               [("Direct (fund house)", "nm"), ("3", "r"), (money(BV["Direct"]), "r"), ("71", "r"), ("12 Oct 2026", "r")],
               [("Interactive Brokers", "nm"), ("2", "r"), (money(BV["Interactive Brokers"]), "r"), ("6", "r"), ("3 Sep 2026", "r")],
               [("Self (PPF, FD, gold)", "nm"), ("3", "r"), (money(BV["Self"]), "r"), ("9", "r"), ("14 Mar 2025", "r")]])
    body = f"""<div class="sec" style="margin-top:20px"><div></div><div class="acts"><span class="btn q"><a href="report-compare-brokers.html">Compare brokers</a></span><span class="btn q">Export</span></div></div>{t}"""
    return page("brokers.html", "Brokers", "Holdings", "Brokers", body, h1="Brokers", meta="5 brokers", ctx="pb",
                anno=["Brokers are added, renamed and hidden in Settings > Brokers. There is no built-in “no broker” choice: where none applies, you add a broker of your own such as “Self”."])


def broker_detail():
    rr = [r for r in R if r["typ"] == "Share"][:5]
    t = table([("Holding", ""), ("Units", "r"), ("Value", "r"), ("Gain", "r"), ("XIRR", "r")],
              [[(r["name"], "nm"), (units(r["u"]), "r"), (money(r["val"]), "r"), (pct(r["gp"]), "r"), (pct(r["x"], signed=False), "r")] for r in rr])
    body = f"""<div class="strip"><div class="f"><div class="lab">Current value</div><div class="fig">{money(BV["Zerodha"])}</div></div><div class="f"><div class="lab">Invested</div><div class="fig">{money(BC["Zerodha"])}</div></div>
<div class="f"><div class="lab">Gain</div><div class="fig">{money(BV["Zerodha"]-BC["Zerodha"], signed=True)}</div></div><div class="f"><div class="lab">XIRR</div><div class="fig">15.3%</div></div></div>
<div class="sec"><h2>Holdings with Zerodha</h2><div class="acts"><span class="btn q">Transactions</span><span class="btn q">Export</span></div></div>{t}"""
    return page("broker-detail.html", "Zerodha", "Holdings", "Brokers", body, h1="Zerodha", meta="Broker", ctx="pb", crumb='<a href="brokers.html">Brokers</a> / Zerodha')
