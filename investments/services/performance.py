"""Performance against the Default Index (plan 5 and 9): XIRR or CAGR for a period, the index-equivalent XIRR and Alpha, and the same
against an investment's sectoral index while that switch is on.

Levels come from `IndexSeries`: a pin for that exact date first, then the stored close on or before the date (plan 17.2). A date with
nothing usable gives "n/a" rather than a guess. A level taken from a pin or from a close more than a week old is counted as approximate and
the report says so.
"""
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from investments import indexcmp, xirr
from investments.models import PinnedPrice, ProfileInvestment
from investments.services import core, holdings, masters, prices

ZERO = Decimal(0)
APPROX_AFTER_DAYS = 7


class IndexSeries:
    """Closes of one index over a window, for many look-ups by date (one query for the series, one for the pins)."""

    def __init__(self, instrument, start, end):
        self.instrument = instrument
        self.points = prices.series(instrument, start, end) if instrument else []
        before = prices.latest_prices([instrument.pk], start - timedelta(days=1)).get(instrument.pk) if instrument else None
        if before:
            self.points = [before] + self.points
        self.days = [d for d, _ in self.points]
        self.pins = {}
        if instrument:
            for asked, close, approx in PinnedPrice.objects.filter(instrument=instrument, asked_date__range=(start, end)).values_list("asked_date", "close", "approximate"):
                self.pins[asked] = (close, approx)
        self.approximate = False

    def level(self, day):
        if day in self.pins:
            close, approx = self.pins[day]
            self.approximate |= approx
            return close
        i = bisect_right(self.days, day)
        if not i:
            return None
        if (day - self.days[i - 1]).days > APPROX_AFTER_DAYS:
            self.approximate = True
        return self.points[i - 1][1]


@dataclass
class Row:
    instrument: object
    xirr: float = None
    cagr: float = None
    index_xirr: float = None
    alpha: float = None
    sect_xirr: float = None
    sect_alpha: float = None
    sect_name: str = ""
    note: str = ""
    starts: date = None
    value: Decimal = ZERO
    flows: list = field(default_factory=list)


def _default_index(profile, settings_row):
    return settings_row.default_index if settings_row.default_index_id else masters.default_index_for(profile)


def decorate_with_index(profile, rows, totals, as_of, settings_row=None):
    """Fill in ``index_xirr`` and ``alpha`` (and the sectoral pair, while that switch is on) on holdings and totals. Returns a list of notes."""
    settings_row = settings_row or core.get_settings(profile, create=False)
    notes = []
    default = _default_index(profile, settings_row)
    if default is None:
        return notes
    dates = [d for h in rows for d, _ in h.flows] + [as_of]
    start = min(dates)
    default_series = IndexSeries(default, start, as_of)
    sect_series = {}
    sect_map = {}
    if settings_row.sectoral_enabled:
        for pi in ProfileInvestment.objects.filter(profile=profile).exclude(sectoral_index=None).select_related("sectoral_index"):
            sect_map[pi.instrument_id] = pi.sectoral_index
    for h in rows:
        if not h.flows:
            continue
        h.index_xirr = indexcmp.index_xirr(h.flows, default_series.level, as_of)
        h.alpha = indexcmp.alpha(h.xirr, h.index_xirr)
        sect = sect_map.get(h.instrument.pk)
        if sect is not None:
            series = sect_series.setdefault(sect.pk, IndexSeries(sect, start, as_of))
            h.sect_xirr = indexcmp.index_xirr(h.flows, series.level, as_of)
            h.sect_alpha = indexcmp.alpha(h.xirr, h.sect_xirr)
    if totals.flows:
        totals.index_xirr = indexcmp.index_xirr(totals.flows, default_series.level, as_of)
        totals.alpha = indexcmp.alpha(totals.xirr, totals.index_xirr)
    if default_series.approximate or any(s.approximate for s in sect_series.values()):
        notes.append("Some index values are approximate (a nearby or month-end day was used).")
    return notes


# ---------------------------------------------------------------- the Performance tab

PRESET_YEARS = (1, 3, 5)


def period_dates(preset=None, start=None, end=None, today=None):
    """``(start, end)`` for a preset number of years back from today, or custom dates."""
    today = today or date.today()
    end = min(end or today, today)
    if preset:
        years = int(preset)
        try:
            start = end.replace(year=end.year - years)
        except ValueError:
            start = end.replace(year=end.year - years, day=28)
    if start is None or start >= end:
        raise ValueError("The start date must be before the end date.")
    return start, end


