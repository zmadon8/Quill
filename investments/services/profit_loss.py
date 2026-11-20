"""The Profit / Loss report (owner round 2026-11): every sale, financial year by financial year (1 April to 31 March), newest first.

Each sale is one sale transaction, its units matched to purchases first-in-first-out (the same replay as the Annual Report, so the
figures agree with it). For each sale:

* Profit / Loss = proceeds (after the sale's charges) less the cost of the purchases it used (with their charges and any cost override).
* Profit / Loss % = Profit / Loss / cost (none when the cost is 0, as for bonus shares).
* XIRR = the yearly rate of the purchases' payments and the sale's proceeds (none for a holding of under 30 days, as elsewhere).
* Long-term and short-term capital gains: each matched purchase is long-term when it was held more than the cutoff of the sale's year
  (Annual Report > "Long-term after", else Settings), so a sale that used old and new purchases splits into both.
* Other income: the whole Profit / Loss of a sale of an investment whose Capital Gains is off (it is not a capital gain).

Only completed sales count (a tentative sale is not in the replay). A record-keeping aid, not tax advice.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from fees.services.financial_year import derive_financial_year

from investments import lots, xirr
from investments.models import Instrument, Transaction
from investments.services import core

from .annual import cutoff_for

ZERO = Decimal(0)
CENT = Decimal("0.01")


@dataclass
class Totals:
    cost: Decimal = ZERO
    proceeds: Decimal = ZERO
    profit: Decimal = ZERO
    long_gain: Decimal = ZERO
    short_gain: Decimal = ZERO
    other_income: Decimal = ZERO
    flows: list = field(default_factory=list)
    count: int = 0

    def add(self, sale):
        self.cost += sale["cost"]
        self.proceeds += sale["proceeds"]
        self.profit += sale["profit"]
        self.long_gain += sale["long_gain"]
        self.short_gain += sale["short_gain"]
        self.other_income += sale["other_income"]
        self.flows += sale["flows"]
        self.count += 1

    @property
    def pct(self):
        return _pct(self.profit, self.cost)

    @property
    def xirr(self):
        return xirr.xirr(self.flows) if self.flows else None


@dataclass
class Year:
    label: str
    cutoff: int
    sales: list = field(default_factory=list)
    totals: Totals = field(default_factory=Totals)


@dataclass
class Report:
    years: list = field(default_factory=list)
    totals: Totals = field(default_factory=Totals)


def _pct(profit, cost):
    return float(profit / cost) if cost else None


def build(profile, portfolio=None, broker=None, events=None):
    """The report: ``Report.years`` newest first, each with its sales (by date) and totals; ``Report.totals`` for every year."""
    settings_row = core.get_settings(profile, create=False)
    names = dict(Instrument.objects.filter(pk__in=Transaction.objects.filter(profile=profile).values("instrument_id")).values_list("pk", "name"))
    lump_ids = set(Instrument.objects.filter(pk__in=names, lump_sum=True).values_list("pk", flat=True))
    other_ids = set(Instrument.objects.filter(pk__in=names, capital_gains=False).values_list("pk", flat=True))
    all_events = events if events is not None else core.events_by_instrument(profile)
    cutoffs = {}
    by_year = {}
    for iid in names:
        result = lots.replay(all_events.pop(iid, []) if events is None else all_events.get(iid, []))
        sales = defaultdict(list)
        for m in result.matches:
            if m.bucket and ((portfolio and m.bucket.portfolio != portfolio) or (broker and m.bucket.broker != broker)):
                continue
            sales[m.sell_ref].append(m)
        for ref, matches in sales.items():
            sold = matches[0].sold_on
            label = derive_financial_year(sold)
            if label not in cutoffs:
                cutoffs[label] = cutoff_for(settings_row, label)
            sale = _sale(names[iid], iid, ref, sold, matches, cutoffs[label], iid in other_ids, iid in lump_ids)
            year = by_year.get(label)
            if year is None:
                year = by_year[label] = Year(label, cutoffs[label])
            year.sales.append(sale)
            year.totals.add(sale)
    report = Report()
    for label in sorted(by_year, reverse=True):
        year = by_year[label]
        year.sales.sort(key=lambda s: (s["sold"], s["name"]))
        report.years.append(year)
        for sale in year.sales:
            report.totals.add(sale)
    return report


def _sale(name, iid, ref, sold, matches, cutoff, other, lump):
    cost = sum((m.cost for m in matches), ZERO)
    proceeds = sum((m.proceeds for m in matches), ZERO)
    profit = proceeds - cost
    long_gain = short_gain = other_income = ZERO
    if other:
        other_income = profit
    else:
        for m in matches:
            if m.holding_days > cutoff:
                long_gain += m.gain
            else:
                short_gain += m.gain
    flows = [(m.paid_on or m.bought_on, -float(m.cost)) for m in matches if m.cost] + [(sold, float(proceeds))]
    first = min(m.bought_on for m in matches)
    return {
        "name": name, "instrument_id": iid, "ref": ref, "sold": sold, "first_bought": first,
        "days": (sold - first).days, "units": sum((m.units for m in matches), ZERO), "lump_sum": lump,
        "cost": cost.quantize(CENT), "proceeds": proceeds.quantize(CENT), "profit": profit.quantize(CENT),
        "pct": _pct(profit, cost), "xirr": xirr.xirr(flows) if cost else None,
        "long_gain": long_gain.quantize(CENT), "short_gain": short_gain.quantize(CENT), "other_income": other_income.quantize(CENT),
        "other": other, "estimated": any(m.estimated for m in matches), "flows": flows,
    }
