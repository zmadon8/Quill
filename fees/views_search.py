"""Search: the JSON endpoint behind the header search box and the full results page."""
from fees import scope
from fees.decorators import fees_reader, handle_fees_errors
from fees.pages import json_ok, render_page
from fees.services import search as search_service


@fees_reader
@handle_fees_errors(json=True)
def search_json(request):
    profile, _settings = scope.context(request)
    query = request.GET.get("q", "")
    return json_ok({"query": query.strip(), "results": search_service.search(profile, query)})


@fees_reader
@handle_fees_errors()
def search_page(request):
    profile, _settings = scope.context(request)
    query = request.GET.get("q", "")
    return render_page(
        request,
        "fees/search.html",
        {"query": query.strip(), "results": search_service.search(profile, query, limit=100)},
    )
