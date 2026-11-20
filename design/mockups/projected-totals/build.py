"""Builds the Projected Totals chart mockups (static HTML + SVG) from one worked example. Run: python3 build.py"""
from pathlib import Path

MONTHS = ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"]
WD = [20, 18, 10, 22, 21, 21, 20, 20, 16, 21, 20, 21]              # working days entered per month, FY 2026-27
BILLED = [320000, 260000, 110000, 400000, 380000, 360000, 350000, 210000]  # actual, Apr to 19 Nov
APPS = [24, 19, 6, 31, 29, 27, 26, 15]
CUR = 7                                                              # November (index); today 19 Nov 2026
DONE = sum(WD[:CUR]) + round(WD[CUR] * 19 / 30)                     # 132 + 13 = 145
YEAR_WD = sum(WD)                                                    # 230


def projection(actual):
    so_far = sum(actual)
    rate = so_far / DONE
    proj = []
    for i in range(12):
        if i < CUR:
            proj.append((actual[i], 0))
        elif i == CUR:
            proj.append((actual[i], rate * (WD[i] - round(WD[i] * 19 / 30))))
        else:
            proj.append((0, rate * WD[i]))
    return so_far, rate, rate * YEAR_WD, proj


def lakh(v):
    return f"\u20b9{v / 100000:.2f} L"


INK, ACC, PROJ, GRID, MUTED = "#1f2933", "#2457a6", "#2457a6", "#e3e6ea", "#6b7280"
W, H, PL, PR, PT, PB = 860, 320, 64, 20, 20, 36


def frame(maxv, ticks, fmt):
    out = []
    for t in ticks:
        y = PT + (H - PT - PB) * (1 - t / maxv)
        out.append(f'<line x1="{PL}" x2="{W-PR}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}"/>'
                   f'<text x="{PL-8}" y="{y+4:.1f}" text-anchor="end" font-size="11" fill="{MUTED}">{fmt(t)}</text>')
    return "".join(out)


def xpos(i, n=12):
    return PL + (W - PL - PR) * (i + 0.5) / n


def cumulative_chart(actual, label, fmt, maxv, ticks):
    so_far, rate, year, proj = projection(actual)
    # Actual: running total at the end of each month up to November (November = so far).
    run, pts_a = 0, []
    for i in range(CUR + 1):
        run += proj[i][0]
        pts_a.append((xpos(i), run))
    # Projected: starts at the actual so far, then adds the rest of November and each future month.
    pts_p = [(xpos(CUR), so_far)]
    run = so_far
    for i in range(CUR, 12):
        run += proj[i][1]
        if i > CUR:
            pts_p.append((xpos(i), run))
    pts_p[-1] = (pts_p[-1][0], year)
    # pace line: the same daily rate from 1 April
    pace, cum = [], 0
    for i in range(12):
        cum += rate * WD[i]
        pace.append((xpos(i), cum))

    def y(v):
        return PT + (H - PT - PB) * (1 - v / maxv)

    def path(pts):
        return " ".join(f"{'M' if k == 0 else 'L'}{x:.1f},{y(v):.1f}" for k, (x, v) in enumerate(pts))

    svg = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img">', frame(maxv, ticks, fmt)]
    svg.append(f'<path d="{path(pace)}" fill="none" stroke="#9aa5b1" stroke-width="1.5" stroke-dasharray="2 4"/>')
    svg.append(f'<path d="{path(pts_p)}" fill="none" stroke="{PROJ}" stroke-width="2.5" stroke-dasharray="7 5"/>')
    svg.append(f'<path d="{path(pts_a)}" fill="none" stroke="{ACC}" stroke-width="3"/>')
    for x, v in pts_a:
        svg.append(f'<circle cx="{x:.1f}" cy="{y(v):.1f}" r="3.5" fill="{ACC}"/>')
    for x, v in pts_p[1:]:
        svg.append(f'<circle cx="{x:.1f}" cy="{y(v):.1f}" r="3.5" fill="#fff" stroke="{PROJ}" stroke-width="2"/>')
    xe, ve = pts_p[-1]
    svg.append(f'<text x="{xe-6:.1f}" y="{y(ve)-10:.1f}" text-anchor="end" font-size="12" font-weight="600" fill="{PROJ}">Projected {fmt(ve)}</text>')
    xa, va = pts_a[-1]
    svg.append(f'<text x="{xa-6:.1f}" y="{y(va)+20:.1f}" text-anchor="end" font-size="12" font-weight="600" fill="{ACC}">So far {fmt(va)}</text>')
    xt = xpos(CUR) + (W - PL - PR) / 12 * (19 / 30 - 0.5)
    svg.append(f'<line x1="{xt:.1f}" x2="{xt:.1f}" y1="{PT}" y2="{H-PB}" stroke="{INK}" stroke-dasharray="3 3"/><text x="{xt+4:.1f}" y="{PT+12}" font-size="11" fill="{INK}">Today, 19 Nov</text>')
    for i, m in enumerate(MONTHS):
        svg.append(f'<text x="{xpos(i):.1f}" y="{H-12}" text-anchor="middle" font-size="12" fill="{MUTED}">{m}</text>')
    svg.append("</svg>")
    return "".join(svg), so_far, rate, year


