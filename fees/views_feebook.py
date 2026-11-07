"""Feebook: every payment against the memos it settled, and the unaccounted payments."""
from django.views.decorators.http import require_safe

from fees import scope
from fees.decorators import fees_reader, handle_fees_errors
from fees.pages import feebook_filters, page_number, render_page
from fees.services import feebook, firms, fy_options, memo_lists, prefs
from fees.services import settings as settings_service


@fees_reader
@handle_fees_errors()
@require_safe
def feebook_page(request):
    profile, settings = scope.context(request)
    filters = feebook_filters(request.GET)
    entries = feebook.list_feebook(profile, filters)
    totals = {
        key: sum((e[key] or 0 for e in entries), start=0) for key in ("amount_paid", "tds", "paid_plus_tds")
    }
    totals["count"] = len(entries)
    page_items, meta = memo_lists.paginate(
        entries, page_number(request.GET), memo_lists.page_size_for(prefs.personal_items_per_page(profile, request.user, settings))
    )
    query = request.GET.copy()
    query.pop("page", None)
    return render_page(
        request,
        "fees/feebook.html",
        {
            "entries": page_items,
            "meta": meta,
            "totals": totals,
            "filters": filters,
            "firm_choices": firms.list_firms(profile),
            "fy_options": fy_options.financial_year_options(
                profile, settings.feebook_start_year, filters.get("financial_year")
            ),
            "bank_choices": settings_service.list_bank_accounts(profile),
            "money_unit": settings.money_unit,
            "query_string": query.urlencode(),
        },
    )
