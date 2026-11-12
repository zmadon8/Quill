"""Statement and Ledger pages for a firm (or one of its groups, ``?group=``) or a matter."""
from django.http import Http404
from django.views.decorators.http import require_safe

from fees import scope
from fees.decorators import fees_reader, handle_fees_errors
from fees.pages import int_or_none, render_page
from fees.services import firms, ledger, matters


def scope_for(profile, kind, object_id, group_id=None):
    """``(scope dict, owner object)``. The lookup raises ``*_NOT_FOUND`` (404) for another profile's id.

    ``group_id`` (a firm's group) narrows a firm scope to that group; a group of another firm is a 404.
    """
    if kind == "firm":
        detail = firms.get_firm(profile, object_id)
        owner = detail["firm"]
        if group_id is not None:
            if not any(group.pk == group_id for group in detail["groups"]):
                raise Http404("Group not found")
            return {"firm_id": owner.pk, "group_id": group_id}, owner
        return {"firm_id": owner.pk}, owner
    owner = matters.get_matter(profile, object_id)
    return {"matter_id": owner.pk}, owner


def group_param(request):
    """The ``group`` query value as an int, or None."""
    return int_or_none(request.GET.get("group"))


def _page(request, kind, object_id, what):
    profile, settings = scope.context(request)
    group_id = group_param(request) if kind == "firm" else None
    ledger_scope, owner = scope_for(profile, kind, object_id, group_id)
    rows = ledger.build_ledger(profile, ledger_scope)
    title = ledger.scope_title(profile, ledger_scope)[0]
    if what == "ledger":
        title = "Ledger" + title[len("Statement"):]
    return render_page(
        request,
        "fees/statement.html" if what == "statement" else "fees/ledger.html",
        {
            "kind": kind,
            "owner": owner,
            "group_id": group_id,
            "rows": rows,
            "totals": ledger.ledger_totals(rows),
            "title": title,
            "money_unit": settings.money_unit,
        },
    )


@fees_reader
@handle_fees_errors()
@require_safe
def firm_statement(request, firm_id):
    return _page(request, "firm", firm_id, "statement")


@fees_reader
@handle_fees_errors()
@require_safe
def firm_ledger(request, firm_id):
    return _page(request, "firm", firm_id, "ledger")


@fees_reader
@handle_fees_errors()
@require_safe
def matter_statement(request, matter_id):
    return _page(request, "matter", matter_id, "statement")


@fees_reader
@handle_fees_errors()
@require_safe
def matter_ledger(request, matter_id):
    return _page(request, "matter", matter_id, "ledger")
