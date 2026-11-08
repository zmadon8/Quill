"""Outstanding memos: the firm summary and the detail grouped by matter."""
import datetime
from urllib.parse import urlencode

from django.views.decorators.http import require_safe

from fees import scope
from fees.decorators import fees_reader, handle_fees_errors
from fees.pages import outstanding_filters, render_page
from fees.services import filter_options, outstanding


VIEWS = ("grouped", "summary", "flat")
FLAT_SORTS = {
    "firm": lambda e: (e["firm_name"].lower(), e["partner_name"].lower(), e["matter_name"].lower(), _day(e)),
    "group": lambda e: (e["partner_name"].lower(), e["firm_name"].lower(), e["matter_name"].lower(), _day(e)),
    "matter": lambda e: (e["matter_name"].lower(), e["firm_name"].lower(), _day(e)),
    "date": lambda e: (_day(e), e["firm_name"].lower(), e["matter_name"].lower()),
}


SORT_CHOICES = (("firm", "Firm"), ("group", "Group"), ("matter", "Matter"), ("date", "Date"), ("due", "Amount Due (High To Low)"))


def _day(entry):
    return entry["date"] or datetime.date.min


def _flat(groups, sort):
    """Every memo of ``groups`` as one list (in memory, no queries), sorted for the In order view."""
    entries = [e for g in groups for e in g["entries"]]
    if sort == "due":
        return sorted(entries, key=lambda e: e["due"], reverse=True)
    return sorted(entries, key=FLAT_SORTS.get(sort, FLAT_SORTS["firm"]))


def _scope_choices(profile, filters):
    return outstanding.list_outstanding_scope(
        profile, {k: v for k, v in filters.items() if k in ("include_written_off", "overdue_only")}
    )


@fees_reader
@handle_fees_errors()
@require_safe
def outstanding_summary(request):
    profile, settings = scope.context(request)
    filters = outstanding_filters(request.GET)
    sort = "name" if request.GET.get("sort") == "name" else "amount"
    rows = outstanding.list_outstanding_by_firm(profile, filters, sort)
    carried = {k: "1" for k, name in (("written_off", "include_written_off"), ("overdue", "overdue_only")) if filters.get(name)}
    rows = [dict(r, detail_query=urlencode(dict(carried, firm=r["firm_id"]))) for r in rows]
    return render_page(
        request,
        "fees/outstanding.html",
        {
            "rows": rows,
            "grand_total": sum((r["outstanding"] for r in rows), start=0),
            "filters": filters,
            "sort": sort,
            "money_unit": settings.money_unit,
            "query_string": request.GET.urlencode(),
        },
    )


@fees_reader
@handle_fees_errors()
@require_safe
def outstanding_detail(request):
    profile, settings = scope.context(request)
    filters = outstanding_filters(request.GET)
    groups = outstanding.list_outstanding(profile, filters)
    view = request.GET.get("view")
    if view not in VIEWS:
        view = "grouped" if "firm_id" in filters else "flat"
    flat_sort = request.GET.get("sort") if request.GET.get("sort") in (*FLAT_SORTS, "due") else "firm"
    # The view and sort choices are not filters, so the Export link leaves them out.
    export_query = {k: v for k, v in request.GET.items() if k not in ("view", "sort")}
    return render_page(
        request,
        "fees/outstanding_detail.html",
        {
            "groups": groups,
            "flat_entries": _flat(groups, flat_sort) if view == "flat" else [],
            "view": view,
            "sorts": SORT_CHOICES,
            "flat_sort": flat_sort,
            "memo_count": sum(len(g["entries"]) for g in groups),
            "grand_total": outstanding.outstanding_grand_total(groups),
            "filters": filters,
            "choices": filter_options.narrow_outstanding_choices(profile, _scope_choices(profile, filters), filters),
            "money_unit": settings.money_unit,
            "query_string": urlencode(export_query),
        },
    )
