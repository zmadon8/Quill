"""Firm pages: the list, one firm (its partners and matters), the new and edit forms, status and partners; and the Clients pages."""
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods, require_safe, require_POST

from fees import forms, scope
from fees.decorators import fees_editor, fees_read_write, fees_reader, handle_fees_errors
from fees.errors import FeesError
from fees.models import Firm, Matter
from fees.pages import render_page
from fees.services import clients, firms

STATUS_FILTERS = ("all", "active", "archived")


def default_list_filter(settings):
    """The Firms / matters default when the URL names no filter: the Settings choice (all or active)."""
    return "active" if getattr(settings, "list_default_filter", "all") == "active" else "all"


@fees_reader
@handle_fees_errors()
@require_safe
def firm_list(request):
    profile, settings = scope.context(request)
    status = request.GET.get("status")
    if status not in STATUS_FILTERS:
        status = default_list_filter(settings)
    return render_page(
        request,
        "fees/firms.html",
        {"firm_rows": firms.list_firms(profile, status), "status": status, "status_filters": STATUS_FILTERS},
    )


def _form_page(request, firm, form, errors=None, status=200):
    return render_page(request, "fees/firm_form.html", {"firm": firm, "form": form, "errors": errors or []}, status=status)


def _failed(request, err, firm, form):
    if err.status == 404:
        raise Http404(err.message)
    return _form_page(request, firm, form, errors=[err.message], status=err.status)


@fees_read_write
@handle_fees_errors()
@require_http_methods(["GET", "HEAD", "POST"])
def firm_new(request):
    if request.method == "POST":
        profile, _settings = scope.context(request)
        form = {"name": request.POST.get("name", ""), "notes": ""}
        try:
            firm = firms.create_firm(profile, forms.clean_text(request.POST, "name", Firm, "Name"))
        except FeesError as err:
            return _failed(request, err, None, form)
        messages.success(request, f"Firm {firm.name} created.")
        return redirect("fees_firm_detail", firm_id=firm.pk)
    return _form_page(request, None, {"name": "", "notes": ""})


@fees_reader
@handle_fees_errors()
@require_safe
def firm_detail(request, firm_id):
    profile, settings = scope.context(request)
    detail = firms.get_firm(profile, firm_id)
    shown = request.GET.get("matters")
    if shown not in ("all", "active"):
        shown = default_list_filter(settings)
    rows = detail["matters"]
    if shown == "active":
        rows = [row for row in rows if not row["matter"].is_archived]
    return render_page(
        request,
        "fees/firm_detail.html",
        {
            "firm": detail["firm"],
            "groups": detail["groups"],
            "matter_rows": rows,
            "matters_shown": shown,
            "matters_filters": ("all", "active"),
        },
    )


@fees_read_write
@handle_fees_errors()
@require_http_methods(["GET", "HEAD", "POST"])
def firm_edit(request, firm_id):
    profile, _settings = scope.context(request)
    firm = firms.get_firm(profile, firm_id)["firm"]
    if request.method == "POST":
        form = {"name": request.POST.get("name", ""), "notes": request.POST.get("notes", "")}
        try:
            firm = firms.update_firm(
                profile,
                firm_id,
                name=forms.clean_text(request.POST, "name", Firm, "Name"),
                notes=forms.clean_text(request.POST, "notes", Firm, "Notes"),
            )
        except FeesError as err:
            return _failed(request, err, firm, form)
        messages.success(request, "Firm saved.")
        return redirect("fees_firm_detail", firm_id=firm.pk)
    return _form_page(request, firm, {"name": firm.name, "notes": firm.notes})


@fees_editor
@handle_fees_errors()
@require_POST
def firm_status(request, firm_id):
    profile, _settings = scope.context(request)
    firms.get_firm(profile, firm_id)  # another profile's firm is a 404 before the status check
    status = request.POST.get("status", "")
    if status not in ("active", "archived"):
        raise FeesError("INVALID_FIRM_STATUS", "Choose active or archived.")
    firms.set_firm_status(profile, firm_id, status)
    messages.success(request, "Firm archived." if status == "archived" else "Firm made active.")
    return redirect("fees_firm_detail", firm_id=firm_id)


