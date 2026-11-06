"""Statistics: the period table, the pivot, saved views, the year-end page and the statistics exports."""
import re
from urllib.parse import urlencode

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from fees import scope
from fees.decorators import fees_editor, fees_read_write, fees_reader, handle_fees_errors
from fees.errors import FeesError
from fees.exports import tax_summary, xlsx
from fees.pages import TEXT_TYPE, XLSX_TYPE, file_response, flag, int_or_none, json_ok, render_page
from fees.services import firms, fy_options, statistics
from fees.services.financial_year import current_financial_year
from fees.services.heavy import heavy_operation

_FY_RE = re.compile(r"^\d{4}-\d{2}$")
_GRANULARITIES = ("month", "quarter", "financialYear")
_OPTION_FLAGS = (
    "pro_rate_current_month",
    "exclude_future_months",
    "exclude_current_month",
    "include_drafts",
)


_TABS = ("standard", "explore")
#: Fiscal-year order of the calendar months (April first).
FY_MONTHS = (4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3)
MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
MEASURES = (
    ("billed", "Amount Billed"),
    ("received", "Amount Received"),
    ("receivedPlusTds", "Received + TDS"),
    ("appearances", "Appearances"),
    ("conferences", "Conferences"),
    ("drafts", "Drafts"),
    ("memos", "Memos (count)"),
    ("matters", "Matters (distinct)"),
    ("mattersNew", "Matters (new)"),
    ("appearancesPerWeek", "Appearances / Week (time rows)"),
    ("feesPerWeek", "Fees / Week (time rows)"),
)
ROW_DIMS = (
    ("month", "Month"),
    ("quarter", "Quarter"),
    ("financialYear", "Financial Year"),
    ("calendarMonth", "Calendar Month (across years)"),
    ("firm", "Firm"),
    ("partner", "Group"),
    ("matter", "Matter"),
)
COL_DIMS = (
    ("none", "None (single column)"),
    ("financialYear", "Financial Year"),
    ("calendarMonth", "Calendar Month"),
)
_ADJUSTMENT_COUNTS = ("working_days", "extra_appearances", "extra_conferences", "extra_drafts")
_ADJUSTMENT_OVERRIDES = (
    "override_appearances", "override_conferences", "override_drafts",
    "override_billed", "override_received", "override_received_plus_tds",
)


def ensure_statistics_on(config):
    """Raise ``STATISTICS_DISABLED`` (409) when the profile has Statistics switched off (owner decision 3).

    Nothing in the statistics engine runs when it is off, so every Statistics page, data, explore, saved
    view, adjustment and export view calls this first. ``config`` is the settings from ``scope.context``.
    """
    if config is not None and not config.statistics_enabled:
        raise FeesError("STATISTICS_DISABLED")


def is_page_post(request):
    """True when a form on the Statistics page posted (it wants a redirect back, not JSON)."""
    return request.POST.get("return_to") in ("statistics", "settings")


def page_post(request, action, done, _to="fees_statistics", _fragment="", **query):
    """Run ``action`` for a page form: flash ``done`` or its error and go back to the page ``_to``
    (the Statistics page unless told otherwise; ``_fragment`` such as ``#settings-years`` is added last)."""
    query = {k: v for k, v in query.items() if not k.endswith("fy") or v == "" or _FY_RE.match(v)}
    try:
        action()
        messages.success(request, done)
    except FeesError as err:
        if err.status == 404:
            raise Http404(err.message) from err
        messages.error(request, err.message)
    return redirect(reverse(_to) + "?" + urlencode(query) + _fragment)


def financial_year_param(query, key="fy", default=True):
    """A financial year label from the query string (``YYYY-YY``); the current one when absent."""
    text = (query.get(key) or "").strip()
    if not text:
        return current_financial_year() if default else None
    if not _FY_RE.match(text):
        raise FeesError("INVALID_FINANCIAL_YEAR", "A financial year looks like 2026-27.")
    return text


def granularity_param(query):
    text = (query.get("granularity") or "month").strip()
    if text not in _GRANULARITIES:
        raise FeesError("INVALID_GRANULARITY", "Choose month, quarter or financialYear.")
    return text


def stat_options(query):
    """The period-engine options present in the query string."""
    options = {}
    for key in _OPTION_FLAGS:
        if key in query:
            options[key] = flag(query.get(key))
    minimum = (query.get("min_financial_year") or "").strip()
    if minimum:
        if not _FY_RE.match(minimum):
            raise FeesError("INVALID_FINANCIAL_YEAR", "A financial year looks like 2026-27.")
        options["min_financial_year"] = minimum
    return options


def _table(stats):
    """The rows of the period table: one per metric, one value per period."""
    rows = []
    for key, label, is_money in xlsx.STAT_METRIC_ROWS:
        rows.append(
            {"label": label, "money": is_money, "cells": [period.get(key) for period in stats["periods"]]}
        )
    return rows


