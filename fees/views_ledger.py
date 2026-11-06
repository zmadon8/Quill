"""Statement and Ledger pages for a firm or a matter."""
from django.views.decorators.http import require_safe

from fees import scope
from fees.decorators import fees_reader, handle_fees_errors
from fees.pages import render_page
from fees.services import firms, ledger, matters


def scope_for(profile, kind, object_id):
    """``(scope dict, owner object)``. The lookup raises ``*_NOT_FOUND`` (404) for another profile's id."""
    if kind == "firm":
        owner = firms.get_firm(profile, object_id)["firm"]
        return {"firm_id": owner.pk}, owner
    owner = matters.get_matter(profile, object_id)
    return {"matter_id": owner.pk}, owner


def _page(request, kind, object_id, what):
    profile, settings = scope.context(request)
    ledger_scope, owner = scope_for(profile, kind, object_id)
    if what == "statement":
        data = ledger.build_statement(profile, ledger_scope)
        return render_page(
            request,
            "fees/statement.html",
            {"kind": kind, "owner": owner, "statement": data, "money_unit": settings.money_unit},
        )
    rows = ledger.build_ledger(profile, ledger_scope)
    title = "Ledger" + ledger.scope_title(profile, ledger_scope)[0][len("Statement"):]
    return render_page(
        request,
        "fees/ledger.html",
        {"kind": kind, "owner": owner, "rows": rows, "title": title, "money_unit": settings.money_unit},
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