def column_chart(actual, fmt, maxv, ticks):
    so_far, rate, year, proj = projection(actual)

    def y(v):
        return PT + (H - PT - PB) * (1 - v / maxv)

    bw = (W - PL - PR) / 12 * 0.6
    svg = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img">',
           '<defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
           f'<line x1="0" y1="0" x2="0" y2="6" stroke="{PROJ}" stroke-width="2" opacity=".45"/></pattern></defs>',
           frame(maxv, ticks, fmt)]
    for i, (a, p) in enumerate(proj):
        x = xpos(i) - bw / 2
        if a:
            svg.append(f'<rect x="{x:.1f}" y="{y(a):.1f}" width="{bw:.1f}" height="{y(0)-y(a):.1f}" fill="{ACC}"/>')
        if p:
            svg.append(f'<rect x="{x:.1f}" y="{y(a+p):.1f}" width="{bw:.1f}" height="{y(a)-y(a+p):.1f}" fill="url(#hatch)" stroke="{PROJ}" stroke-dasharray="4 3"/>')
        top = a + p
        lbl = fmt(top) if i >= CUR else fmt(a)
        svg.append(f'<text x="{xpos(i):.1f}" y="{y(top)-6:.1f}" text-anchor="middle" font-size="10.5" fill="{PROJ if i > CUR else INK}">{lbl}</text>')
        svg.append(f'<text x="{xpos(i):.1f}" y="{H-12}" text-anchor="middle" font-size="12" fill="{MUTED}">{MONTHS[i]}</text>')
    svg.append("</svg>")
    return "".join(svg), proj


def year_chart(past, actual, fmt, maxv, ticks):
    so_far, rate, year, _ = projection(actual)
    bars = past + [("2026-27", so_far, year - so_far)]

    def y(v):
        return PT + (H - PT - PB) * (1 - v / maxv)

    n = len(bars)
    bw = (W - PL - PR) / n * 0.45
    svg = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img">',
           '<defs><pattern id="hatch2" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
           f'<line x1="0" y1="0" x2="0" y2="6" stroke="{PROJ}" stroke-width="2" opacity=".45"/></pattern></defs>',
           frame(maxv, ticks, fmt)]
    for i, (label, a, p) in enumerate(bars):
        cx = xpos(i, n)
        x = cx - bw / 2
        svg.append(f'<rect x="{x:.1f}" y="{y(a):.1f}" width="{bw:.1f}" height="{y(0)-y(a):.1f}" fill="{ACC if p else "#8fa9d4"}"/>')
        if p:
            svg.append(f'<rect x="{x:.1f}" y="{y(a+p):.1f}" width="{bw:.1f}" height="{y(a)-y(a+p):.1f}" fill="url(#hatch2)" stroke="{PROJ}" stroke-dasharray="4 3"/>')
            svg.append(f'<text x="{cx:.1f}" y="{y(a+p)-8:.1f}" text-anchor="middle" font-size="12" font-weight="600" fill="{PROJ}">Projected {fmt(a+p)}</text>')
            svg.append(f'<text x="{cx:.1f}" y="{y(a/2):.1f}" text-anchor="middle" font-size="12" font-weight="600" fill="#fff">So far {fmt(a)}</text>')
        else:
            svg.append(f'<text x="{cx:.1f}" y="{y(a)-8:.1f}" text-anchor="middle" font-size="12" fill="{INK}">{fmt(a)}</text>')
        svg.append(f'<text x="{cx:.1f}" y="{H-12}" text-anchor="middle" font-size="12" fill="{MUTED}">{label}</text>')
    svg.append("</svg>")
    return "".join(svg)


