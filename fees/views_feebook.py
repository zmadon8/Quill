"""Feebook: every payment against the memos it settled, and the unaccounted payments."""
from django.views.decorators.http import require_GET

from fees import scope
from fees.decorators import fees_reader, handle_fees_errors
from fees.pages import feebook_filters, page_number, render_page
from fees.services import feebook, firms, memo_lists
from fees.services import settings as settings_service

PAGE_SIZE = 50


@fees_reader
@handle_fees_errors()
@require_GET
def feebook_page(request):
    profile, settings = scope.context(request)
    filters = feebook_filters(request.GET)
    entries = feebook.list_feebook(profile, filters)
    page_items, meta = memo_lists.paginate(entries, page_number(request.GET), PAGE_SIZE)
    query = request.GET.copy()
    query.pop("page", None)
    return render_page(
        request,
        "fees/feebook.html",
        {
            "entries": page_items,
            "meta": meta,
            "filters": filters,
            "firm_choices": firms.list_firms(profile),
            "bank_choices": settings_service.list_bank_accounts(profile),
            "money_unit": settings.money_unit,
            "query_string": query.urlencode(),
        },
    )
