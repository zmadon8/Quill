"""Feebook: every payment against the memos it settled, and the unaccounted payments."""
from django.views.decorators.http import require_safe

from fees import scope
from fees.decorators import fees_reader, handle_fees_errors
from fees.pages import feebook_filters, page_number, render_page
from fees.services import feebook, filter_options, fy_options, memo_lists, prefs
from fees.services import settings as settings_service
from fees.services.financial_year import current_financial_year


@fees_reader
@handle_fees_errors()
@require_safe
def feebook_page(request):
    profile, settings = scope.context(request)
    current = current_financial_year()
    filters = feebook_filters(request.GET, current)
    banks = list(settings_service.list_bank_accounts(profile))
    options = filter_options.feebook_options(profile, filters, banks)
    if "fy" not in request.GET:
        # No year in the link: the current year, or the newest year with payments when the current year has none.
        chosen = filter_options.default_year(options["years"], current)
        if chosen != filters.get("financial_year"):
            filters = {k: v for k, v in filters.items() if k != "financial_year"}
            if chosen:
                filters["financial_year"] = chosen
            options = filter_options.feebook_options(profile, filters, banks)
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
    if "fy" not in query and filters.get("financial_year"):
        query["fy"] = filters["financial_year"]
    return render_page(
        request,
        "fees/feebook.html",
        {
            "entries": page_items,
            "meta": meta,
            "totals": totals,
            "filters": filters,
            "firm_choices": options["firms"],
            "fy_options": fy_options.financial_year_options(
                profile, settings.feebook_start_year, filters.get("financial_year"), only_years=options["years"]
            ),
            "bank_choices": options["banks"],
            "money_unit": settings.money_unit,
            "query_string": query.urlencode(),
        },
    )
