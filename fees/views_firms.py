"""Firm pages: the list, one firm (its groups and matters), and the new and edit forms."""
from django.views.decorators.http import require_GET

from fees import scope
from fees.decorators import fees_read_write, fees_reader, handle_fees_errors
from fees.pages import render_page
from fees.services import firms

STATUS_FILTERS = ("all", "active", "archived")


@fees_reader
@handle_fees_errors()
@require_GET
def firm_list(request):
    profile, _settings = scope.context(request)
    status = request.GET.get("status", "all")
    if status not in STATUS_FILTERS:
        status = "all"
    return render_page(
        request,
        "fees/firms.html",
        {"firm_rows": firms.list_firms(profile, status), "status": status, "status_filters": STATUS_FILTERS},
    )


@fees_read_write
@handle_fees_errors()
@require_GET
def firm_new(request):
    return render_page(request, "fees/firm_form.html", {"firm": None, "form": {"name": "", "notes": ""}})


@fees_reader
@handle_fees_errors()
@require_GET
def firm_detail(request, firm_id):
    profile, _settings = scope.context(request)
    detail = firms.get_firm(profile, firm_id)
    return render_page(
        request,
        "fees/firm_detail.html",
        {"firm": detail["firm"], "groups": detail["groups"], "matter_rows": detail["matters"]},
    )


@fees_read_write
@handle_fees_errors()
@require_GET
def firm_edit(request, firm_id):
    profile, _settings = scope.context(request)
    firm = firms.get_firm(profile, firm_id)["firm"]
    return render_page(
        request, "fees/firm_form.html", {"firm": firm, "form": {"name": firm.name, "notes": firm.notes}}
    )