#: Metrics that add up across periods (the Total column); ratios do not.
_SUMMED_METRICS = frozenset(
    ("num_appearances", "num_conferences", "num_drafts", "amount_billed", "amount_recovered",
     "amount_received", "amount_received_plus_tds")
)


def _display_table(stats):
    """The period table for the page: like ``_table`` but each cell says whether it was typed in by hand,
    plus a Total per summable metric. The JSON endpoint keeps using ``_table``."""
    periods = stats["periods"]
    rows = []
    for key, label, is_money in xlsx.STAT_METRIC_ROWS:
        cells = [
            {
                "value": period.get(key),
                "overridden": key in (period.get("overridden") or ()),
                "current": bool(period.get("is_current_month")),
            }
            for period in periods
        ]
        total = None
        if key in _SUMMED_METRICS and periods:
            total = sum((period.get(key) or 0 for period in periods), 0)
        rows.append({"label": label, "money": is_money, "cells": cells, "total": total})
    return rows


def adjustment_rows(profile, fy):
    """Twelve month rows in financial-year order, each with the saved adjustment values (blank when none)."""
    saved = {row["month"]: row for row in statistics.list_adjustments(profile, fy)}
    rows = []
    for month in FY_MONTHS:
        row = saved.get(month) or {}
        rows.append(
            {
                "month": month,
                "name": MONTH_NAMES[month - 1],
                "counts": [
                    {"key": key, "label": key.replace("_", " ").capitalize(), "value": row.get(key, 0)}
                    for key in _ADJUSTMENT_COUNTS
                ],
                "overrides": [
                    {"key": key, "label": key[len("override_"):].replace("_", " ").capitalize(), "value": row.get(key)}
                    for key in _ADJUSTMENT_OVERRIDES
                ],
            }
        )
    return rows


def _choice(query, key, choices, default):
    value = (query.get(key) or default).strip()
    return value if value in dict(choices) else default


def _explore_context(profile, query):
    """The Explore tab: the chosen pivot settings, the pivot as table rows, and the saved views with their links."""
    chosen = {
        "measure": _choice(query, "measure", MEASURES, "billed"),
        "row_dim": _choice(query, "row_dim", ROW_DIMS, "financialYear"),
        "col_dim": _choice(query, "col_dim", COL_DIMS, "none"),
        "from_fy": financial_year_param(query, "from_fy", default=False) or "",
        "to_fy": financial_year_param(query, "to_fy", default=False) or "",
        "firm_id": int_or_none(query.get("firm_id")),
    }
    req = {key: chosen[key] for key in ("measure", "row_dim", "col_dim")}
    for key in ("from_fy", "to_fy", "firm_id"):
        if chosen[key]:
            req[key] = chosen[key]
    context = {"chosen": chosen, "firm_choices": firms.list_firms(profile), "pivot": None, "pivot_error": ""}
    try:
        pivot = statistics.get_pivot(profile, req)
    except FeesError as err:
        if err.status == 404:
            raise
        context["pivot_error"] = err.message
        return context
    columns = pivot["columns"]
    rows = [
        {"label": row["label"], "values": [row["cells"].get(col["key"]) for col in columns], "total": row["total"]}
        for row in pivot["rows"]
    ]
    context["pivot"] = {
        "money": pivot["money"],
        "columns": columns,
        "rows": rows,
        "totals": [pivot["column_totals"].get(col["key"]) for col in columns],
        "grand_total": pivot["grand_total"],
    }
    context["chart_data"] = {
        "money": pivot["money"],
        "columns": [col["label"] for col in columns],
        "rows": [{"label": row["label"], "values": row["values"]} for row in rows],
    }
    return context


def saved_view_query(view):
    """The Explore link that opens a saved view."""
    query = {"tab": "explore", "measure": view["measure"], "row_dim": view["row_dim"], "col_dim": view["col_dim"]}
    for key in ("from_fy", "to_fy", "firm_id"):
        if view.get(key):
            query[key] = view[key]
    return urlencode(query)


@fees_reader
@handle_fees_errors()
@require_safe
def statistics_page(request):
    profile, config = scope.context(request)
    if config is not None and not config.statistics_enabled:
        return render_page(request, "fees/statistics.html", {"stats_off": True})
    tab = _choice(request.GET, "tab", [(t, t) for t in _TABS], "standard")
    granularity = granularity_param(request.GET)
    fy = financial_year_param(request.GET)
    context = {
        "tab": tab,
        "granularity": granularity,
        "fy": fy,
        "granularities": _GRANULARITIES,
        "money_unit": config.money_unit,
        "months": MONTH_NAMES,
        "fy_options": fy_options.financial_year_options(profile, config.initial_financial_year, fy),
    }
    if tab == "standard":
        stats = statistics.get_period_statistics(
            profile, granularity, None if granularity == "financialYear" else fy, stat_options(request.GET)
        )
        context.update({"stats": stats, "table": _display_table(stats)})
    else:
        context.update(_explore_context(profile, request.GET))
        context["fy_options"] = fy_options.financial_year_options(
            profile, config.initial_financial_year, (fy, context["chosen"]["from_fy"], context["chosen"]["to_fy"])
        )
        context.update(
            measures=MEASURES, row_dims=ROW_DIMS, col_dims=COL_DIMS,
            saved_views=[dict(v, query=saved_view_query(v)) for v in statistics.list_saved_views(profile)],
        )
    return render_page(request, "fees/statistics.html", context)


