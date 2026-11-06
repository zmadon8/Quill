"""Statistics: the period table, the pivot, saved views, the year-end page and the statistics exports."""
import re

from django.views.decorators.http import require_http_methods, require_POST, require_safe

from fees import scope
from fees.decorators import fees_editor, fees_read_write, fees_reader, handle_fees_errors
from fees.errors import FeesError
from fees.exports import tax_summary, xlsx
from fees.pages import TEXT_TYPE, XLSX_TYPE, file_response, flag, int_or_none, json_ok, render_page
from fees.services import firms, statistics
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


@fees_reader
@handle_fees_errors()
@require_safe
def statistics_page(request):
    profile, _settings = scope.context(request)
    granularity = granularity_param(request.GET)
    fy = financial_year_param(request.GET)
    stats = statistics.get_period_statistics(
        profile, granularity, None if granularity == "financialYear" else fy, stat_options(request.GET)
    )
    return render_page(
        request,
        "fees/statistics.html",
        {
            "granularity": granularity,
            "fy": fy,
            "stats": stats,
            "table": _table(stats),
            "granularities": _GRANULARITIES,
            "saved_views": statistics.list_saved_views(profile),
        },
    )


@fees_reader
@handle_fees_errors(json=True)
@require_safe
def data(request):
    """JSON: the period table."""
    profile, _settings = scope.context(request)
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
    profile, _settings = scope.context(request)
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
    profile, _settings = scope.context(request)
    if request.method == "POST":
        post = request.POST
        view_input = {
            "name": post.get("name", ""),
            "measure": (post.get("measure") or "").strip(),
            "row_dim": (post.get("row_dim") or "").strip(),
            "col_dim": (post.get("col_dim") or "").strip(),
            "from_fy": financial_year_param(post, "from_fy", default=False) or "",
            "to_fy": financial_year_param(post, "to_fy", default=False) or "",
        }
        firm_id = int_or_none(post.get("firm_id"))
        if firm_id is not None:
            firms.get_firm(profile, firm_id)  # another profile's firm is a 404
            view_input["firm_id"] = firm_id
        return json_ok({"views": statistics.save_saved_view(profile, view_input)}, status=201)
    return json_ok({"views": statistics.list_saved_views(profile)})


@fees_editor
@handle_fees_errors(json=True)
@require_POST
def saved_view_delete(request, view_id):
    profile, _settings = scope.context(request)
    return json_ok({"views": statistics.delete_saved_view(profile, view_id)})


@fees_reader
@handle_fees_errors()
@require_safe
def year_end(request):
    profile, _settings = scope.context(request)
    fy = financial_year_param(request.GET)
    summary = statistics.get_year_end_summary(profile, fy, stat_options(request.GET))
    return render_page(request, "fees/year_end.html", {"fy": fy, "summary": summary})


@fees_reader
@handle_fees_errors()
@require_safe
def export_statistics(request):
    profile, _settings = scope.context(request)
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
    profile, _settings = scope.context(request)
    fy = financial_year_param(request.GET)
    with heavy_operation("annual_export"):
        result = xlsx.export_annual_summary(profile, fy, stat_options(request.GET))
    return file_response(result, XLSX_TYPE)


@fees_reader
@handle_fees_errors()
@require_safe
def export_tax_summary(request):
    profile, _settings = scope.context(request)
    fy = financial_year_param(request.GET)
    return file_response(tax_summary.export_tax_summary(profile, fy, stat_options(request.GET)), TEXT_TYPE)
