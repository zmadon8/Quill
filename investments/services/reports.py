"""The other reports (plan 9, "Reports and statistics"). Each returns a ``Table``: a title, a short explanation, column headings with a kind
for formatting ("text", "money", "pct", "units", "date", "int"), rows, an optional total row and notes. One template draws every table and one
Excel writer exports it, so every table can be sorted and exported."""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from fees.services.financial_year import derive_financial_year

from investments import indexcmp, lots, xirr
from investments.models import Broker, Dividend, Instrument, Portfolio, ProfileInvestment, Transaction
from investments.services import annual, core, fetch, holdings, masters, performance, prices

ZERO = Decimal(0)


@dataclass
class Table:
    title: str
    intro: str
    columns: list                      # [(heading, kind)]
    rows: list = field(default_factory=list)
    total: list = None
    notes: list = field(default_factory=list)


def yearly(profile, portfolio=None, broker=None, **_):
    t = Table("Year-by-year returns", "Each financial year's XIRR next to the Default Index's change over the same year.",
              [("Financial year", "text"), ("Start value", "money"), ("Invested", "money"), ("Sold", "money"), ("End value", "money"), ("XIRR", "pct"),
               ("Index return", "pct"), ("Difference", "pct")])
    for label in reversed(annual.year_choices(profile)):
        r = annual.build(profile, label, portfolio=portfolio, broker=broker, with_portfolios=False)
        diff = None if r.xirr is None or r.index_return is None else r.xirr - r.index_return
        t.rows.append([label + ("" if r.completed else " (to date)"), r.opening_value, r.invested, r.sold, r.closing_value, r.xirr, r.index_return, diff])
    t.notes.append("The index return is the change in the index over the year; XIRR is the yearly return on the money you put in.")
    return t


def best_worst(profile, portfolio=None, broker=None, years=1, held_only=False, **_):
    start, end = performance.period_dates(preset=years)
    rows, _total, notes, _s = performance.table(profile, start=start, end=end, portfolio=portfolio, broker=broker, held_only=held_only)
    opening = {h.instrument.pk: h for h in holdings.compute(profile, portfolio=portfolio, broker=broker, as_of=start)[0]}
    scored = []
    for r in rows:
        before = opening.get(r.instrument.pk)
        put_in = -sum((a for d, a in r.flows if d > start), ZERO)
        gain = r.value - (before.value if before and before.units else ZERO) - put_in
        scored.append((r, gain))
    scored.sort(key=lambda x: (x[0].xirr is None, -(x[0].xirr or 0)))
    t = Table(f"Best and worst performers, last {years} year{'s' if years != 1 else ''}", "The top and bottom five by XIRR over the period, and the rupees of gain each added.",
              [("", "text"), ("Investment", "text"), ("XIRR", "pct"), ("Index XIRR", "pct"), ("Alpha", "pct"), ("Gain in the period", "money")])
    best = scored[:5]
    worst = [x for x in scored[::-1] if x[0].xirr is not None][:5]
    for tag, part in (("Best", best), ("Worst", worst)):
        for r, gain in part:
            t.rows.append([tag, r.instrument.name, r.xirr, r.index_xirr, r.alpha, gain])
    t.notes += notes
    return t


def scoreboard(profile, portfolio=None, broker=None, years=1, held_only=False, **_):
    start, end = performance.period_dates(preset=years)
    rows, total, _n, sectoral = performance.table(profile, start=start, end=end, portfolio=portfolio, broker=broker, held_only=held_only)
    rated = [r for r in rows if r.alpha is not None]
    beat = [r for r in rated if r.alpha > 0]
    t = Table("Index scoreboard", f"How many holdings beat the Default Index over the last {years} year{'s' if years != 1 else ''}, and by how much.",
              [("Investment", "text"), ("XIRR", "pct"), ("Index XIRR", "pct"), ("Alpha", "pct")] + ([("Sectoral alpha", "pct")] if sectoral else []))
    for r in sorted(rated, key=lambda r: -r.alpha):
        t.rows.append([r.instrument.name, r.xirr, r.index_xirr, r.alpha] + ([r.sect_alpha] if sectoral else []))
    t.notes.append(f"{len(beat)} of {len(rated)} beat the index" + (f"; {sum(1 for r in rated if r.sect_alpha and r.sect_alpha > 0)} beat their sectoral index" if sectoral else "") + ".")
    return t


