"""Hand-drawn SVG line charts (plan 25.3: no chart library; every line differs by pattern as well as shade; a table version too).
Pure Python. ``line_chart`` returns a dict the template draws: the polylines, axis ticks and the legend."""
import json
import math
from datetime import date
from decimal import Decimal

from investments.money_auto import format_indian

PATTERNS = ("", "6 4", "2 3", "10 3 2 3", "1 2", "8 2")
SHADES = ("var(--s1)", "var(--s2)", "var(--s3)", "var(--ox)", "var(--s2)", "var(--s3)")


def _small_step(raw):
    """A 1, 2 or 5 step (times a power of ten) at or above ``raw``, for a range under five units."""
    raw = max(raw, 1e-6)
    power = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if m * power >= raw:
            return round(m * power, 6)
    return round(10 * power, 6)


def _tick_labels(ticks):
    """One label per tick; decimals are added until no two labels match (a flat price line spans well under one rupee)."""
    for places in range(0, 5):
        labels = [_fmt(t, places) for t in ticks]
        if len(set(labels)) == len(labels):
            return labels
    return labels


def _nice_ticks(lo, hi, count=5):
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    span = hi - lo
    raw = span / count
    magnitude = 10 ** (len(str(int(abs(raw)))) - 1) if raw >= 1 else 1
    step = max(magnitude, round(raw / magnitude) * magnitude) if raw >= 1 else _small_step(raw)
    start = (lo // step) * step
    ticks = []
    v = start
    while v <= hi + step * 0.5 and len(ticks) < 12:
        if v >= lo - step * 0.5:
            ticks.append(v)
        v += step
    return ticks


def line_chart(days, lines, width=900, height=280, pad=(56, 16, 24, 30), markers=None, by_date=False, notes=None, paired=False):
    """``lines`` is ``[(label, [value or None per day])]``. With ``by_date`` the x position follows the date (the days are not evenly
    spaced, as when every Manual Price History entry is added to the sample days), else the position in the list. ``notes`` is
    ``[[date, text]]`` for a date that appears twice in ``days`` (a sale: the point before it, then the point after, so the line drops
    vertically): the text is shown in the hover tooltip for both points and as the sale marker's title. With ``paired`` the lines come in
    pairs (a line, then its moving average): the average takes its line's shade, a fine dotted pattern and a thinner stroke. Returns ``{"width","height","paths","yticks","xticks","legend"}``."""
    left, right, top, bottom = pad
    values = [float(v) for _l, vs in lines for v in vs if v is not None]
    if not values or len(days) < 2:
        return None
    lo, hi = min(values), max(values)
    ticks = _nice_ticks(lo, hi)
    lo, hi = min(lo, ticks[0]), max(hi, ticks[-1])
    plot_w, plot_h = width - left - right, height - top - bottom
    n = len(days) - 1

    span = (days[-1] - days[0]).days if by_date else 0

    def x(i):
        if by_date and span > 0:
            return left + plot_w * (days[i] - days[0]).days / span
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
        if paired:
            pair, is_average = divmod(k, 2)
            paths.append({"label": label, "points": [" ".join(s) for s in segments], "dash": "2 2" if is_average else PATTERNS[pair % len(PATTERNS)],
                          "stroke": SHADES[pair % len(SHADES)], "width": 1.2 if is_average else (2 if pair == 0 else 1.5)})
            continue
        paths.append({"label": label, "points": [" ".join(s) for s in segments], "dash": PATTERNS[k % len(PATTERNS)],
                      "stroke": SHADES[k % len(SHADES)], "width": 2 if k == 0 else 1.5})
    yticks = [{"y": round(y(t), 1), "label": label} for t, label in zip(ticks, _tick_labels(ticks))]
    marks = sorted({0, n // 4, n // 2, 3 * n // 4, n})
    xticks = [{"x": round(x(i), 1), "label": days[i].strftime("%b %Y" if (days[-1] - days[0]).days > 120 else "%-d %b")} for i in marks]
    # markers: [(date, label, "buy" or "sell")] drawn on the first line at the nearest sample date (the purchases and sales on a price chart)
    marks_out = []
    first = lines[0][1] if lines else []
    noted = {(date.fromisoformat(d) if isinstance(d, str) else d): t for d, t in notes or []}
    for day, label, kind in markers or []:
        if isinstance(day, str):   # markers kept in a cached payload carry ISO dates
            day = date.fromisoformat(day)
        label = noted.get(day, label) if kind == "sell" else label
        i = min(range(len(days)), key=lambda k: abs((days[k] - day).days))
        if first[i] is not None:
            marks_out.append({"x": round(x(i), 1), "y": round(y(first[i]), 1), "label": label, "kind": kind})
    hover = _hover(days, lines, x, noted)
    return {"width": width, "height": height, "paths": paths, "hover": hover, "yticks": yticks, "xticks": xticks, "left": left, "right": width - right,
            "top": top, "bottom": height - bottom, "markers": marks_out}


HOVER_POINTS = 150


def _hover(days, lines, x, noted=None):
    """Compact JSON for static/js/investments/chart-hover.js: x positions, date labels and each line's formatted values at up to
    HOVER_POINTS sample days (always including the first and last). Plain text; the template escapes it into a data attribute."""
    count = len(days)
    step = max(1, -(-count // HOVER_POINTS))
    note_at = {i: noted[day] for i, day in enumerate(days) if noted and day in noted}
    idx = sorted(set(range(0, count, step)) | {count - 1} | set(note_at))
    series = []
    for label, vs in lines:
        series.append({"l": str(label), "v": ["" if vs[i] is None else format_indian(vs[i]) for i in idx]})
    out = {"x": [round(x(i), 1) for i in idx], "d": [days[i].strftime("%-d %b %Y") for i in idx], "s": series}
    if note_at:
        out["n"] = {str(k): note_at[i] for k, i in enumerate(idx) if i in note_at}      # keyed by the position in this list
    return json.dumps(out, separators=(",", ":"), ensure_ascii=False)


def _fmt(v, places=0):
    v = float(v)
    if abs(v) >= 1e7:
        return f"{v / 1e7:.{max(1, places)}f} cr"
    if abs(v) >= 1e5:
        return f"{v / 1e5:.{max(1, places)}f} lac"
    return format_indian(v, places)


def as_float(v):
    return float(v) if isinstance(v, Decimal) else v


def sparkline(values, width=72, height=22, pad=2):
    """A tiny trend line for a table cell: ``{"points", "up", "width", "height", "change"}`` or None with fewer than two values.
    ``up`` is True when the last value is at or above the first; ``change`` is that move as a fraction of the first."""
    vals = [float(v) for v in values if v is not None]
    if len(vals) < 2:
        return None
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    n = len(vals) - 1
    pts = " ".join(f"{pad + (width - 2 * pad) * i / n:.1f},{pad + (height - 2 * pad) * (1 - (v - lo) / span):.1f}" for i, v in enumerate(vals))
    first = vals[0]
    return {"points": pts, "up": vals[-1] >= first, "width": width, "height": height,
            "change": (vals[-1] - first) / first if first else 0.0}
