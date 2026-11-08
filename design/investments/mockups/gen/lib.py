# ruff: noqa
"""Shared helpers for the Investments mockups: number formatting, illustrative data, SVG charts and page layout.
All figures are ILLUSTRATIVE (invented) and exist only to show what the pages look like."""
import math
import os
import random
from html import escape

OUT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)) + os.sep

# ------------------------------------------------------------------ numbers
def group_indian(n: int) -> str:
    s = str(abs(int(n)))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return s


def full(n, d=0):
    sign = "−" if n < 0 else ""
    a = abs(n)
    if d:
        whole = int(a)
        frac = f"{a - whole:.{d}f}"[1:]
        return f"{sign}₹{group_indian(whole)}{frac}"
    return f"{sign}₹{group_indian(round(a))}"


def auto(n):
    a = abs(n)
    sign = "−" if n < 0 else ""
    if a >= 1e7:
        return f"{sign}₹{a/1e7:.2f} cr"
    if a >= 1e5:
        return f"{sign}₹{a/1e5:.2f} lac"
    if a >= 1e3:
        return f"{sign}₹{a/1e3:.2f} k"
    return f"{sign}₹{round(a)}"


def money(n, signed=False, cls=""):
    """A rupee amount that obeys the Auto/Full toggle. Pointing at it shows the exact figure."""
    a, f = auto(abs(n)), full(abs(n))
    if signed:
        sg = "+" if n > 0 else ("−" if n < 0 else "")
        a, f = sg + a, sg + f
        cls = cls or ("g" if n > 0 else "l" if n < 0 else "")
    elif n < 0:
        a, f = "−" + a, "−" + f
    return f'<span class="m {cls}" data-auto="{a}" data-full="{f}" title="{f}">{a}</span>'


def pct(x, signed=True, d=1, colour=True):
    sg = "+" if x > 0 and signed else ("−" if x < 0 else "")
    cls = ("g" if x > 0 else "l" if x < 0 else "") if colour and signed else ""
    return f'<span class="{cls}">{sg}{abs(x):.{d}f}%</span>'


def px(x, d=2):
    """A per-unit price: never changed by the toggle."""
    whole = int(x)
    frac = int(round((x - whole) * 10 ** d))
    if frac >= 10 ** d:
        whole, frac = whole + 1, 0
    return f"₹{group_indian(whole)}.{frac:0{d}d}"


def units(x, d=0):
    if d == 0:
        return group_indian(int(x))
    whole = int(x)
    return f"{group_indian(whole)}.{int(round((x - whole) * 10**d)):0{d}d}"


# ------------------------------------------------------------------ illustrative data
FX = 88.0  # INR per USD (illustrative)

# name, short, type, code, units, udec, avg, price, pe, xirr, bench, flag, sector, portfolio
H = [
    ("Reliance Industries", "Share", "RELIANCE.NS", 300, 0, 1090.00, 1320.00, 24.1, 13.1, 11.0, "", "Energy"),
    ("Tata Consultancy Services", "Share", "TCS.NS", 120, 0, 3250.00, 3480.00, 29.5, 9.8, 11.2, "", "IT"),
    ("Infosys", "Share", "INFY.NS", 250, 0, 1420.00, 1565.00, 24.8, 12.4, 11.0, "", "IT"),
    ("HDFC Bank", "Share", "HDFCBANK.NS", 400, 0, 1510.00, 1735.00, 19.6, 14.9, 11.0, "", "Banking"),
    ("ITC", "Share", "ITC.NS", 800, 0, 385.00, 428.00, 26.3, 10.5, 11.0, "", "FMCG"),
    ("Larsen & Toubro", "Share", "LT.NS", 60, 0, 3010.00, 3640.00, 32.4, 17.2, 11.0, "", "Industrials"),
    ("Asian Paints", "Share", "ASIANPAINT.NS", 90, 0, 3150.00, 2480.00, 52.0, -6.2, 10.1, "alert", "Consumer"),
    ("Bajaj Finance", "Share", "BAJFINANCE.NS", 150, 0, 780.00, 912.00, 31.8, 16.8, 11.0, "prov", "Financials"),
    ("Parag Parikh Flexi Cap Fund – Direct Growth", "Mutual fund", "AMFI 122639", 4820.512, 3, 52.30, 81.46, None, 18.6, 12.9, "await", "Flexi cap"),
    ("HDFC Index Fund – Nifty 50 – Direct Growth", "Mutual fund", "AMFI 119063", 9100.250, 3, 158.00, 214.35, None, 11.4, 11.0, "", "Index"),
    ("SBI Small Cap Fund – Direct Growth", "Mutual fund", "AMFI 125497", 2640.800, 3, 105.20, 168.90, None, 21.3, 14.2, "", "Small cap"),
    ("Public Provident Fund – Ziyad", "Alternative", "no code", 1, 0, 610000.00, 785000.00, None, 7.1, 7.0, "", "Debt"),
    ("HDFC Bank FD (7.1%, to 14 Mar 2027)", "Alternative", "no code", 1, 0, 500000.00, 546000.00, None, 7.1, 7.0, "", "Debt"),
    ("Gold – physical (grams)", "Alternative", "no code", 60, 0, 6100.00, 9400.00, None, 9.4, 8.2, "stale", "Gold"),
    ("Apple Inc (USD)", "Foreign", "AAPL", 40, 0, 168.00 * FX, 228.00 * FX, 34.1, 15.7, 12.5, "", "Technology"),
    ("Vanguard S&P 500 ETF (USD)", "Foreign", "VOO", 15, 0, 430.00 * FX, 560.00 * FX, None, 14.4, 12.5, "", "Index"),
]