def _group_of_firm(profile, firm_id, group_id):
    """The group, which must belong to this firm (any other group is a 404)."""
    for group in firms.get_firm(profile, firm_id)["groups"]:
        if group.pk == group_id:
            return group
    raise Http404("Partner not found")


@fees_reader
@handle_fees_errors()
@require_safe
def group_detail(request, firm_id, group_id):
    """One group of a firm: the firm page's details and buttons, limited to this group's matters."""
    profile, settings = scope.context(request)
    detail = firms.get_firm(profile, firm_id)
    group = next((g for g in detail["groups"] if g.pk == group_id), None)
    if group is None:
        raise Http404("Partner not found")
    shown = request.GET.get("matters")
    if shown not in ("all", "active"):
        shown = default_list_filter(settings)
    rows = [row for row in detail["matters"] if row["matter"].group_id == group_id]
    if shown == "active":
        rows = [row for row in rows if not row["matter"].is_archived]
    return render_page(
        request,
        "fees/group_detail.html",
        {
            "firm": detail["firm"],
            "group": group,
            "matter_rows": rows,
            "matters_shown": shown,
            "matters_filters": ("all", "active"),
        },
    )


@fees_editor
@handle_fees_errors()
@require_POST
def group_add(request, firm_id):
    profile, _settings = scope.context(request)
    firms.add_group(profile, firm_id, request.POST.get("name", ""))
    messages.success(request, "Partner added.")
    return redirect("fees_firm_detail", firm_id=firm_id)


@fees_editor
@handle_fees_errors()
@require_POST
def group_rename(request, firm_id, group_id):
    profile, _settings = scope.context(request)
    _group_of_firm(profile, firm_id, group_id)
    firms.update_group(profile, group_id, request.POST.get("name", ""))
    messages.success(request, "Partner renamed.")
    return redirect("fees_firm_detail", firm_id=firm_id)


@fees_editor
@handle_fees_errors()
@require_POST
def group_remove(request, firm_id, group_id):
    profile, _settings = scope.context(request)
    _group_of_firm(profile, firm_id, group_id)
    firms.remove_group(profile, firm_id, group_id)
    messages.success(request, "Partner removed.")
    return redirect("fees_firm_detail", firm_id=firm_id)


# ---------------------------------------------------------------------------
# Clients (owner round 2026-11)
# ---------------------------------------------------------------------------

@fees_reader
@handle_fees_errors()
@require_safe
def client_list(request):
    profile, _settings = scope.context(request)
    return render_page(request, "fees/clients.html", {"client_rows": clients.list_clients(profile)})


@fees_editor
@handle_fees_errors()
@require_POST
def client_add(request):
    profile, _settings = scope.context(request)
    client = clients.create_client(profile, request.POST.get("name", ""))
    messages.success(request, f"Client {client.name} added.")
    return redirect("fees_firms_clients")


@fees_reader
@handle_fees_errors()
@require_safe
def client_detail(request, client_id):
    """One client: its matters (any firm), with links to the memos, the outstanding fees and the Feebook narrowed to it."""
    profile, settings = scope.context(request)
    client = next((c for c in clients.list_clients(profile) if c.pk == client_id), None)
    if client is None:
        raise Http404("Client not found")
    shown = request.GET.get("matters")
    if shown not in ("all", "active"):
        shown = default_list_filter(settings)
    rows = Matter.objects.filter(profile=profile, client_id=client_id).select_related("firm", "group").order_by("firm__name", "name")
    if shown == "active":
        rows = rows.filter(is_archived=False)
    return render_page(request, "fees/client_detail.html", {
        "client": client, "matter_rows": list(rows), "matters_shown": shown, "matters_filters": ("all", "active"),
    })


@fees_editor
@handle_fees_errors()
@require_POST
def client_rename(request, client_id):
    profile, _settings = scope.context(request)
    clients.rename_client(profile, client_id, request.POST.get("name", ""))
    messages.success(request, "Client renamed.")
    return redirect("fees_firms_client_detail", client_id=client_id)


@fees_editor
@handle_fees_errors()
@require_POST
def client_delete(request, client_id):
    profile, _settings = scope.context(request)
    count = clients.delete_client(profile, client_id)
    messages.success(request, "Client deleted." + (f" {count} matter{'s' if count != 1 else ''} now ha{'ve' if count != 1 else 's'} no client." if count else ""))
    return redirect("fees_firms_clients")

