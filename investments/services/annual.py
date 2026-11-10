"""The Annual Report (plan 13): one financial year, 1 April to 31 March; a completed year as at the end of 31 March, the current year as at
today. Values are Total Portfolio Value (never dividends). Capital gains are first-in-first-out, short or long term by the cutoff chosen for
the year (a default in Settings), with the per-lot cost override. Purchases awaiting allotment on the closing date are valued at cost and
marked Provisional. A record-keeping aid, not tax advice: the treatments are for the CA to confirm.
"""
import dataclasses
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from fees.services.financial_year import current_financial_year, derive_financial_year, recent_financial_years

from investments import lots, xirr
from investments.models import (
    KIND_INDEX, SIDE_BUY, SIDE_SELL, STATUS_AWAITING, STATUS_FINAL, Dividend, Instrument, Portfolio, Transaction,
)
from investments.services import core, holdings, masters, prices

ZERO = Decimal(0)


def bounds(label, today=None):
    """``(start, end, closing date, completed)`` for a label such as ``"2025-26"``."""
    today = today or date.today()
    start_year = int(label[:4])
    start, end = date(start_year, 4, 1), date(start_year + 1, 3, 31)
    completed = end < today
    return start, end, end if completed else today, completed


def year_choices(profile, today=None):
    first = Transaction.objects.filter(profile=profile).order_by("date").values_list("date", flat=True).first()
    earliest = derive_financial_year(first) if first else current_financial_year(today)
    return recent_financial_years(count=30, min_financial_year=earliest, now=today)


def cutoff_for(settings_row, label):
    try:
        return int((settings_row.year_cutoffs or {}).get(label) or settings_row.long_term_days)
    except (TypeError, ValueError):
        return settings_row.long_term_days


@dataclass
class Report:
    label: str
    start: date
    end: date
    closing: date
    completed: bool
    cutoff: int
    opening_value: Decimal = ZERO
    invested: Decimal = ZERO
    sold: Decimal = ZERO
    closing_value: Decimal = ZERO
    short_gain: Decimal = ZERO
    long_gain: Decimal = ZERO
    xirr: float = None
    index_return: float = None
    index_name: str = ""
    dividends: Decimal = ZERO
    dividend_tax: Decimal = ZERO
    unrealised: Decimal = ZERO
    sales: list = field(default_factory=list)
    holdings: list = field(default_factory=list)
    allocation: list = field(default_factory=list)
    transactions: list = field(default_factory=list)
    awaiting: list = field(default_factory=list)
    by_portfolio: list = field(default_factory=list)
    provisional: bool = False
    approximate: bool = False

    @property
    def reinvested(self):
        return self.invested - self.sold

    @property
    def total_gain(self):
        return self.short_gain + self.long_gain


