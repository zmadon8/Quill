"""Search: the JSON endpoint behind the header search box and the full results page."""
from django.urls import reverse
from django.views.decorators.http import require_safe

from fees import scope
from fees.decorators import fees_reader, handle_fees_errors
from fees.pages import json_ok, render_page
from fees.services import search as search_service


_ITEM_URLS = {"firm": "fees_firm_detail", "matter": "fees_matter_detail", "memo": "fees_memo_detail"}


def _with_urls(results):
    """Each result with the ``url`` of the page it opens (pages, partners and clients carry theirs already)."""
    return [r if r.get("url") else dict(r, url=reverse(_ITEM_URLS[r["kind"]], args=[r["id"]])) for r in results]


def _options(request, settings):
    """Who is searching: pages they cannot open are not offered."""
    from accounts.models import ROLE_EDITOR
    from accounts.profiles import request_role
    from accounts.suite import KEY_FEES
    from fees.pages import dashboard_on

    return {"can_edit": request_role(request, KEY_FEES) == ROLE_EDITOR, "statistics_on": dashboard_on(settings)}


@fees_reader
@handle_fees_errors(json=True)
@require_safe
def search_json(request):
    profile, settings = scope.context(request)
    query = request.GET.get("q", "")
    return json_ok({"query": query.strip(), "results": _with_urls(search_service.search(profile, query, **_options(request, settings)))})


@fees_reader
@handle_fees_errors()
@require_safe
def search_page(request):
    profile, settings = scope.context(request)
    query = request.GET.get("q", "")
    return render_page(
        request,
        "fees/search.html",
        {"query": query.strip(), "results": _with_urls(search_service.search(profile, query, limit=100, **_options(request, settings)))},
    )