def rows():
    out = []
    for r in H:
        name, typ, code, u, ud, avg, price, pe, x, b, flag, sector = r
        cost, val = u * avg, u * price
        out.append(dict(name=name, typ=typ, code=code, u=u, ud=ud, avg=avg, price=price, pe=pe, x=x, b=b,
                        flag=flag, sector=sector, cost=cost, val=val, gain=val - cost, gp=(val / cost - 1) * 100))
    return out


R = rows()
INVESTED = sum(r["cost"] for r in R)
VALUE = sum(r["val"] for r in R)
GAIN = VALUE - INVESTED
PORT_XIRR, BENCH_XIRR = 14.2, 11.8
DIVIDENDS = 112400


def _share(pred, key="val"):
    return sum(r[key] for r in R if pred(r)) / sum(r[key] for r in R) * 100


T_SHARE, T_FUND, T_ALT, T_FOR = (_share(lambda r, t=t: r["typ"] == t) for t in ("Share", "Mutual fund", "Alternative", "Foreign"))
A_DEBT = _share(lambda r: r["sector"] == "Debt")
A_GOLD = _share(lambda r: r["sector"] == "Gold")
A_EQ = 100 - A_DEBT - A_GOLD


def _by_type(t, key):
    return sum(r[key] for r in R if r["typ"] == t)


# which broker holds what (illustrative): shares split Zerodha 78% / Groww 22%, funds Direct, foreign IBKR, alternative Self
BV = {"Zerodha": _by_type("Share", "val") * 0.78, "Groww": _by_type("Share", "val") * 0.22, "Direct": _by_type("Mutual fund", "val"),
      "Interactive Brokers": _by_type("Foreign", "val"), "Self": _by_type("Alternative", "val")}
BC = {"Zerodha": _by_type("Share", "cost") * 0.78, "Groww": _by_type("Share", "cost") * 0.22, "Direct": _by_type("Mutual fund", "cost"),
      "Interactive Brokers": _by_type("Foreign", "cost"), "Self": _by_type("Alternative", "cost")}

SECT = {  # sectoral index and its XIRR over the same cash flows (illustrative); funds and alternatives have none
    "Reliance Industries": ("Nifty Energy", 9.2), "Tata Consultancy Services": ("Nifty IT", 8.4), "Infosys": ("Nifty IT", 8.4),
    "HDFC Bank": ("Nifty Bank", 10.6), "ITC": ("Nifty FMCG", 12.1), "Larsen & Toubro": ("Nifty Infrastructure", 13.4),
    "Asian Paints": ("Nifty India Consumption", 12.3), "Bajaj Finance": ("Nifty Financial Services", 11.5),
    "Apple Inc (USD)": ("Nasdaq 100 (in ₹)", 16.8), "Vanguard S&P 500 ETF (USD)": ("S&P 500 (in ₹)", 14.0),
}


# ------------------------------------------------------------------ svg charts
def series(seed, n, start, drift, vol):
    rnd = random.Random(seed)
    v, out = start, []
    for _ in range(n):
        v *= 1 + rnd.gauss(drift, vol)
        out.append(v)
    return out


def _scale(vals, lo, hi, pad=0.06):
    span = (hi - lo) or 1
    lo, hi = lo - span * pad, hi + span * pad
    return lo, hi


def _nice_ticks(lo, hi, target=5):
    span = (hi - lo) or 1
    raw = span / target
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=mag)
    t0 = math.floor(lo / step) * step
    t1 = math.ceil(hi / step) * step
    out, v = [], t0
    while v <= t1 + step * 1e-6:
        out.append(v)
        v += step
    return out