def build(profile, label, *, portfolio=None, broker=None, include_dividends=None, today=None, with_portfolios=True, events=None):
    today = today or date.today()
    settings_row = core.get_settings(profile, create=False)
    start, end, closing, completed = bounds(label, today)
    report = Report(label, start, end, closing, completed, cutoff_for(settings_row, label))
    if include_dividends is None:
        include_dividends = settings_row.include_dividends
    opening_day = start - timedelta(days=1)
    t0 = holdings.compute(profile, portfolio=portfolio, broker=broker, as_of=opening_day, settings=settings_row, include_dividends=include_dividends)[1]
    rows1, t1 = holdings.compute(profile, portfolio=portfolio, broker=broker, as_of=closing, settings=settings_row, include_dividends=include_dividends)
    report.opening_value, report.closing_value = t0.value, t1.value
    report.holdings = holdings.held(rows1)
    report.allocation = holdings.allocation(report.holdings)
    report.unrealised = sum((h.value - h.cost for h in report.holdings if not h.unpriced and not h.blocked and not h.awaiting), ZERO)
    report.provisional = bool(t1.provisional or t1.awaiting)

    flows = []
    txns = Transaction.objects.filter(profile=profile, date__range=(start, closing)).select_related("instrument", "broker", "portfolio")
    if portfolio:
        txns = txns.filter(portfolio_id=portfolio)
    if broker:
        txns = txns.filter(broker_id=broker)
    for t in txns.order_by("date", "id"):
        if t.status == STATUS_AWAITING:
            if t.side == SIDE_BUY and settings_row.awaiting_treatment != "leave_out":
                report.invested += t.amount or ZERO
                flows.append((t.date, -(t.amount or ZERO)))
            report.transactions.append(t)
            continue
        if t.status != STATUS_FINAL or t.units is None:
            continue
        if t.side == SIDE_BUY:
            amount = core.buy_total(t)
            report.invested += amount
            flows.append((t.date, -amount))
        else:
            amount = core.sell_total(t)
            report.sold += amount
            flows.append((t.date, amount))
        report.transactions.append(t)
    report.awaiting = [t for t in Transaction.objects.filter(profile=profile, status=STATUS_AWAITING, date__lte=closing).select_related("instrument")
                       if (not portfolio or t.portfolio_id == portfolio) and (not broker or t.broker_id == broker)]

    divs = Dividend.objects.filter(profile=profile, date__range=(start, closing))
    if portfolio:
        divs = divs.filter(portfolio_id=portfolio)
    if broker:
        divs = divs.filter(broker_id=broker)
    for day, amount, tax in divs.values_list("date", "amount", "tax_deducted"):
        report.dividends += amount
        report.dividend_tax += tax
        if include_dividends:
            flows.append((day, amount))

    # capital gains: replay every investment's whole history once, keep the sales in this year that pass the filters
    names = dict(Instrument.objects.filter(pk__in=Transaction.objects.filter(profile=profile).values("instrument_id")).values_list("pk", "name"))
    pfs = list(Portfolio.objects.filter(profile=profile)) if with_portfolios and portfolio is None else []
    # The events are released investment by investment unless the per-portfolio breakdown below still needs them (memory, plan 26).
    release = events is None and len(pfs) <= 1
    all_events = events if events is not None else core.events_by_instrument(profile)
    # How each non-purchase row (bonus, split, demerger, no-cost) came to be held, to tag the sales that use its units.
    row_origins = dict(Transaction.objects.filter(profile=profile).exclude(origin="purchase").values_list("pk", "origin"))
    for iid in names:
        result = lots.replay(all_events.pop(iid, []) if release else all_events.get(iid, []), as_of=closing)
        for m in result.matches:
            if not (start <= m.sold_on <= closing):
                continue
            if m.bucket and ((portfolio and m.bucket.portfolio != portfolio) or (broker and m.bucket.broker != broker)):
                continue
            term = "long" if m.holding_days > report.cutoff else "short"
            if term == "long":
                report.long_gain += m.gain
            else:
                report.short_gain += m.gain
            origin = row_origins.get(m.buy_ref[1]) if isinstance(m.buy_ref, tuple) and m.buy_ref[0] == "txn" else None
            report.sales.append({"name": names[iid], "bought": m.bought_on, "paid": m.paid_on, "sold": m.sold_on, "days": m.holding_days, "units": m.units,
                                 "cost": m.cost, "proceeds": m.proceeds, "gain": m.gain, "term": term, "estimated": m.estimated,
                                 "bonus": (isinstance(m.buy_ref, tuple) and m.buy_ref[0] == "ca") or origin == "bonus",
                                 # The cost the gain uses, and (when a demerger moved cost between the parent and the new shares) the cost
                                 # the original transactions give. The original transactions themselves are never changed.
                                 "origin": origin or "", "adjusted": bool(m.adjustment), "original_cost": m.original_cost})
    report.sales.sort(key=lambda s: (s["sold"], s["name"]))

    cash = [(opening_day, -report.opening_value)] if report.opening_value else []
    cash += flows
    if cash:
        report.xirr = xirr.xirr([(d, float(a)) for d, a in cash] + [(closing, float(report.closing_value))])

    index = settings_row.default_index if settings_row.default_index_id else masters.default_index_for(profile)
    if index:
        report.index_name = index.name
        a = prices.price_on(index, opening_day)
        b = prices.price_on(index, closing)
        if a and b and a[1]:
            report.index_return = float(b[1] / a[1]) - 1.0
            report.approximate = bool(a[3] or b[3])

    if pfs:
        if len(pfs) == 1:
            # One portfolio: its figures are the report's own, so reuse them rather than computing the year twice.
            report.by_portfolio.append((pfs[0].name, dataclasses.replace(report, by_portfolio=[])))
        else:
            for p in pfs:
                sub = build(profile, label, portfolio=p.pk, broker=broker, include_dividends=include_dividends, today=today, with_portfolios=False,
                            events=all_events)
                # only the summary figures are shown or exported per portfolio; drop the lists so they are not held for the whole page
                sub.holdings, sub.allocation, sub.transactions, sub.awaiting, sub.sales = [], [], [], [], []
                report.by_portfolio.append((p.name, sub))
    return report


__all__ = ["bounds", "build", "year_choices", "cutoff_for", "KIND_INDEX", "SIDE_SELL"]