def cagr_of(instrument, start, end):
    """The investment's own price growth from its first stored price on or after ``start`` to its last on or before ``end``, with the date it
    started from (None, None when there is no price history; alternative investments have none)."""
    if instrument.kind == "alternative":
        return None, None
    rows = prices.series(instrument, start, end)
    if len(rows) < 2:
        return None, None
    (d0, p0), (d1, p1) = rows[0], rows[-1]
    days = (d1 - d0).days
    if days < xirr.MIN_DAYS or p0 <= 0:
        return None, d0
    return float(p1 / p0) ** (365.0 / days) - 1.0, d0


def table(profile, *, start, end, measure="xirr", portfolio=None, broker=None, settings_row=None):
    """One row per investment for the period (plan 9). The value on the start date counts as the opening investment; an investment bought
    after the start only uses data from its first purchase, and says so. Returns ``(rows, total_row, notes, sectoral_on)``."""
    settings_row = settings_row or core.get_settings(profile, create=False)
    now_rows, now_totals = holdings.compute(profile, portfolio=portfolio, broker=broker, as_of=end, settings=settings_row)
    opening = {h.instrument.pk: h for h in holdings.compute(profile, portfolio=portfolio, broker=broker, as_of=start, settings=settings_row)[0]}
    default = _default_index(profile, settings_row)
    series_start = start - timedelta(days=1)
    default_series = IndexSeries(default, series_start, end) if default else None
    sect_map = {}
    if settings_row.sectoral_enabled:
        for pi in ProfileInvestment.objects.filter(profile=profile).exclude(sectoral_index=None).select_related("sectoral_index"):
            sect_map[pi.instrument_id] = pi.sectoral_index
    sect_series = {}
    out, all_flows, notes = [], [], []
    closing_total = ZERO
    for h in now_rows:
        before = opening.get(h.instrument.pk)
        flows = []
        row = Row(instrument=h.instrument, value=h.value)
        if before is not None and before.units > 0:
            flows.append((start, -before.value))
        elif h.flows and min(d for d, _ in h.flows) > start:
            row.starts = min(d for d, _ in h.flows)
            row.note = f"Held from {row.starts:%-d %b %Y}"
        flows += [(d, a) for d, a in h.flows if start < d <= end]
        row.flows = flows
        if not flows and h.sold_out:
            continue
        if measure == "cagr":
            row.cagr, first = cagr_of(h.instrument, start, end)
            if first and first > start and not row.note:
                row.note = f"Prices from {first:%-d %b %Y}"
        else:
            closing = [(end, h.value)] if h.units or h.awaiting else []
            row.xirr = xirr.xirr([(d, float(a)) for d, a in flows + closing])
        if default_series and flows:
            row.index_xirr = indexcmp.index_xirr(flows, default_series.level, end)
            row.alpha = indexcmp.alpha(row.xirr, row.index_xirr) if measure == "xirr" else None
            sect = sect_map.get(h.instrument.pk)
            if sect is not None:
                series = sect_series.setdefault(sect.pk, IndexSeries(sect, series_start, end))
                row.sect_name = sect.name
                row.sect_xirr = indexcmp.index_xirr(flows, series.level, end)
                row.sect_alpha = indexcmp.alpha(row.xirr, row.sect_xirr) if measure == "xirr" else None
        out.append(row)
        all_flows += flows
        closing_total += h.value if h.units or h.awaiting else ZERO
    total = Row(instrument=None, value=closing_total, flows=all_flows)
    if measure == "xirr" and all_flows:
        total.xirr = xirr.xirr([(d, float(a)) for d, a in all_flows] + [(end, float(closing_total))])
        if default_series:
            total.index_xirr = indexcmp.index_xirr(all_flows, default_series.level, end)
            total.alpha = indexcmp.alpha(total.xirr, total.index_xirr)
    if default_series and default_series.approximate:
        notes.append("Some index values are approximate (a nearby or month-end day was used).")
    if any(r.starts for r in out):
        notes.append("Investments bought after the start use only the data from their first purchase; the index is compared over the same dates.")
    if measure == "cagr":
        notes.append("CAGR is the investment's own price growth for as long as prices are stored in the program; it ignores when you bought.")
    return out, total, notes, bool(settings_row.sectoral_enabled)
