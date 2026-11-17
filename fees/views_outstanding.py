"""Outstanding memos: the firm summary and the detail grouped by matter."""
import datetime
from urllib.parse import urlencode

from django.views.decorators.http import require_safe

from fees import scope
from fees.decorators import fees_reader, handle_fees_errors
from fees.pages import outstanding_filters, overdue_on, render_page
from fees.services import filter_options, outstanding, payments


VIEWS = ("grouped", "summary", "flat")
FLAT_SORTS = {
    "firm": lambda e: (e["firm_name"].lower(), e["partner_name"].lower(), e["matter_name"].lower(), _day(e)),
    "group": lambda e: (e["partner_name"].lower(), e["firm_name"].lower(), e["matter_name"].lower(), _day(e)),
    # Client: matters with no client last.
    "client": lambda e: (not e["client_name"], e["client_name"].lower(), e["firm_name"].lower(), e["matter_name"].lower(), _day(e)),
    "matter": lambda e: (e["matter_name"].lower(), e["firm_name"].lower(), _day(e)),
    "date": lambda e: (_day(e), e["firm_name"].lower(), e["matter_name"].lower()),
}


SORT_CHOICES = (("firm", "Firm"), ("group", "Partner"), ("client", "Client"), ("matter", "Matter"), ("date", "Date"), ("due", "Amount Due (High To Low)"))


def _day(entry):
    return entry["date"] or datetime.date.min


def _flat(groups, sort):
    """Every memo of ``groups`` as one list (in memory, no queries), sorted for the In order view."""
    entries = [e for g in groups for e in g["entries"]]
    if sort == "due":
        return sorted(entries, key=lambda e: e["due"], reverse=True)
    return sorted(entries, key=FLAT_SORTS.get(sort, FLAT_SORTS["firm"]))


def _query_without_overdue(request, settings):
    """The page's query string; ``overdue`` is dropped when Overdue after (days) is 0."""
    query = request.GET.copy()
    if not overdue_on(settings):
        query.pop("overdue", None)
    return query.urlencode()


def _scope_choices(profile, filters):
    return outstanding.list_outstanding_scope(
        profile, {k: v for k, v in filters.items() if k in ("include_written_off", "overdue_only")}
    )


#: By Firm columns that sort from the table headings: key -> (heading, sort key, first click goes descending).
SUMMARY_SORTS = {
    "firm": ("Firm", lambda r: r["firm_name"].lower(), False),
    "memos": ("Memos", lambda r: r["memo_count"], True),
    "share": ("Share of total", lambda r: r["outstanding"], True),
    "outstanding": ("Outstanding", lambda r: r["outstanding"], True),
}
#: The old ``?sort=name`` / ``?sort=amount`` values (links, bookmarks, the Excel export) still work.
_SUMMARY_ALIASES = {"name": "firm", "amount": "-outstanding"}
SUMMARY_DEFAULT_SORT = "-outstanding"


def parse_summary_sort(raw):
    """``(key, descending)`` from ``?sort=`` ("firm", "-firm", "name", ...); the default is Outstanding, high to low."""
    raw = _SUMMARY_ALIASES.get(raw, raw or SUMMARY_DEFAULT_SORT)
    descending = raw.startswith("-")
    key = raw[1:] if descending else raw
    if key not in SUMMARY_SORTS:
        return parse_summary_sort(SUMMARY_DEFAULT_SORT)
    return key, descending


def _summary_headers(query, key, descending):
    """Sortable heading descriptors (label, link, aria-sort) for the By Firm table. A heading's first click sorts it the
    natural way (A to Z, or high to low for numbers); clicking the sorted heading again reverses it. The other
    filters in ``query`` (a dict) stay in the link."""
    out = {}
    for name, (label, _fn, first_desc) in SUMMARY_SORTS.items():
        on = name == key
        if on:
            target = name if descending else f"-{name}"
        else:
            target = f"-{name}" if first_desc else name
        out[name] = {"label": label, "url": "?" + urlencode(dict(query, sort=target)),
                     "aria": ("descending" if descending else "ascending") if on else "none"}
    return out


@fees_reader
@handle_fees_errors()
@require_safe
def outstanding_summary(request):
    profile, settings = scope.context(request)
    filters = outstanding_filters(request.GET, overdue_on(settings))
    key, descending = parse_summary_sort(request.GET.get("sort"))
    rows = outstanding.list_outstanding_by_firm(profile, filters, "name")  # A to Z; the sort below is stable
    rows.sort(key=SUMMARY_SORTS[key][1], reverse=descending)
    carried = {k: "1" for k, name in (("written_off", "include_written_off"), ("overdue", "overdue_only")) if filters.get(name)}
    grand_total = sum((r["outstanding"] for r in rows), start=0)
    # Share of the total per firm (a bar on each row) and the four ageing totals above the table (owner round 2026-11).
    rows = [dict(r, detail_query=urlencode(dict(carried, firm=r["firm_id"])),
                 share=int(round(r["outstanding"] / grand_total * 100)) if grand_total else 0) for r in rows]
    return render_page(
        request,
        "fees/outstanding.html",
        {
            "rows": rows,
            # Each card links to the memo list for its age range, keeping the other filters.
            "ageing": [dict(b, detail_query=urlencode(dict(carried, age=b["key"]))) for b in outstanding.ageing_totals(rows)],
            "grand_total": grand_total,
            "filters": filters,
            "sort_key": key,
            "sort_descending": descending,
            "heads": _summary_headers(carried, key, descending),
            "money_unit": settings.money_unit,
            "query_string": _query_without_overdue(request, settings),
        },
    )


@fees_reader
@handle_fees_errors()
@require_safe
def outstanding_detail(request):
    profile, settings = scope.context(request)
    filters = outstanding_filters(request.GET, overdue_on(settings))
    groups = outstanding.list_outstanding(profile, filters)
    view = request.GET.get("view")
    if view not in VIEWS:
        # One firm's memos open as Matter Totals; every firm together as one flat list (owner round 2026-12).
        view = "summary" if "firm_id" in filters else "flat"
    flat_sort = request.GET.get("sort") if request.GET.get("sort") in (*FLAT_SORTS, "due") else "firm"
    # The view and sort choices are not filters, so the Export link leaves them out.
    export_query = {k: v for k, v in request.GET.items() if k not in ("view", "sort") and (k != "overdue" or overdue_on(settings))}
    return render_page(
        request,
        "fees/outstanding_detail.html",
        {
            "groups": groups,
            "flat_entries": _flat(groups, flat_sort) if view == "flat" else [],
            "view": view,
            "sorts": SORT_CHOICES,
            "flat_sort": flat_sort,
            "max_allocations": payments.MAX_ALLOCATIONS,
            "memo_count": sum(len(g["entries"]) for g in groups),
            "grand_total": outstanding.outstanding_grand_total(groups),
            "filters": filters,
            "age_label": next((b[1] for b in outstanding.AGEING_BUCKETS if b[0] == filters.get("age")), ""),
            "clear_age_query": urlencode({k: v for k, v in export_query.items() if k != "age"}),
            "choices": filter_options.narrow_outstanding_choices(profile, _scope_choices(profile, filters), filters),
            "money_unit": settings.money_unit,
            "query_string": urlencode(export_query),
        },
    )
