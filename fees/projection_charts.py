"""Server-drawn SVG charts for Projected Totals on Statistics > Standard (owner round 2026-11).

* ``running_total_svg``: the current financial year month by month as a running total. Solid up to today (what happened),
  dashed from today to 31 March (projected at the pace so far); a faint dotted line draws the same pace from 1 April.
* ``year_columns_svg``: one column a financial year. The current year is stacked: so far (solid) and the projected rest of
  the year (hatched) on top.

They only draw: the figures come from ``fees.services.statistics.projection``. Every text is escaped; colours come from the
page's CSS classes (``.pc-*`` in ledger-statistics.css), so the chart follows the colour theme.

Hovering (or touching, or the arrow keys on the focused chart) shows the figures of the month or year under the cursor, the
actual and the projected side by side: ``static/js/investments/chart-hover.js`` reads the ``data-hover`` attribute.
"""
import json
from decimal import Decimal

from django.utils.html import escape
from django.utils.safestring import mark_safe

from fees.services.money import format_money

W, H = 860, 300
PAD_L, PAD_R, PAD_T, PAD_B = 70, 24, 24, 34


def _nice_max(value):
    """A round top for the axis, at least ``value`` (1, 2, 2.5 or 5 x a power of ten)."""
    value = float(value or 0)
    if value <= 0:
        return 1.0
    power = 10 ** (len(str(int(value))) - 1)
    for step in (1, 2, 2.5, 5, 10):
        if step * power >= value:
            return step * power
    return 10 * power


def _label(value, money, unit):
    if money:
        return format_money(Decimal(str(value)), unit=unit)
    return f"{float(value):,.0f}"


def _axis_label(value, money):
    return format_money(Decimal(str(value)), unit="truncated") if money else f"{value:,.0f}"


class _Plot:
    def __init__(self, top, columns):
        self.top = _nice_max(top)
        self.columns = columns

    def x(self, i):
        return PAD_L + (W - PAD_L - PAD_R) * (i + 0.5) / self.columns

    def y(self, value):
        return PAD_T + (H - PAD_T - PAD_B) * (1 - float(value) / self.top)

    def grid(self, money):
        out = []
        for k in range(5):
            v = self.top * k / 4
            y = self.y(v)
            out.append(f'<line class="pc-grid" x1="{PAD_L}" x2="{W - PAD_R}" y1="{y:.1f}" y2="{y:.1f}"/>'
                       f'<text class="pc-axis" x="{PAD_L - 8}" y="{y + 4:.1f}" text-anchor="end">{escape(_axis_label(v, money))}</text>')
        return "".join(out)

    def labels(self, names):
        return "".join(f'<text class="pc-axis" x="{self.x(i):.1f}" y="{H - 12}" text-anchor="middle">{escape(n)}</text>'
                       for i, n in enumerate(names))


ACTUAL_COLOUR = "var(--accent)"
PROJECTED_COLOUR = "var(--muted)"


def _tip_value(value, money):
    """A figure for the hover box, in full (the axis is short; the box gives the exact figure)."""
    if value is None:
        return ""
    if money:
        return "\u20b9" + format_money(Decimal(str(value)), unit="full")
    return f"{float(value):,.0f}"


def _svg(body, label, hover=None, plot=None):
    """The chart, wrapped with the hover box when ``hover`` is ``{"d": [labels], "s": [{"l", "c", "v"}]}``."""
    if hover is None:
        return mark_safe(f'<svg class="projection-chart" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(label)}" '
                         f'preserveAspectRatio="xMidYMid meet">{body}</svg>')
    data = dict(hover, x=[round(plot.x(i), 1) for i in range(len(hover["d"]))])
    return mark_safe(
        '<div class="chart-plot">'
        f'<svg class="projection-chart ch hv" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(label)}" tabindex="0" '
        f'data-top="{PAD_T}" data-bottom="{H - PAD_B}" data-hover="{escape(json.dumps(data))}" '
        f'preserveAspectRatio="xMidYMid meet">{body}</svg>'
        '<div class="hv-tip" role="status" hidden></div></div>'
    )


