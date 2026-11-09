"""Hand-drawn SVG line charts (plan 25.3: no chart library; every line differs by pattern as well as shade; a table version too).
Pure Python. ``line_chart`` returns a dict the template draws: the polylines, axis ticks and the legend."""
from decimal import Decimal

PATTERNS = ("", "6 4", "2 3", "10 3 2 3", "1 2", "8 2")
SHADES = ("var(--s1)", "var(--s2)", "var(--s3)", "var(--ox)", "var(--s2)", "var(--s3)")


def _nice_ticks(lo, hi, count=5):
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    span = hi - lo
    raw = span / count
    magnitude = 10 ** (len(str(int(abs(raw)))) - 1) if raw >= 1 else 1
    step = max(magnitude, round(raw / magnitude) * magnitude) if raw >= 1 else round(raw, 2) or 0.01
    start = (lo // step) * step
    ticks = []
    v = start
    while v <= hi + step * 0.5 and len(ticks) < 12:
        if v >= lo - step * 0.5:
            ticks.append(v)
        v += step
    return ticks


def line_chart(days, lines, width=900, height=280, pad=(56, 16, 24, 30)):
    """``lines`` is ``[(label, [value or None per day])]``. Returns ``{"width","height","paths","yticks","xticks","legend"}``."""
    left, right, top, bottom = pad
    values = [float(v) for _l, vs in lines for v in vs if v is not None]
    if not values or len(days) < 2:
        return None
    lo, hi = min(values), max(values)
    ticks = _nice_ticks(lo, hi)
    lo, hi = min(lo, ticks[0]), max(hi, ticks[-1])
    plot_w, plot_h = width - left - right, height - top - bottom
    n = len(days) - 1

    def x(i):
        return left + plot_w * i / n

    def y(v):
        return top + plot_h * (1 - (float(v) - lo) / ((hi - lo) or 1))

    paths = []
    for k, (label, vs) in enumerate(lines):
        segments, current = [], []
        for i, v in enumerate(vs):
            if v is None:
                if current:
                    segments.append(current)
                current = []
            else:
                current.append(f"{x(i):.1f},{y(v):.1f}")
        if current:
            segments.append(current)
        paths.append({"label": label, "points": [" ".join(s) for s in segments], "dash": PATTERNS[k % len(PATTERNS)],
                      "stroke": SHADES[k % len(SHADES)], "width": 2 if k == 0 else 1.5})
    yticks = [{"y": round(y(t), 1), "label": _fmt(t)} for t in ticks]
    marks = sorted({0, n // 4, n // 2, 3 * n // 4, n})
    xticks = [{"x": round(x(i), 1), "label": days[i].strftime("%b %Y" if (days[-1] - days[0]).days > 120 else "%-d %b")} for i in marks]
    return {"width": width, "height": height, "paths": paths, "yticks": yticks, "xticks": xticks, "left": left, "right": width - right,
            "top": top, "bottom": height - bottom}


def _fmt(v):
    v = float(v)
    if abs(v) >= 1e7:
        return f"{v / 1e7:.1f} cr"
    if abs(v) >= 1e5:
        return f"{v / 1e5:.1f} lac"
    if abs(v) >= 1e3:
        return f"{v / 1e3:.0f} k"
    return f"{v:.0f}"


def as_float(v):
    return float(v) if isinstance(v, Decimal) else v
