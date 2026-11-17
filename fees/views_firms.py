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


#: The firm page's matter filter (owner round 2026-11: Archived Only added).
MATTER_FILTERS = ("all", "active", "archived")


def matters_shown(request, settings):
    """``?matters=`` (all, active or archived), else the Settings default."""
    shown = request.GET.get("matters")
    return shown if shown in MATTER_FILTERS else default_list_filter(settings)


def filter_matter_rows(rows, shown):
    if shown == "active":
        return [row for row in rows if not row["matter"].is_archived]
    if shown == "archived":
        return [row for row in rows if row["matter"].is_archived]
    return rows


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


#: How the firm page groups its matters (owner round 2026-12): under each Partner, or under each Client.
BY_CHOICES = ("partner", "client")


def _client_sections(rows):
    """``[{"title", "rows"}]`` for the Client-wise view: one card per client by name, matters with no client last."""
    by_client = {}
    for row in rows:
        by_client.setdefault(row["matter"].client_id, []).append(row)
    named = sorted((r for k, r in by_client.items() if k is not None), key=lambda r: r[0]["matter"].client.name.lower())
    sections = [{"title": r[0]["matter"].client.name, "rows": r} for r in named]
    if None in by_client:
        sections.append({"title": "No client", "rows": by_client[None]})
    return sections


def _partner_sections(groups, rows):
    sections = [{"title": g.name, "rows": [r for r in rows if r["matter"].group_id == g.pk]} for g in groups]
    loose = [r for r in rows if r["matter"].group_id is None]
    if loose:
        sections.append({"title": "No partner", "rows": loose})
    return sections