@fees_reader
@handle_fees_errors(json=True)
@require_safe
def data(request):
    """JSON: the period table."""
    profile, config = scope.context(request)
    ensure_statistics_on(config)
    granularity = granularity_param(request.GET)
    fy = financial_year_param(request.GET)
    stats = statistics.get_period_statistics(
        profile, granularity, None if granularity == "financialYear" else fy, stat_options(request.GET)
    )
    return json_ok({"statistics": stats, "rows": _table(stats)})


@fees_reader
@handle_fees_errors(json=True)
@require_safe
def explore(request):
    """JSON: a pivot of one measure over a row dimension and an optional column dimension."""
    profile, config = scope.context(request)
    ensure_statistics_on(config)
    query = request.GET
    req = {
        "measure": (query.get("measure") or "billed").strip(),
        "row_dim": (query.get("row_dim") or "financialYear").strip(),
        "col_dim": (query.get("col_dim") or "none").strip(),
    }
    firm_id = int_or_none(query.get("firm_id"))
    if firm_id is not None:
        req["firm_id"] = firm_id
    for key in ("from_fy", "to_fy"):
        value = financial_year_param(query, key, default=False)
        if value:
            req[key] = value
    return json_ok({"pivot": statistics.get_pivot(profile, req)})


@fees_read_write
@handle_fees_errors(json=True)
@require_http_methods(["GET", "HEAD", "POST"])
def saved_views(request):
    """JSON: the saved pivot views (GET); save a new one (POST, Editor)."""
    profile, config = scope.context(request)
    if request.method == "POST":
        post = request.POST

        def save():
            ensure_statistics_on(config)
            view_input = {
                "name": post.get("name", ""),
                "measure": (post.get("measure") or "").strip(),
                "row_dim": (post.get("row_dim") or "").strip(),
                "col_dim": (post.get("col_dim") or "").strip(),
            }
            for key in ("from_fy", "to_fy"):
                view_input[key] = financial_year_param(post, key, default=False) or ""
            firm_id = int_or_none(post.get("firm_id"))
            if firm_id is not None:
                firms.get_firm(profile, firm_id)  # another profile's firm is a 404
                view_input["firm_id"] = firm_id
            statistics.save_saved_view(profile, view_input)

        if is_page_post(request):
            back = {"tab": "explore"}
            for key in ("measure", "row_dim", "col_dim", "from_fy", "to_fy", "firm_id"):
                if post.get(key):
                    back[key] = post.get(key)
            return page_post(request, save, "View saved.", **back)
        save()
        return json_ok({"views": statistics.list_saved_views(profile)}, status=201)
    ensure_statistics_on(config)
    return json_ok({"views": statistics.list_saved_views(profile)})


@fees_editor
@handle_fees_errors(json=True)
@require_POST
def saved_view_delete(request, view_id):
    profile, config = scope.context(request)

    def delete():
        ensure_statistics_on(config)
        return statistics.delete_saved_view(profile, view_id)

    if is_page_post(request):
        return page_post(request, delete, "View deleted.", tab="explore")
    return json_ok({"views": delete()})


@fees_reader
@handle_fees_errors()
@require_safe
def year_end(request):
    profile, config = scope.context(request)
    if config is not None and not config.statistics_enabled:
        return render_page(request, "fees/statistics.html", {"stats_off": True})
    fy = financial_year_param(request.GET)
    summary = statistics.get_year_end_summary(profile, fy, stat_options(request.GET))
    return render_page(request, "fees/year_end.html", {"fy": fy, "summary": summary})


@fees_reader
@handle_fees_errors()
@require_safe
def export_statistics(request):
    profile, config = scope.context(request)
    ensure_statistics_on(config)
    granularity = granularity_param(request.GET)
    fy = financial_year_param(request.GET)
    result = xlsx.export_statistics(
        profile, granularity, None if granularity == "financialYear" else fy, stat_options(request.GET)
    )
    return file_response(result, XLSX_TYPE)


@fees_reader
@handle_fees_errors()
@require_safe
def export_annual(request):
    profile, config = scope.context(request)
    ensure_statistics_on(config)
    fy = financial_year_param(request.GET)
    with heavy_operation("annual_export"):
        result = xlsx.export_annual_summary(profile, fy, stat_options(request.GET))
    return file_response(result, XLSX_TYPE)


@fees_reader
@handle_fees_errors()
@require_safe
def export_tax_summary(request):
    profile, config = scope.context(request)
    ensure_statistics_on(config)
    fy = financial_year_param(request.GET)
    return file_response(tax_summary.export_tax_summary(profile, fy, stat_options(request.GET)), TEXT_TYPE)