def line_chart(lines, labels, w=900, h=300, ymin=None, ymax=None, fmt=lambda v: f"{v:.0f}", markers=None, yfmt=None):
    """lines: [(name, [values], style)] with style in solid/dash/dot/mid. labels: [(index, text)] for the x axis."""
    ml, mr, mt, mb = 58, 150, 12, 28
    n = len(lines[0][1])
    allv = [v for _, vs, _ in lines for v in vs]
    ticks = _nice_ticks(ymin if ymin is not None else min(allv), ymax if ymax is not None else max(allv))
    lo, hi = ticks[0], ticks[-1]
    iw, ih = w - ml - mr, h - mt - mb

    def X(i):
        return ml + iw * i / (n - 1)

    def Y(v):
        return mt + ih * (1 - (v - lo) / (hi - lo))

    s = [f'<svg class="ch" viewBox="0 0 {w} {h}" role="img" aria-label="Line chart">']
    for v in ticks:
        y = Y(v)
        s.append(f'<line x1="{ml}" x2="{w-mr}" y1="{y:.1f}" y2="{y:.1f}" stroke="#d9d3c5" stroke-width="1"/>')
        s.append(f'<text x="{ml-8}" y="{y+4:.1f}" text-anchor="end">{(yfmt or fmt)(v)}</text>')
    for i, t in labels:
        s.append(f'<text x="{X(i):.1f}" y="{h-8}" text-anchor="middle">{t}</text>')
        s.append(f'<line x1="{X(i):.1f}" x2="{X(i):.1f}" y1="{mt+ih}" y2="{mt+ih+4}" stroke="#8d8577"/>')
    styles = {"solid": ('#1e1c19', 2.2, ''), "dash": ('#8d8577', 1.8, '6 4'), "dot": ('#5a5348', 1.8, '1.5 3.5'),
              "ox": ('#7a1f2b', 1.8, ''), "mid": ('#8d8577', 1.8, '')}
    ends = []
    for name, vs, st in lines:
        col, sw, da = styles[st]
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vs))
        s.append(f'<polyline fill="none" stroke="{col}" stroke-width="{sw}" stroke-dasharray="{da}" points="{pts}"/>')
        ends.append([Y(vs[-1]) + 4, name, vs[-1]])
    # end labels: keep at least 14 units apart so they never overlap
    ends.sort(key=lambda e: e[0])
    for k in range(1, len(ends)):
        if ends[k][0] - ends[k - 1][0] < 14:
            ends[k][0] = ends[k - 1][0] + 14
    for y, name, v in ends:
        s.append(f'<text class="lg" x="{X(n-1)+8:.1f}" y="{y:.1f}">{name} {fmt(v)}</text>')
    if markers:
        for i, kind in markers:
            v = lines[0][1][i]
            x, y = X(i), Y(v)
            if kind == "b":
                s.append(f'<path d="M{x:.1f},{y-9:.1f} l6,11 h-12 z" fill="#2d5a3d"/>')
            else:
                s.append(f'<path d="M{x:.1f},{y+9:.1f} l6,-11 h-12 z" fill="#a8441f"/>')
    s.append("</svg>")
    return "".join(s)


def bars_rows(items, total=None, unit="%"):
    """Horizontal bars: items [(label, value)], value in percent of the whole."""
    total = total or max(v for _, v in items)
    out = ['<div class="bars">']
    for label, v in items:
        out.append(f'<div class="b"><span>{label}</span><span class="tr"><i style="width:{v/total*100:.1f}%"></i></span>'
                   f'<span class="v">{v:.1f}{unit}</span></div>')
    out.append("</div>")
    return "".join(out)


def stacked(items):
    cols = ["#1e1c19", "#5a5348", "#8d8577", "#b9b2a3", "#d9d3c5", "#efeadd"]
    seg = "".join(f'<i style="width:{v:.1f}%;background:{cols[i % 6]}"></i>' for i, (_, v) in enumerate(items))
    keys = "".join(f'<span><i style="background:{cols[i % 6]};border:1px solid #8d8577"></i>{l} {v:.1f}%</span>'
                   for i, (l, v) in enumerate(items))
    return f'<div class="stack">{seg}</div><div class="keys">{keys}</div>'