def dividend_report(profile, portfolio=None, broker=None, held_only=False, **_):
    qs = Dividend.objects.filter(profile=profile).select_related("instrument")
    if portfolio:
        qs = qs.filter(portfolio_id=portfolio)
    if broker:
        qs = qs.filter(broker_id=broker)
    rows_now, _t = holdings.compute(profile, portfolio=portfolio, broker=broker)
    cost = {h.instrument.pk: h.cost_of_units for h in rows_now}
    shown = {h.instrument.pk for h in rows_now if h.is_held}
    by = {}
    for dv in qs:
        if held_only and dv.instrument_id not in shown:
            continue
        key = (derive_financial_year(dv.date), dv.instrument)
        by[key] = by.get(key, ZERO) + dv.amount
    t = Table("Dividend report", "Dividends by financial year and holding, with the yield on the cost of the units held now.",
              [("Financial year", "text"), ("Investment", "text"), ("Received", "money"), ("Yield on cost", "pct")])
    for (fy, inst), amount in sorted(by.items(), key=lambda kv: (kv[0][0], kv[0][1].name), reverse=True):
        c = cost.get(inst.pk)
        t.rows.append([fy, inst.name, amount, float(amount / c) if c else None])
    t.total = ["Total", "", sum(by.values(), ZERO), None]
    if held_only:
        t.notes.append("Held only: dividends from investments you no longer hold are left out, and so from the total. Untick Held only to include them.")
    return t


def income(profile, portfolio=None, broker=None, **_):
    t = Table("Total income summary", "Dividends plus realised gains for each financial year.",
              [("Financial year", "text"), ("Dividends", "money"), ("Short-term gains", "money"), ("Long-term gains", "money"), ("Total", "money")])
    for label in annual.year_choices(profile):
        r = annual.build(profile, label, portfolio=portfolio, broker=broker, with_portfolios=False)
        t.rows.append([label, r.dividends, r.short_gain, r.long_gain, r.dividends + r.total_gain])
    t.notes.append("A record-keeping aid, not tax advice.")
    return t


def _lots_now(profile, portfolio, broker):
    rows, _t = holdings.compute(profile, portfolio=portfolio, broker=broker, with_xirr=False)
    return [(h, lot) for h in rows for lot in h.lots]


def turning_long(profile, portfolio=None, broker=None, days=60, **_):
    s = core.get_settings(profile, create=False)
    today = date.today()
    t = Table(f"Lots turning long-term in the next {days} days", "Purchases that cross the long-term cutoff soon.",
              [("Investment", "text"), ("Held from", "date"), ("Units", "units"), ("Cost", "money"), ("Turns long-term", "date"), ("Days left", "int")])
    for h, lot in _lots_now(profile, portfolio, broker):
        turns = lot.bought_on + timedelta(days=s.long_term_days + 1)
        left = (turns - today).days
        if 0 < left <= days:
            t.rows.append([h.instrument.name, lot.bought_on, lot.units, lot.cost, turns, left])
    t.rows.sort(key=lambda r: r[5])
    return t


def unrealised_lots(profile, portfolio=None, broker=None, **_):
    s = core.get_settings(profile, create=False)
    today = date.today()
    t = Table("Unrealised gains and losses by lot", "If everything were sold today, first in first out: short or long term, gains and losses that could be booked.",
              [("Investment", "text"), ("Held from", "date"), ("Units", "units"), ("Cost", "money"), ("Value", "money"), ("Gain", "money"), ("Term", "text")])
    short = long_ = ZERO
    for h, lot in _lots_now(profile, portfolio, broker):
        if not h.price:
            continue
        value = lot.units * h.price
        gain = value - lot.cost
        term = "Long-term" if (today - lot.bought_on).days > s.long_term_days else "Short-term"
        if term == "Long-term":
            long_ += gain
        else:
            short += gain
        t.rows.append([h.instrument.name, lot.bought_on, lot.units, lot.cost, value, gain, term])
    t.notes.append(f"Short-term {short:,.2f}, long-term {long_:,.2f}. Check with your CA before acting on it.")
    return t


def concentration(profile, portfolio=None, broker=None, **_):
    s = core.get_settings(profile, create=False)
    rows, totals = holdings.compute(profile, portfolio=portfolio, broker=broker)
    held = sorted(holdings.held(rows), key=lambda h: -h.value)
    t = Table("Concentration", f"The share of the ten largest holdings; a holding above {s.concentration_limit}% (Settings > Insights) is flagged.",
              [("Investment", "text"), ("Value", "money"), ("Share", "pct"), ("", "text")])
    for h in held[:10]:
        share = float(h.value / totals.value) if totals.value else None
        t.rows.append([h.instrument.name, h.value, share, "Above the limit" if share and share * 100 > float(s.concentration_limit) else ""])
    top = sum((h.value for h in held[:10]), ZERO)
    t.total = ["Top ten", top, float(top / totals.value) if totals.value else None, ""]
    return t


