"""Search: the JSON endpoint behind the header search box and the full results page."""
from django.urls import reverse
from django.views.decorators.http import require_safe

from fees import scope
from fees.decorators import fees_reader, handle_fees_errors
from fees.pages import json_ok, render_page
from fees.services import search as search_service


_ITEM_URLS = {"firm": "fees_firm_detail", "matter": "fees_matter_detail", "memo": "fees_memo_detail"}


def _with_urls(results):
    """Each result with the ``url`` of the page it opens."""
    return [dict(r, url=reverse(_ITEM_URLS[r["kind"]], args=[r["id"]])) for r in results]


@fees_reader
@handle_fees_errors(json=True)
@require_safe
def search_json(request):
    profile, _settings = scope.context(request)
    query = request.GET.get("q", "")
    return json_ok({"query": query.strip(), "results": _with_urls(search_service.search(profile, query))})


@fees_reader
@handle_fees_errors()
@require_safe
def search_page(request):
    profile, _settings = scope.context(request)
    query = request.GET.get("q", "")
    return render_page(
        request,
        "fees/search.html",
        {"query": query.strip(), "results": search_service.search(profile, query, limit=100)},
    )