def running_total_svg(month_names, plan, current_index, title, money=True, unit="full"):
    """``plan`` is ``projection.project_months`` output; ``current_index`` the position of the current month (0 to 11)."""
    months = plan["months"]
    actual_points, running = [], Decimal("0")
    for i in range(current_index + 1):
        running += months[i]["actual"]
        actual_points.append((i, running))
    projected_points = [(current_index, running)]
    for i in range(current_index, 12):
        running += months[i]["extra"] + (months[i]["actual"] if i > current_index else 0)
        if i > current_index:
            projected_points.append((i, running))
    if len(projected_points) == 1:  # March: the rest of the month only
        projected_points.append((current_index, running))
    pace, total = [], Decimal("0")
    for i, entered in enumerate(plan["entered"]):
        total += plan["rate"] * Decimal(entered)
        pace.append((i, total))
    plot = _Plot(max(Decimal(plan["projected"]), running, total), 12)

    def path(points):
        return " ".join(f"{'M' if k == 0 else 'L'}{plot.x(i):.1f},{plot.y(v):.1f}" for k, (i, v) in enumerate(points))

    body = [plot.grid(money)]
    body.append(f'<path class="pc-pace" d="{path(pace)}"/>')
    body.append(f'<path class="pc-projected-line" d="{path(projected_points)}"/>')
    body.append(f'<path class="pc-actual-line" d="{path(actual_points)}"/>')
    body += [f'<circle class="pc-actual-dot" cx="{plot.x(i):.1f}" cy="{plot.y(v):.1f}" r="3.5"/>' for i, v in actual_points]
    body += [f'<circle class="pc-projected-dot" cx="{plot.x(i):.1f}" cy="{plot.y(v):.1f}" r="3.5"/>' for i, v in projected_points[1:]]
    end_i, _end_v = projected_points[-1]
    body.append(f'<text class="pc-note pc-projected-text" x="{plot.x(end_i) - 6:.1f}" y="{plot.y(plan["projected"]) - 10:.1f}" '
                f'text-anchor="end">Projected {escape(_label(plan["projected"], money, unit))}</text>')
    now_i, now_v = actual_points[-1]
    # Below and to the right of today's point: the dashed line rises away from it, so the text stays clear of both lines.
    anchor = "end" if now_i >= 10 else "start"
    body.append(f'<text class="pc-note pc-actual-text" x="{plot.x(now_i) + (-8 if anchor == "end" else 8):.1f}" '
                f'y="{plot.y(now_v) + 20:.1f}" text-anchor="{anchor}">So far {escape(_label(plan["so_far"], money, unit))}</text>')
    body.append(plot.labels(month_names))
    label = (f"{title}, running total: {_label(plan['so_far'], money, unit)} so far, "
             f"projected {_label(plan['projected'], money, unit)} for the year")
    # The hover box: the month on its own and the running total, each actual and projected.
    in_month, projected_month, to_date, projected_to_date = [], [], [], []
    run_actual = run_projected = Decimal("0")
    for i, m in enumerate(months):
        run_actual += m["actual"]
        run_projected += m["actual"] + m["extra"]
        happened = i <= current_index
        in_month.append(_tip_value(m["actual"], money) if happened else "Not yet")
        projected_month.append(_tip_value(m["actual"] + m["extra"], money))
        to_date.append(_tip_value(run_actual, money) if happened else "Not yet")
        projected_to_date.append(_tip_value(run_projected, money))
    hover = {"d": list(month_names), "s": [
        {"l": "Actual, the month", "c": ACTUAL_COLOUR, "v": in_month},
        {"l": "Projected, the month", "c": PROJECTED_COLOUR, "v": projected_month},
        {"l": "Actual, running total", "c": ACTUAL_COLOUR, "v": to_date},
        {"l": "Projected, running total", "c": PROJECTED_COLOUR, "v": projected_to_date},
    ]}
    return _svg("".join(body), label, hover, plot)


def year_columns_svg(years, title, money=True, unit="full"):
    """``years`` is ``[(label, actual, projected or None)]`` oldest first; a year with a projection is drawn stacked."""
    top = max((max(Decimal(str(a)), Decimal(str(p or 0))) for _l, a, p in years), default=Decimal("0"))
    plot = _Plot(top, max(len(years), 1))
    width = (W - PAD_L - PAD_R) / max(len(years), 1) * 0.5
    body = ['<defs><pattern id="pc-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
            '<line class="pc-hatch-line" x1="0" y1="0" x2="0" y2="6"/></pattern></defs>', plot.grid(money)]
    for i, (name, actual, projected) in enumerate(years):
        x = plot.x(i) - width / 2
        y_actual, base = plot.y(actual), plot.y(0)
        cls = "pc-actual-bar" if projected is not None else "pc-past-bar"
        body.append(f'<rect class="{cls}" x="{x:.1f}" y="{y_actual:.1f}" width="{width:.1f}" height="{max(base - y_actual, 0):.1f}"/>')
        if projected is not None and Decimal(str(projected)) > Decimal(str(actual)):
            y_proj = plot.y(projected)
            body.append(f'<rect class="pc-projected-bar" x="{x:.1f}" y="{y_proj:.1f}" width="{width:.1f}" height="{y_actual - y_proj:.1f}"/>')
            body.append(f'<text class="pc-note pc-projected-text" x="{plot.x(i):.1f}" y="{y_proj - 8:.1f}" text-anchor="middle">'
                        f'Projected {escape(_label(projected, money, unit))}</text>')
            inside = base - y_actual > 28  # inside the solid part when it is tall enough, else above the projected figure
            body.append(f'<text class="pc-note {"pc-inside-text" if inside else "pc-actual-text"}" x="{plot.x(i):.1f}" '
                        f'y="{(y_actual + 18) if inside else (y_proj - 24):.1f}" text-anchor="middle">So far {escape(_label(actual, money, unit))}</text>')
        else:
            body.append(f'<text class="pc-value" x="{plot.x(i):.1f}" y="{y_actual - 8:.1f}" text-anchor="middle">'
                        f'{escape(_label(actual, money, unit))}</text>')
    body.append(plot.labels([name for name, _a, _p in years]))
    hover = {"d": [name for name, _a, _p in years], "s": [
        {"l": "Actual", "c": ACTUAL_COLOUR, "v": [_tip_value(a, money) for _n, a, _p in years]},
        {"l": "Projected", "c": PROJECTED_COLOUR,
         "v": [_tip_value(p, money) if p is not None else "Year over" for _n, _a, p in years]},
    ]}
    return _svg("".join(body), f"{title} by financial year", hover, plot)