def cost_of_funds(profile, portfolio=None, broker=None, **_):
    rows, _t = holdings.compute(profile, portfolio=portfolio, broker=broker)
    funds = [h for h in holdings.held(rows) if h.instrument.kind == "fund"]
    t = Table("Cost of funds", "The expense ratio of each mutual fund (entered in the catalogue) and the average weighted by value.",
              [("Fund", "text"), ("Value", "money"), ("Expense ratio %", "num")])
    weighted, base = ZERO, ZERO
    for h in funds:
        er = h.instrument.expense_ratio
        t.rows.append([h.instrument.name, h.value, er])
        if er is not None:
            weighted += er * h.value
            base += h.value
    t.total = ["Weighted average", base, (weighted / base).quantize(Decimal("0.001")) if base else None]
    if any(h.instrument.expense_ratio is None for h in funds):
        t.notes.append("Some funds have no expense ratio yet; an Admin can enter it in Settings > Catalogue.")
    return t


def data_check(profile, held_only=False, **_):
    s = core.get_settings(profile, create=False)
    ids = ProfileInvestment.objects.filter(profile=profile).values_list("instrument_id", flat=True)
    if held_only:
        now_held = holdings.held_instrument_ids(profile)
        ids = [i for i in ids if i in now_held]
    insts = list(Instrument.objects.filter(pk__in=list(ids)))
    stale = fetch.stale_ids([i for i in insts if i.price_source not in ("manual", "upload")])
    last = prices.last_price_date([i.pk for i in insts])
    t = Table("Data check", "Old or missing prices, investments with no code, and (while the sectoral index is on) holdings with no sectoral index.",
              [("Investment", "text"), ("Problem", "text")])
    sect = dict(ProfileInvestment.objects.filter(profile=profile).values_list("instrument_id", "sectoral_index_id"))
    for i in sorted(insts, key=lambda i: i.name):
        if i.kind != "alternative" and i.pk not in last:
            t.rows.append([i.name, "No price stored"])
        elif i.pk in stale:
            t.rows.append([i.name, f"Price is old (last {last[i.pk]:%-d %b %Y})"])
        if i.kind in ("share", "fund", "foreign") and not i.code:
            t.rows.append([i.name, "No code, so prices cannot be fetched"])
        if s.sectoral_enabled and i.kind != "alternative" and not sect.get(i.pk):
            t.rows.append([i.name, "No sectoral index"])
    if not t.rows:
        t.notes.append("Nothing to fix.")
    return t


def _group_table(profile, title, intro, groups, years):
    start, end = performance.period_dates(preset=years)
    s = core.get_settings(profile, create=False)
    index = s.default_index if s.default_index_id else masters.default_index_for(profile)
    series = performance.IndexSeries(index, start, end) if index else None
    t = Table(title, intro, [("", "text"), ("Invested", "money"), ("Current value", "money"), ("Gain", "money"), ("XIRR", "pct"), ("Index XIRR", "pct"), ("Alpha", "pct")])
    for name, kw in groups:
        rows, tot, _n, _s = performance.table(profile, start=start, end=end, **kw)
        now = holdings.compute(profile, **kw)[1]
        ix = indexcmp.index_xirr(tot.flows, series.level, end) if series and tot.flows else None
        t.rows.append([name, now.invested, now.value, now.gain, tot.xirr, ix, indexcmp.alpha(tot.xirr, ix)])
    return t


def compare_portfolios(profile, years=3, **_):
    groups = [(p.name, {"portfolio": p.pk}) for p in Portfolio.objects.filter(profile=profile)]
    return _group_table(profile, "Compare portfolios", f"Each portfolio of this profile over the last {years} years.", groups, years)


def compare_brokers(profile, years=3, **_):
    groups = [(b.name, {"broker": b.pk}) for b in Broker.objects.filter(profile=profile)] + [("All holdings", {})]
    t = _group_table(profile, "Compare brokers", f"Everything held with each broker over the last {years} years, against the Default Index over the same cash flows.",
                     groups, years)
    t.notes.append("A transfer between brokers counts as money leaving one and arriving at the other at the market value on the transfer date. "
                   "Differences mainly reflect which investments each broker holds and when they were bought, not the quality of the broker.")
    return t


REPORTS = {
    "yearly": (yearly, "Year-by-year returns"), "best-worst": (best_worst, "Best and worst performers"), "scoreboard": (scoreboard, "Index scoreboard"),
    "dividends": (dividend_report, "Dividend report"), "income": (income, "Total income summary"),
    "turning-long": (turning_long, "Lots turning long-term soon"), "unrealised": (unrealised_lots, "Unrealised gains and losses by lot"),
    "concentration": (concentration, "Concentration"), "cost-of-funds": (cost_of_funds, "Cost of funds"), "data-check": (data_check, "Data check"),
    "compare-portfolios": (compare_portfolios, "Compare portfolios"), "compare-brokers": (compare_brokers, "Compare brokers"),
}

__all__ = ["REPORTS", "Table", "lots", "xirr", "Transaction"]