LEGEND = (f'<p class="legend"><span><i style="border-top:3px solid {ACC}"></i>Actual</span>'
          f'<span><i style="border-top:3px dashed {PROJ}"></i>Projected</span>'
          f'<span><i style="border-top:2px dotted #9aa5b1"></i>Pace from 1 April</span></p>')
BAR_LEGEND = (f'<p class="legend"><span><b style="background:{ACC}"></b>Actual</span>'
              f'<span><b class="hatch"></b>Projected (rest of the month / future month)</span></p>')

CSS = """
body{font-family:system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;color:#1f2933;background:#f7f7f5;margin:0;padding:24px}
.card{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:18px 22px;max-width:900px;margin:0 auto 22px}
h1{font-size:20px;font-weight:600;margin:0 0 4px}h2{font-size:15px;font-weight:600;margin:0 0 2px}
.sub{color:#6b7280;font-size:13px;margin:0 0 10px}
.legend{display:flex;gap:18px;font-size:12.5px;color:#374151;margin:4px 0 0}
.legend i{display:inline-block;width:26px;vertical-align:middle;margin-right:6px}
.legend b{display:inline-block;width:14px;height:12px;vertical-align:middle;margin-right:6px}
.legend b.hatch{background:repeating-linear-gradient(45deg,rgba(36,87,166,.45) 0 2px,transparent 2px 6px);outline:1px dashed #2457a6}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.kpi{border:1px solid #e3e6ea;border-radius:8px;padding:10px 12px}
.kpi .l{font-size:12px;color:#6b7280}.kpi .v{font-size:20px;font-weight:600;margin-top:2px}
.kpi .p{font-size:12.5px;color:#2457a6;margin-top:2px}.kpi .p em{font-style:normal;border-bottom:1px dashed #2457a6}
table{border-collapse:collapse;font-size:12.5px;width:100%}th,td{padding:5px 8px;border-bottom:1px solid #eef0f2;text-align:right}
th:first-child,td:first-child{text-align:left}thead th{color:#6b7280;font-weight:600}
td.proj{color:#2457a6;font-style:italic}th.proj{color:#2457a6}
"""


def page(title, body):
    return f"<!doctype html><meta charset=utf-8><title>{title}</title><style>{CSS}</style>{body}"


out = Path(__file__).parent
svg1, so_far, rate, year = cumulative_chart(BILLED, "Billed", lambda v: lakh(v), 4000000, [0, 1000000, 2000000, 3000000, 4000000])
(out / "1-cumulative-line.html").write_text(page("Billed this year, cumulative", f"""
<div class="card"><h1>Amount Billed, FY 2026-27 (running total)</h1>
<p class="sub">Solid: billed so far. Dashed: projected from today to 31 March at the pace so far (&#8377;{rate:,.0f} a working day). Faint dotted: the same pace drawn from 1 April, for comparison.</p>
{svg1}{LEGEND}</div>"""))