def grouped_bars(cats, a, b, w=760, h=250, an="Portfolio", bn="Nifty 50"):
    ml, mr, mt, mb = 44, 10, 14, 30
    iw, ih = w - ml - mr, h - mt - mb
    lo, hi = min(0, min(a + b)) - 4, max(a + b) + 6
    def Y(v): return mt + ih * (1 - (v - lo) / (hi - lo))
    s = [f'<svg class="ch" viewBox="0 0 {w} {h}" role="img" aria-label="Year by year returns">',
         '<defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
         '<rect width="6" height="6" fill="#fcfbf8"/><line x1="0" y1="0" x2="0" y2="6" stroke="#5a5348" stroke-width="2"/></pattern></defs>']
    for k in range(0, 6):
        v = lo + (hi - lo) * k / 5
        s.append(f'<line x1="{ml}" x2="{w-mr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="#d9d3c5"/>'
                 f'<text x="{ml-6}" y="{Y(v)+4:.1f}" text-anchor="end">{v:.0f}%</text>')
    s.append(f'<line x1="{ml}" x2="{w-mr}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" stroke="#1e1c19"/>')
    gw = iw / len(cats)
    for i, c in enumerate(cats):
        x0 = ml + gw * i + gw * 0.18
        bw = gw * 0.30
        for j, (v, fill) in enumerate(((a[i], "#1e1c19"), (b[i], "url(#hatch)"))):
            y1, y2 = sorted((Y(v), Y(0)))
            s.append(f'<rect x="{x0 + j*bw:.1f}" y="{y1:.1f}" width="{bw-2:.1f}" height="{max(y2-y1,1):.1f}" fill="{fill}" stroke="#1e1c19" stroke-width="1"/>')
            s.append(f'<text x="{x0 + j*bw + bw/2 - 1:.1f}" y="{(y1-4) if v>=0 else (y2+12):.1f}" text-anchor="middle">{v:.0f}</text>')
        s.append(f'<text x="{ml + gw*i + gw/2:.1f}" y="{h-9}" text-anchor="middle">{c}</text>')
    s.append("</svg>")
    leg = f'<div class="legend"><span><i></i>{an} (solid bar)</span><span><i class="d"></i>{bn} (hatched bar)</span></div>'
    return "".join(s) + leg


# ------------------------------------------------------------------ layout
GROUPS = [
    ("Overview", "dashboard.html", []),
    ("Holdings", "holdings.html", [
        ("Investments", "holdings.html"), ("Transactions", "transactions.html"), ("Dividends", "dividends.html"),
        ("Corporate actions", "corporate-actions.html"), ("Brokers", "brokers.html")]),
    ("Reports", "performance.html", [
        ("Performance", "performance.html"), ("Charts", "charts.html"), ("Total Portfolio Value", "value.html"),
        ("Annual Report", "annual.html"), ("Other reports", "reports.html"), ("History", "history.html")]),
    ("Alerts", "alerts.html", []),
    ("Settings", "settings-general.html", [
        ("General", "settings-general.html"), ("Brokers", "settings-brokers.html"), ("Alerts", "settings-alerts.html"),
        ("Display", "settings-display.html"), ("Pages", "settings-pages.html"), ("Insights", "settings-insights.html"),
        ("Price sources", "admin-prices.html"), ("Catalogue", "admin-catalogue.html")]),
]

JS = """<script>
(function(){var k='inv-mock-num',m=localStorage.getItem(k)||'auto';
function apply(){document.querySelectorAll('.m').forEach(function(e){e.textContent=e.getAttribute('data-'+m)});
document.querySelectorAll('.toggle span').forEach(function(s){s.classList.toggle('on',s.getAttribute('data-m')===m)})}
document.querySelectorAll('.toggle span').forEach(function(s){s.addEventListener('click',function(){m=s.getAttribute('data-m');localStorage.setItem(k,m);apply()})});
apply()})();
</script>"""


def sel(label, value, off=False):
    return f'<div class="sel{" off" if off else ""}"><span>{label}</span><b>{value}</b></div>'


