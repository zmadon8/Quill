"""Outstanding memos: the firm summary and the detail grouped by matter."""
from django.views.decorators.http import require_safe

from fees import scope
from fees.decorators import fees_reader, handle_fees_errors
from fees.pages import outstanding_filters, render_page
from fees.services import outstanding


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
    return render_page(
        request,
        "fees/outstanding_detail.html",
        {
            "groups": groups,
            "grand_total": outstanding.outstanding_grand_total(groups),
            "filters": filters,
            "choices": _scope_choices(profile, filters),
            "money_unit": settings.money_unit,
            "query_string": request.GET.urlencode(),
        },
    )