svg2, proj = column_chart(BILLED, lambda v: f"{v/100000:.1f}L", 500000, [0, 100000, 200000, 300000, 400000, 500000])
(out / "2-monthly-stacked.html").write_text(page("Billed by month, stacked", f"""
<div class="card"><h1>Amount Billed by month, FY 2026-27</h1>
<p class="sub">Past months: actual only. November: actual so far (solid) with the rest of the month projected on top (hatched). December to March: projected only, each month's working days &times; the rate a working day.</p>
{svg2}{BAR_LEGEND}</div>"""))

svg3 = year_chart([("2023-24", 2850000, 0), ("2024-25", 3210000, 0), ("2025-26", 3460000, 0)], BILLED,
                  lambda v: lakh(v), 4000000, [0, 1000000, 2000000, 3000000, 4000000])
(out / "3-years-stacked.html").write_text(page("Billed by financial year", f"""
<div class="card"><h1>Amount Billed by financial year</h1>
<p class="sub">The current year is one stacked column: billed so far (solid) and the projected rest of the year (hatched). Past years show what was billed.</p>
{svg3}{BAR_LEGEND.replace("rest of the month / future month", "rest of the year")}</div>"""))

a_so_far, a_rate, a_year, a_proj = projection(APPS)
months_cells = "".join(f"<th>{m}</th>" for m in MONTHS)


def row(name, vals, fmt, total, projected):
    cells = []
    for i, (a, p) in enumerate(vals):
        if i < CUR:
            cells.append(f"<td>{fmt(a)}</td>")
        elif i == CUR:
            cells.append(f"<td>{fmt(a)}<br><span class='proj'>month: {fmt(a + p)}</span></td>")
        else:
            cells.append(f"<td class='proj'>{fmt(p)}</td>")
    return f"<tr><td>{name}</td>{''.join(cells)}<td>{total}</td><td class='proj'>{projected}</td></tr>"


rows = (row("Amount Billed (&#8377; L)", projection(BILLED)[3], lambda v: f"{v / 100000:.2f}", f"{so_far / 100000:.2f}", f"{year / 100000:.2f}")
        + row("Appearances", a_proj, lambda v: f"{v:.0f}", a_so_far, f"{a_year:.0f}")
        + "<tr><td>Working days</td>" + "".join(f"<td>{w}</td>" for w in WD) + f"<td>{DONE} done</td><td class='proj'>{YEAR_WD}</td></tr>")
boxes = (f'<div class="kpi"><div class="l">Billed This Year</div><div class="v">{lakh(so_far)}</div><div class="p">Projected: <em>{lakh(year)}</em></div></div>'
         f'<div class="kpi"><div class="l">Appearances This Year</div><div class="v">{a_so_far}</div><div class="p">Projected: <em>{a_year:.0f}</em></div></div>'
         f'<div class="kpi"><div class="l">Fees / Day This Year</div><div class="v">&#8377;{rate:,.0f}</div><div class="p">{DONE} of {YEAR_WD} working days done</div></div>'
         f'<div class="kpi"><div class="l">Appearances / Week This Year</div><div class="v">{a_rate * 5:.1f}</div><div class="p">A rate: not projected</div></div>')
(out / "4-boxes-and-table.html").write_text(page("Projected boxes and table",
    '<div class="card"><h1>Dashboard boxes</h1><p class="sub">Each total for This Year gains a projected line under the actual figure.</p>'
    f'<div class="kpis">{boxes}</div></div>'
    '<div class="card"><h1>Statistics, Standard table (by month)</h1><p class="sub">Projected figures in blue italics. The current month shows the actual so far and, under it, the projected whole month. A Projected column follows Total.</p>'
    f'<table><thead><tr><th>Metric</th>{months_cells}<th>Total so far</th><th class="proj">Projected</th></tr></thead><tbody>{rows}</tbody></table></div>'))

print("done", DONE, YEAR_WD, round(so_far), round(rate), round(year), a_so_far, round(a_year, 1),
      [round(p) for a, p in projection(BILLED)[3][CUR:]])