def page(fn, title, group, sub, body, h1=None, meta="", ctx="full", anno=None, titlebar=True, crumb=None, search_open=False):
    """ctx: 'full' (portfolio+broker+as-at), 'pb' (portfolio+broker), 'none' (only utilities)."""
    nav = []
    for g, href, subs in GROUPS:
        on = " on" if g == group else ""
        badge = '<span class="dot">3</span>' if g == "Alerts" else ""
        nav.append(f'<a class="nl{on}" href="{href}">{g}{badge}</a>')
    subnav = ""
    for g, href, subs in GROUPS:
        if g == group and subs:
            items = []
            for label, h in subs:
                cls = ("on" if label == sub else "") + (" adm" if label in ("Price sources", "Catalogue") else "")
                items.append(f'<a class="{cls.strip()}" href="{h}">{label}</a>')
            subnav = f'<nav class="sub">{"".join(items)}</nav>'
    if ctx == "none":
        ctxhtml = '<div class="ctx"></div>'
    else:
        parts = [sel("Portfolio", "All Portfolios"), sel("Broker", "All brokers")]
        if ctx == "full":
            parts.append(sel("As at", "Today, 6 Nov 2026"))
        ctxhtml = f'<div class="ctx">{"".join(parts)}</div>'
    util = ('<div class="util"><span class="btn q">Update Prices</span>'
            '<div class="toggle" title="Number display"><span data-m="auto" class="on">Auto</span><span data-m="full">Full</span></div></div>')
    status = '<div class="status">Updated <b>6 Nov 2026, 2:00 am</b> · prices as of close 5 Nov · 2 not updated</div>'
    tb = ""
    if titlebar:
        tb = f'<div class="titlebar"><h1 class="t">{h1 or title}</h1><div class="meta">{meta}</div></div>'
    cr = f'<div class="crumb">{crumb}</div>' if crumb else ""
    searchpop = ""
    if search_open:
        searchpop = ('<div class="search-pop"><div class="f"><div class="in">reli<span style="border-left:1.5px solid var(--ink);height:20px;margin-left:1px"></span></div>'
                     '<span class="btn p">Search</span></div></div>')
    an = ""
    if anno:
        li = "".join(f"<li>{a}</li>" for a in anno)
        an = f'<div class="anno"><h4>Mockup note</h4><ul>{li}</ul></div>'
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · Investments (mockup)</title><link rel="stylesheet" href="mockup.css"></head>
<body><div class="page">
<header class="site-header"><div class="brand-row"><span class="brand">Investments<span> · Madon</span></span><span class="profile-switch" title="Switch profile"><svg viewBox="0 0 16 16" width="16" height="16"><path d="M4 6l4-3.5L12 6M4 10l4 3.5L12 10" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg></span><span class="history-buttons"><span class="ic" title="Back"><svg viewBox="0 0 16 16" width="18" height="18"><path d="M14 8H2M7 3L2 8l5 5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></span><span class="ic" title="Forward"><svg viewBox="0 0 16 16" width="18" height="18"><path d="M2 8h12M9 3l5 5-5 5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></span></span><span class="menu-btn">Menu</span></div><nav class="program-nav" aria-label="Main">{"".join(nav)}<span class="who">ziyad</span><a class="ic{" open" if search_open else ""}" title="Search (Opt F)"><svg viewBox="0 0 24 24" width="22" height="22"><circle cx="10.5" cy="10.5" r="6" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M15 15l5.5 5.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></a><a class="ic" href="dashboard.html" title="Home"><svg viewBox="0 0 24 24" width="22" height="22"><path d="M3 11.5L12 4l9 7.5M5.5 10v10h13V10M10 20v-6h4v6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></a></nav></header>
{searchpop}{subnav}
<div class="tools">{ctxhtml}{util}{status}</div>
{cr}{tb}
{body}
{an}
<footer class="f"><span>Mockup · all figures are invented</span><span><a href="index.html">All mockup pages</a></span></footer>
</div>{JS}</body></html>"""
    with open(OUT + fn, "w") as f:
        f.write(html)
    return fn


def table(head, body_rows, foot=None, cls="led", caption=None):
    """head: list of (label, css) ; body_rows: list of list of cell html (td attributes via tuple (html, css))."""
    h = "".join(f'<th class="{c}">{l}</th>' for l, c in head)
    out = [f'<div class="tw"><table class="{cls}">']
    if caption:
        out.append(f"<caption>{caption}</caption>")
    out.append(f"<thead><tr>{h}</tr></thead><tbody>")
    for r in body_rows:
        if isinstance(r, str):
            out.append(r)
            continue
        tds = ""
        for c in r:
            if isinstance(c, tuple):
                tds += f'<td class="{c[1]}">{c[0]}</td>'
            else:
                tds += f"<td>{c}</td>"
        out.append(f"<tr>{tds}</tr>")
    out.append("</tbody>")
    if foot:
        out.append(f"<tfoot><tr>{foot}</tr></tfoot>")
    out.append("</table></div>")
    return "".join(out)


def tag(text, kind=""):
    return f'<span class="tag {kind}">{text}</span>'


def fld(label, value, cls="", note="", ph=False, err=False):
    c = f"in {cls}" + (" ph" if ph else "") + (" err" if err else "")
    n = f'<span class="note{" err" if err else ""}">{note}</span>' if note else ""
    return f'<div class="fld"><label>{label}</label><div class="{c.strip()}">{value}</div>{n}</div>'
