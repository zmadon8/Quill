"""Reports: Performance, Charts and Total Portfolio Value (plan 9, 12)."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.db.models import Q

from .decorators import inv_editor as inv_read_write_view, inv_reader
from .models import HOLDABLE_KINDS, KIND_INDEX, Broker, Instrument, Portfolio, ProfileInvestment
from .services import core, holdings, masters, performance, series, statscache
from .svgchart import line_chart
from .viewutil import page, parse_date, profile_or_404, selection

PERIODS = [("1", "1 year"), ("3", "3 years"), ("5", "5 years"), ("custom", "Custom dates")]
CHART_PERIODS = [("1m", "1 month"), ("6m", "6 months"), ("1", "1 year"), ("3", "3 years"), ("5", "5 years"), ("all", "All"), ("custom", "Custom")]


def _pct(v):
    return None if v is None else round(v * 100, 2)


@inv_reader
def performance_view(request):
    profile = profile_or_404(request)
    portfolio, broker, _asat = selection(request, profile)
    measure = "cagr" if request.GET.get("measure") == "cagr" else "xirr"
    period = request.GET.get("period", "1")
    try:
        if period == "custom":
            start, end = performance.period_dates(start=parse_date(request.GET.get("from")), end=parse_date(request.GET.get("to")))
        else:
            start, end = performance.period_dates(preset=int(period) if period.isdigit() else 1)
    except ValueError as exc:
        messages.error(request, str(exc))
        start, end = performance.period_dates(preset=1)
        period = "1"
    rows, total, notes, sectoral = performance.table(profile, start=start, end=end, measure=measure, portfolio=portfolio, broker=broker)
    if request.GET.get("export") == "xlsx":
        from .exports import response

        header = ["Investment", "From", "XIRR %" if measure == "xirr" else "CAGR %", "Default Index XIRR %", "Alpha %"] + (
            ["Sectoral index", "Sectoral XIRR %", "Alpha vs sectoral %"] if sectoral else [])
        data = [[r.instrument.name, r.starts or start, _pct(r.xirr if measure == "xirr" else r.cagr), _pct(r.index_xirr), _pct(r.alpha)]
                + ([r.sect_name, _pct(r.sect_xirr), _pct(r.sect_alpha)] if sectoral else []) for r in rows]
        data.append(["All", start, _pct(total.xirr), _pct(total.index_xirr), _pct(total.alpha)])
        return response(f"Performance {start:%Y-%m-%d} to {end:%Y-%m-%d}.xlsx", [("Performance", header, data)])
    return page(request, "investments/performance.html", {
        "page_title_text": "Performance", "rows": rows, "total": total, "notes": notes, "sectoral": sectoral, "measure": measure, "period": period,
        "periods": PERIODS, "start": start, "end": end, "default_index": masters.default_index_for(profile)})


def _chart_window(period, request, first):
    today = date.today()
    if period == "1m":
        return today - timedelta(days=31), today
    if period == "6m":
        return today - timedelta(days=183), today
    if period == "all":
        return first or today - timedelta(days=365), today
    if period == "custom":
        start, end = parse_date(request.GET.get("from")), parse_date(request.GET.get("to")) or today
        if start and start < end:
            return start, min(end, today)
    years = int(period) if str(period).isdigit() else 1
    return performance.period_dates(preset=years)


@inv_reader
def charts_view(request):
    profile = profile_or_404(request)
    portfolio, broker, _asat = selection(request, profile)
    settings_row = core.get_settings(profile, create=False)
    period = request.GET.get("period", "1")
    first = holdings_first_date(profile)
    start, end = _chart_window(period, request, first)
    mode = "b" if request.GET.get("chart") == "b" else "a"
    held_ids = list(ProfileInvestment.objects.filter(profile=profile).values_list("instrument_id", flat=True))
    choices = Instrument.objects.filter(pk__in=held_ids, kind__in=HOLDABLE_KINDS).order_by("name")
    index_choices = Instrument.objects.filter(kind=KIND_INDEX).order_by("name")
    chosen_index_ids = [int(i) for i in request.GET.getlist("index") if i.isdigit()] or [getattr(masters.default_index_for(profile), "pk", None)]
    chosen_indices = list(index_choices.filter(pk__in=[i for i in chosen_index_ids if i]))[: series.MAX_SERIES - 1]
    picked = [int(i) for i in request.GET.getlist("inv") if i.isdigit()]
    group_broker = request.GET.get("group_broker")

    def compute():
        days = series.sample_dates(start, end)
        lines = []
        if mode == "a":
            ids = [i for i in picked if i in held_ids] or None
            gb = int(group_broker) if group_broker and group_broker.isdigit() else broker
            values, flows = series.portfolio_value_series(profile, days, portfolio=portfolio, broker=gb, instrument_ids=ids, settings_row=settings_row)
            lines.append(("Portfolio", series.performance_index(values, flows)))
        else:
            for inst, vals in series.price_lines(choices.filter(pk__in=picked), days):
                lines.append((inst.name, vals))
        for inst, vals in series.price_lines(chosen_indices, days):
            lines.append((inst.name, vals))
        return {"days": [d.isoformat() for d in days], "lines": [(label, [None if v is None else float(v) for v in vals]) for label, vals in lines]}

    params = {"m": mode, "s": start, "e": end, "p": portfolio, "b": broker, "i": chosen_index_ids, "v": picked, "g": group_broker}
    data = statscache.get_or_compute(profile, "chart", params, compute, today_sensitive=True)
    days = [date.fromisoformat(d) for d in data["days"]]
    lines = [(label, vals) for label, vals in data["lines"]]
    if request.GET.get("export") == "xlsx":
        from .exports import response

        return response(f"Chart {start:%Y-%m-%d} to {end:%Y-%m-%d}.xlsx", [("Chart", ["Date"] + [l for l, _ in lines],
                                                                         [[d] + [None if v[i] is None else round(v[i], 4) for _l, v in lines] for i, d in enumerate(days)])])
    chart = line_chart(days, lines)
    table = [(d, [None if v[i] is None else round(v[i], 2) for _l, v in lines]) for i, d in enumerate(days)]
    return page(request, "investments/charts.html", {
        "page_title_text": "Charts", "chart": chart, "lines": lines, "table": table[-60:], "table_all": len(table), "mode": mode, "period": period,
        "periods": CHART_PERIODS, "start": start, "end": end, "choices": choices, "picked": picked, "index_choices": index_choices,
        "chosen_index_ids": chosen_index_ids, "brokers": Broker.objects.filter(profile=profile), "group_broker": group_broker,
        "first": first})


def holdings_first_date(profile):
    from .models import Transaction

    return Transaction.objects.filter(profile=profile).order_by("date").values_list("date", flat=True).first()


@inv_reader
def value_view(request):
    """Total Portfolio Value on any date, by type, portfolio and broker, with a timeline. Dividends are never included."""
    profile = profile_or_404(request)
    portfolio, broker, asat = selection(request, profile)
    on = parse_date(request.GET.get("on")) or asat or date.today()
    on = min(on, date.today())
    settings_row = core.get_settings(profile, create=False)
    treatment = request.GET.get("alt")
    if treatment in ("unchanged", "averaged"):
        settings_row.alt_treatment = treatment
    rows, totals = holdings.compute(profile, portfolio=portfolio, broker=broker, as_of=on, settings=settings_row)
    held = holdings.held(rows)
    by_type = {}
    for h in held:
        by_type[h.instrument.get_kind_display()] = by_type.get(h.instrument.get_kind_display(), Decimal(0)) + h.value
    by_portfolio = []
    for p in Portfolio.objects.filter(profile=profile):
        if portfolio and p.pk != portfolio:
            continue
        by_portfolio.append((p.name, holdings.compute(profile, portfolio=p.pk, broker=broker, as_of=on, settings=settings_row)[1].value))
    by_broker = []
    for b in Broker.objects.filter(profile=profile):
        if broker and b.pk != broker:
            continue
        v = holdings.compute(profile, portfolio=portfolio, broker=b.pk, as_of=on, settings=settings_row)[1].value
        if v:
            by_broker.append((b.name, v))
    first = holdings_first_date(profile)
    timeline = None
    if first and first < on:
        def compute():
            days = series.sample_dates(first, on)
            values, _flows = series.portfolio_value_series(profile, days, portfolio=portfolio, broker=broker, settings_row=settings_row)
            return {"days": [d.isoformat() for d in days], "values": [float(v) for v in values]}

        data = statscache.get_or_compute(profile, "value_timeline", {"p": portfolio, "b": broker, "on": on, "alt": settings_row.alt_treatment}, compute,
                                         today_sensitive=True)
        timeline = line_chart([date.fromisoformat(d) for d in data["days"]], [("Total Portfolio Value", data["values"])])
    if request.GET.get("export") == "xlsx":
        from .exports import response

        return response(f"Total Portfolio Value {on:%Y-%m-%d}.xlsx", [
            ("Holdings", ["Investment", "Type", "Units", "Price", "Price date", "Value"], [[h.instrument.name, h.instrument.get_kind_display(), h.units, h.price,
                                                                                          h.price_date, h.value] for h in held]),
            ("By type", ["Type", "Value"], sorted(by_type.items())), ("By portfolio", ["Portfolio", "Value"], by_portfolio),
            ("By broker", ["Broker", "Value"], by_broker)])
    return page(request, "investments/value.html", {
        "page_title_text": "Total Portfolio Value", "rows": held, "totals": totals, "on": on, "by_type": sorted(by_type.items(), key=lambda kv: -kv[1]),
        "by_portfolio": by_portfolio, "by_broker": by_broker, "timeline": timeline, "alt_treatment": settings_row.alt_treatment,
        "has_alt": any(h.instrument.kind == "alternative" for h in held)})


__all__ = ["performance_view", "charts_view", "value_view", "Q"]


# ------------------------------------------------------------------ Annual Report (plan 13)

@inv_reader
def annual_view(request):
    from django.shortcuts import redirect
    from django.urls import reverse

    from .services import annual

    profile = profile_or_404(request)
    portfolio, broker, _asat = selection(request, profile)
    years = annual.year_choices(profile)
    label = request.GET.get("fy") if request.GET.get("fy") in years else years[0]
    settings_row = core.get_settings(profile, create=False)
    if request.method == "POST":
        from accounts.models import ROLE_EDITOR
        from accounts.profiles import request_role
        from accounts.suite import KEY_INVESTMENTS
        from django.core.exceptions import PermissionDenied

        if request_role(request, KEY_INVESTMENTS) != ROLE_EDITOR:
            raise PermissionDenied
        try:
            days = int(request.POST.get("cutoff", ""))
            if not 1 <= days <= 3650:
                raise ValueError
        except ValueError:
            messages.error(request, "The cutoff must be a number of days between 1 and 3650.")
        else:
            cutoffs = dict(settings_row.year_cutoffs or {})
            cutoffs[label] = days
            masters.update_settings(profile, request.user, year_cutoffs=cutoffs)
            messages.success(request, f"Long-term cutoff for {label} saved.")
        return redirect(reverse("investments_annual") + f"?fy={label}")
    from .viewutil import include_dividends

    report = annual.build(profile, label, portfolio=portfolio, broker=broker, include_dividends=include_dividends(request, profile))
    if request.GET.get("export") == "xlsx":
        return _annual_export(report)
    return page(request, "investments/annual.html", {"page_title_text": f"Annual Report {label}", "r": report, "years": years, "label": label,
                                                    "default_cutoff": settings_row.long_term_days, "include_div": settings_row.include_dividends})


def _annual_export(r):
    from .exports import response

    pct = (lambda v: None if v is None else round(v * 100, 2))
    summary = [["Starting portfolio value", r.opening_value], ["Amount invested", r.invested], ["Amount sold", r.sold], ["Amount re-invested", r.reinvested],
               ["Short-term capital gains", r.short_gain], ["Long-term capital gains", r.long_gain], ["XIRR for the year %", pct(r.xirr)],
               [f"{r.index_name} return %", pct(r.index_return)], ["Ending portfolio value", r.closing_value], ["Dividends received", r.dividends],
               ["Tax deducted on dividends", r.dividend_tax], ["Unrealised gain at year end", r.unrealised], ["Long-term after (days held)", r.cutoff],
               ["Note", "A record-keeping aid, not tax advice. Check the treatment with your CA."]]
    sales = [[s["name"], s["bought"], s["sold"], s["days"], s["units"], s["cost"], s["proceeds"], s["gain"], "Long-term" if s["term"] == "long" else "Short-term",
              "Estimated date" if s["estimated"] else ("Bonus" if s["bonus"] else "")] for s in r.sales]
    held = [[h.instrument.name, h.instrument.get_kind_display(), h.units, h.cost, h.value, h.value - h.cost, "Provisional" if (h.provisional or h.awaiting) else ""]
            for h in r.holdings]
    txns = [[t.date, t.instrument.name, t.get_side_display(), t.units, t.price, t.charges, t.amount if t.status == "awaiting" else None, t.broker.name, t.portfolio.name,
             t.get_status_display()] for t in r.transactions]
    by_pf = [[name, s.opening_value, s.invested, s.sold, s.short_gain, s.long_gain, pct(s.xirr), s.closing_value] for name, s in r.by_portfolio]
    return response(f"Annual Report {r.label}.xlsx", [
        ("Summary", ["Item", r.label], summary),
        ("Capital gains", ["Investment", "Bought (held from)", "Sold", "Days held", "Units", "Cost", "Proceeds", "Gain", "Term", "Note"], sales),
        ("Holdings at year end", ["Investment", "Type", "Units", "Cost", "Value", "Unrealised gain", ""], held),
        ("Transactions", ["Date", "Investment", "Buy / sell", "Units", "Price", "Charges", "Amount awaiting", "Broker", "Portfolio", "Status"], txns),
        ("By portfolio", ["Portfolio", "Starting value", "Invested", "Sold", "Short-term gains", "Long-term gains", "XIRR %", "Ending value"], by_pf)])


# ------------------------------------------------------------------ other reports and insights

@inv_reader
def reports_index(request):
    from .services.reports import REPORTS

    profile_or_404(request)
    return page(request, "investments/reports.html", {"page_title_text": "Other reports", "reports": [(slug, label) for slug, (_fn, label) in REPORTS.items()]})


@inv_reader
def report_view(request, slug):
    from django.http import Http404

    from .services.reports import REPORTS

    profile = profile_or_404(request)
    if slug not in REPORTS:
        raise Http404
    portfolio, broker, _asat = selection(request, profile)
    fn, _label = REPORTS[slug]
    years = int(request.GET.get("years", 3 if slug.startswith("compare") else 1)) if str(request.GET.get("years", "1")).isdigit() else 1
    days = int(request.GET.get("days", 60)) if str(request.GET.get("days", "60")).isdigit() else 60
    table = fn(profile, portfolio=portfolio, broker=broker, years=max(1, min(years, 20)), days=days)
    if request.GET.get("export") == "xlsx":
        from .exports import response

        def cell(v, kind):
            return round(v * 100, 2) if kind == "pct" and v is not None else v

        rows = [[cell(v, k) for v, (_h, k) in zip(row, table.columns)] for row in table.rows] + ([[cell(v, k) for v, (_h, k) in zip(table.total, table.columns)]] if table.total else [])
        return response(f"{table.title}.xlsx", [(table.title[:31], [h + (" %" if k == "pct" else "") for h, k in table.columns], rows)])
    rows = [list(zip(row, [k for _h, k in table.columns])) for row in table.rows]
    total = list(zip(table.total, [k for _h, k in table.columns])) if table.total else None
    return page(request, "investments/report.html", {"page_title_text": table.title, "t": table, "rows": rows, "total": total, "slug": slug, "years": years,
                                                    "days": days})


@inv_read_write_view
def insights_dismiss(request):
    from django.shortcuts import redirect

    from .services import insights

    profile = profile_or_404(request)
    if request.method == "POST":
        insights.dismiss(profile, request.POST.get("key", ""))
    from .viewutil import safe_next

    return redirect(safe_next(request, "/investments/dashboard/"))
