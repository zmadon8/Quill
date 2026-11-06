"""Small helpers shared by the Fee Register views: rendering, JSON, file responses and query-string filters.

Nothing here touches the services' data rules. A view parses the request, calls a service and hands the
result to one of these helpers.
"""
from django.core.serializers.json import DjangoJSONEncoder
from django.http import FileResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse

from accounts.models import ROLE_EDITOR
from accounts.profiles import request_memberships, request_role
from accounts.suite import KEY_FEES
from fees import scope
from fees.exports.filenames import content_disposition

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TEXT_TYPE = "text/plain; charset=utf-8"

#: The ``default_tab`` setting value to the URL name of that page.
TAB_URL_NAMES = {
    "memos": "fees_memos",
    "dashboard": "fees_dashboard",
    "statistics": "fees_statistics",
    "firms": "fees_firms",
    "feebook": "fees_feebook",
    "outstanding": "fees_outstanding",
    "settings": "fees_settings",
}

#: Header entries: (key, label, url name, url-name prefixes that mark it current).
_NAV = (
    ("dashboard", "Dashboard", "fees_dashboard", ("fees_dashboard",)),
    ("statistics", "Statistics", "fees_statistics", ("fees_statistics",)),
    ("memos", "Memos", "fees_memos", ("fees_memo", "fees_payment")),
    ("firms", "Firms", "fees_firms", ("fees_firm", "fees_matter")),
    ("feebook", "Feebook", "fees_feebook", ("fees_feebook",)),
    ("outstanding", "Outstanding", "fees_outstanding", ("fees_outstanding",)),
    ("settings", "Settings", "fees_settings", ("fees_settings", "fees_bank", "fees_template", "fees_signature",
                                               "fees_filename", "fees_backup", "fees_import")),
)


def nav_for(request, settings):
    """The header entries for this page; Statistics is left out when it is switched off in Settings."""
    match = getattr(request, "resolver_match", None)
    current = (match.url_name or "") if match else ""
    items = []
    for key, label, url_name, prefixes in _NAV:
        if key == "statistics" and settings is not None and not settings.statistics_enabled:
            continue
        items.append({"url": reverse(url_name), "name": label, "on": current.startswith(prefixes)})
    return items


def render_page(request, template, context=None, status=200):
    """Render a Fee Register page with the profile, settings, role flag and header entries added."""
    profile, settings = scope.context(request)
    base = {
        "fees_profile": profile,
        "fees_settings": settings,
        # Show status markers (Settings); read once per request from the cached settings, so no extra query.
        "fees_dots": settings is None or settings.show_status_dots,
        "can_edit": request_role(request, KEY_FEES) == ROLE_EDITOR,
        "fees_nav": nav_for(request, settings),
        # The user's other Fee Register profiles, for the header switcher (memberships are cached, so no query).
        "fees_other_profiles": [m.profile for m in request_memberships(request, KEY_FEES)[1:]],
    }
    base.update(context or {})
    return render(request, template, base, status=status)


def json_ok(data=None, status=200, **extra):
    """``{"ok": true, ...}`` as JSON. ``data`` (a dict) is merged first, then ``extra``."""
    body = {"ok": True}
    if data:
        body.update(data)
    body.update(extra)
    return JsonResponse(body, status=status, encoder=DjangoJSONEncoder)


def file_response(result, content_type):
    """A download for a ``(file_name, file object)`` export result. The file closes when sent."""
    file_name, fileobj = result
    response = FileResponse(fileobj, as_attachment=False, content_type=content_type)
    response["Content-Disposition"] = content_disposition(file_name)
    return response


def bytes_response(file_name, data, content_type):
    """A download for bytes already in memory (the template and the signature image)."""
    from django.http import HttpResponse

    response = HttpResponse(data, content_type=content_type)
    response["Content-Disposition"] = content_disposition(file_name)
    return response


# ---------------------------------------------------------------------------
# Query-string parsing
# ---------------------------------------------------------------------------


def int_or_none(value):
    """``int(value)`` for a plain digit string, else None."""
    text = str(value).strip() if value is not None else ""
    return int(text) if text.isdigit() else None


def flag(value):
    """True for ``1``, ``true``, ``on`` or ``yes`` (any case)."""
    return str(value or "").strip().lower() in ("1", "true", "on", "yes")


def int_list(value):
    """``"1,2,x,3"`` -> ``[1, 2, 3]``."""
    return [n for n in (int_or_none(part) for part in str(value or "").split(",")) if n is not None]


def memo_filters(query):
    """Memo list filters from a query string: ``fy``, ``firm``, ``group``, ``matter``, ``unpaid``."""
    filters = {}
    if query.get("fy"):
        filters["financial_year"] = query["fy"].strip()
    for key, name in (("firm", "firm_id"), ("group", "group_id"), ("matter", "matter_id")):
        number = int_or_none(query.get(key))
        if number is not None:
            filters[name] = number
    if flag(query.get("unpaid")):
        filters["unpaid_only"] = True
    return filters


def feebook_filters(query):
    """Feebook filters: ``fy``, ``firm``, ``group``, ``bank``, ``unaccounted``."""
    filters = {}
    if query.get("fy"):
        filters["financial_year"] = query["fy"].strip()
    for key, name in (("firm", "firm_id"), ("group", "group_id"), ("bank", "bank_account_id")):
        number = int_or_none(query.get(key))
        if number is not None:
            filters[name] = number
    if flag(query.get("unaccounted")):
        filters["unaccounted_only"] = True
    return filters


def outstanding_filters(query):
    """Outstanding filters: ``firm``, ``group``, ``matter``, ``written_off``, ``overdue``."""
    filters = {}
    for key, name in (("firm", "firm_id"), ("group", "group_id"), ("matter", "matter_id")):
        number = int_or_none(query.get(key))
        if number is not None:
            filters[name] = number
    if flag(query.get("written_off")):
        filters["include_written_off"] = True
    if flag(query.get("overdue")):
        filters["overdue_only"] = True
    return filters


def page_number(query):
    """The ``page`` query value as an int of at least 1."""
    return max(1, int_or_none(query.get("page")) or 1)