@fees_reader
@handle_fees_errors()
@require_safe
def firm_detail(request, firm_id):
    profile, settings = scope.context(request)
    detail = firms.get_firm(profile, firm_id)
    shown = matters_shown(request, settings)
    by = request.GET.get("by")
    if by not in BY_CHOICES:
        by = "partner"
    rows = filter_matter_rows(detail["matters"], shown)
    return render_page(
        request,
        "fees/firm_detail.html",
        {
            "firm": detail["firm"],
            "sections": _client_sections(rows) if by == "client" else _partner_sections(detail["groups"], rows),
            "matter_rows": rows,
            "matters_shown": shown,
            "matters_filters": MATTER_FILTERS,
            "by": by,
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
    shown = matters_shown(request, settings)
    rows = filter_matter_rows([row for row in detail["matters"] if row["matter"].group_id == group_id], shown)
    return render_page(
        request,
        "fees/group_detail.html",
        {
            "firm": detail["firm"],
            "group": group,
            "matter_rows": rows,
            "matters_shown": shown,
            "matters_filters": MATTER_FILTERS,
        },
    )


@fees_editor
@handle_fees_errors()
@require_POST
def group_add(request, firm_id):
    profile, _settings = scope.context(request)
    firms.add_group(profile, firm_id, request.POST.get("name", ""))
    messages.success(request, "Partner added.")
    return redirect("fees_firm_partners", firm_id=firm_id)


@fees_editor
@handle_fees_errors()
@require_POST
def group_rename(request, firm_id, group_id):
    profile, _settings = scope.context(request)
    _group_of_firm(profile, firm_id, group_id)
    firms.update_group(profile, group_id, request.POST.get("name", ""))
    messages.success(request, "Partner renamed.")
    return redirect("fees_group_detail", firm_id=firm_id, group_id=group_id)


@fees_editor
@handle_fees_errors()
@require_POST
def group_remove(request, firm_id, group_id):
    profile, _settings = scope.context(request)
    _group_of_firm(profile, firm_id, group_id)
    moved = firms.remove_group(profile, firm_id, group_id)
    messages.success(request, "Partner removed." + (f" {moved} matter{'s' if moved != 1 else ''} now ha{'ve' if moved != 1 else 's'} no partner." if moved else ""))
    return redirect("fees_firm_partners", firm_id=firm_id)


@fees_reader
@handle_fees_errors()
@require_safe
def firm_partners(request, firm_id):
    """Every partner of one firm, each linking to its matters; an Editor adds, renames (on the partner's page) and removes them."""
    profile, _settings = scope.context(request)
    detail = firms.get_firm(profile, firm_id)
    counts = {}
    for row in detail["matters"]:
        counts[row["matter"].group_id] = counts.get(row["matter"].group_id, 0) + 1
    return render_page(request, "fees/firm_partners.html", {
        "firm": detail["firm"],
        "partner_rows": [{"group": g, "matter_count": counts.get(g.pk, 0)} for g in detail["groups"]],
        "no_partner_count": counts.get(None, 0),
    })


@fees_reader
@handle_fees_errors()
@require_safe
def firm_clients(request, firm_id):
    """Every client of one firm (the clients of its matters), each linking to its matters in this firm; an Editor renames or removes them."""
    profile, _settings = scope.context(request)
    firm = firms.get_firm(profile, firm_id)["firm"]
    return render_page(request, "fees/firm_clients.html", {
        "firm": firm,
        "client_rows": clients.list_clients_for_firm(profile, firm_id),
        "no_client_count": Matter.objects.filter(profile=profile, firm_id=firm_id, client__isnull=True).count(),
    })


def _client_of_firm(profile, firm_id, client_id):
    """``(firm, client)``: the client may be any client of this profile (one with no matter in this firm shows an empty list)."""
    firm = firms.get_firm(profile, firm_id)["firm"]  # another profile's firm is a 404 first
    client = next((c for c in clients.list_clients(profile) if c.pk == client_id), None)
    if client is None:
        raise Http404("Client not found")
    return firm, client


@fees_reader
@handle_fees_errors()
@require_safe
def firm_client_detail(request, firm_id, client_id):
    """One client of a firm: its matters in this firm only (the firm page's matter list, limited to this client)."""
    profile, settings = scope.context(request)
    firm, client = _client_of_firm(profile, firm_id, client_id)
    shown = matters_shown(request, settings)
    rows = Matter.objects.filter(profile=profile, firm_id=firm_id, client_id=client_id).select_related("group").order_by("name")
    if shown != "all":
        rows = rows.filter(is_archived=(shown == "archived"))
    return render_page(request, "fees/firm_client_detail.html", {
        "firm": firm, "client": client, "matter_rows": list(rows), "matters_shown": shown, "matters_filters": MATTER_FILTERS,
    })


@fees_editor
@handle_fees_errors()
@require_POST
def firm_client_rename(request, firm_id, client_id):
    profile, _settings = scope.context(request)
    _client_of_firm(profile, firm_id, client_id)
    target = clients.rename_for_firm(profile, firm_id, client_id, request.POST.get("name", ""))
    messages.success(request, "Client renamed.")
    return redirect("fees_firm_client_detail", firm_id=firm_id, client_id=target.pk)


@fees_editor
@handle_fees_errors()
@require_POST
def firm_client_remove(request, firm_id, client_id):
    profile, _settings = scope.context(request)
    _client_of_firm(profile, firm_id, client_id)
    count = clients.clear_for_firm(profile, firm_id, client_id)
    messages.success(request, "Client removed." + (f" {count} matter{'s' if count != 1 else ''} now ha{'ve' if count != 1 else 's'} no client." if count else ""))
    return redirect("fees_firm_clients", firm_id=firm_id)


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
    shown = matters_shown(request, settings)
    rows = Matter.objects.filter(profile=profile, client_id=client_id).select_related("firm", "group").order_by("firm__name", "name")
    if shown != "all":
        rows = rows.filter(is_archived=(shown == "archived"))
    return render_page(request, "fees/client_detail.html", {
        "client": client, "matter_rows": list(rows), "matters_shown": shown, "matters_filters": MATTER_FILTERS,
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

