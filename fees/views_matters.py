"""Matter pages: one matter (with its memos), the new and edit forms, and archive."""
from django.contrib import messages
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods, require_safe, require_POST

from fees import forms, scope
from fees.decorators import fees_editor, fees_read_write, fees_reader, handle_fees_errors
from fees.errors import FeesError
from fees.pages import int_or_none, render_page
from fees.services import clients, firms, matters, memo_lists, payments
from fees.services import settings as settings_service
from fees.services.matters import MEMO_DEFAULT_FIELDS


def _form_values(matter=None):
    values = {name: "" for name in MEMO_DEFAULT_FIELDS if name != "addressee_use_firm_name"}
    values.update(name="", firm_id="", group_id="", addressee_use_firm_name=False, client_id="", client_new="")
    if matter is not None:
        for name in MEMO_DEFAULT_FIELDS:
            values[name] = getattr(matter, name)
        values.update(name=matter.name, firm_id=matter.firm_id, group_id=matter.group_id, client_id=matter.client_id or "")
        if matter.addressee_use_firm_name:
            # Brought back by an older backup: show (and so save) the firm's name in the box, as there is no tick any more.
            values["addressee_line1"] = matter.firm.name
            values["addressee_use_firm_name"] = False
    return values


def _echo(post):
    values = {name: forms.posted_party_type(post, name) if name in forms.PARTY_TYPE_FIELDS else post.get(name, "") for name in _form_values()}
    values["addressee_use_firm_name"] = post.get("addressee_use_firm_name") == "1"
    values["firm_id"] = int_or_none(post.get("firm_id")) or ""
    values["group_id"] = int_or_none(post.get("group_id")) or ""
    values["client_id"] = int_or_none(post.get("client_id")) or ""
    return values


def _chosen_client(profile, post, firm_id):
    """The Client the form chose, as a client of the matter's firm ``firm_id`` (a typed new name wins over the list), or None."""
    return clients.resolve(profile, firm_id, int_or_none(post.get("client_id")), post.get("client_new", ""))


def _form_page(request, matter, form, errors=None, status=200):
    profile, _settings = scope.context(request)
    firm_id = int_or_none(form.get("firm_id"))
    groups = firms.get_firm(profile, firm_id)["groups"] if firm_id is not None else []
    return render_page(
        request,
        "fees/matter_form.html",
        {
            "matter": matter,
            "form": form,
            "firm_choices": firms.list_firms(profile),
            "group_choices": groups,
            "party_types": settings_service.party_types(profile),
            "client_choices": clients.choices_for_firm(profile, firm_id, int_or_none(form.get("client_id")) or (matter.client_id if matter else None)),
            "errors": errors or [],
        },
        status=status,
    )


def _failed(request, err, matter):
    if err.status == 404:
        raise Http404(err.message)
    return _form_page(request, matter, _echo(request.POST), errors=[err.message], status=err.status)


@fees_read_write
@handle_fees_errors()
@require_http_methods(["GET", "HEAD", "POST"])
def matter_new(request):
    profile, _settings = scope.context(request)
    if request.method == "POST":
        try:
            name, group_id, firm_id, defaults = forms.matter_data_from_post(request.POST)
            if firm_id is None:
                raise FeesError("INVALID_MATTER", "Choose a firm.")
            with transaction.atomic():   # a new client typed on a form that then fails is not kept
                client = _chosen_client(profile, request.POST, firm_id)
                matter = matters.create_matter(profile, firm_id, group_id, name, **defaults)
                clients.set_matter_client(profile, matter, client)
        except FeesError as err:
            return _failed(request, err, None)
        messages.success(request, f"Matter {matter.name} created.")
        return redirect("fees_matter_detail", matter_id=matter.pk)
    form = _form_values()
    # A new matter's Cause title starts as Settings > Memos > Caption, as a new memo's does.
    form["court_name"] = settings_service.get_settings(profile)["default_court_name"] or ""
    # No "use the firm name" tick on a new matter (owner round 2026-12): Addressee line 1 simply starts with the firm's name, to keep or change.
    form["addressee_use_firm_name"] = False
    firm_id = int_or_none(request.GET.get("firm"))
    if firm_id is not None:
        form["firm_id"] = firm_id
        form["addressee_line1"] = firms.get_firm(profile, firm_id)["firm"].name
        group_id = int_or_none(request.GET.get("group"))
        if group_id is not None and any(g.pk == group_id for g in firms.get_firm(profile, firm_id)["groups"]):
            form["group_id"] = group_id
    return _form_page(request, None, form)


def is_outstanding(item):
    """A memo with fees outstanding, as on the Outstanding page: finalised, not written off, not fully paid."""
    return not item["is_draft"] and not item["written_off"] and item["status"] == "Unpaid"


def matter_memo_items(profile, matter_id, outstanding_only=False):
    """The Matter page's memo rows (drafts too), or only the outstanding ones."""
    items = memo_lists.list_memos_for_matter(profile, matter_id)
    return [m for m in items if is_outstanding(m)] if outstanding_only else items


@fees_reader
@handle_fees_errors()
@require_safe
def matter_detail(request, matter_id):
    profile, settings = scope.context(request)
    matter = matters.get_matter(profile, matter_id)
    outstanding_only = request.GET.get("outstanding") == "1"
    items = matter_memo_items(profile, matter_id, outstanding_only)
    return render_page(
        request,
        "fees/matter_detail.html",
        {
            "matter": matter,
            "outstanding_only": outstanding_only,
            "items": items,
            "totals": memo_lists.footer_totals(items),
            "money_unit": settings.money_unit,
            "max_allocations": payments.MAX_ALLOCATIONS,
        },
    )


@fees_read_write
@handle_fees_errors()
@require_http_methods(["GET", "HEAD", "POST"])
def matter_edit(request, matter_id):
    profile, _settings = scope.context(request)
    matter = matters.get_matter(profile, matter_id)
    if request.method == "POST":
        try:
            name, group_id, firm_id, defaults = forms.matter_data_from_post(request.POST)
            with transaction.atomic():
                client = _chosen_client(profile, request.POST, firm_id if firm_id is not None else matter.firm_id)
                matter = matters.update_matter(
                    profile, matter_id, name=name, firm_id=firm_id, group_id=group_id, **defaults
                )
                clients.set_matter_client(profile, matter, client)
        except FeesError as err:
            return _failed(request, err, matter)
        messages.success(request, "Matter saved.")
        return redirect("fees_matter_detail", matter_id=matter.pk)
    form = _form_values(matter)
    firm_id = int_or_none(request.GET.get("firm"))
    if firm_id is not None and firm_id != matter.firm_id:
        # Moving the matter to another firm: show that firm's partners.
        form["firm_id"] = firm_id
        form["group_id"] = ""
    return _form_page(request, matter, form)


@fees_editor
@handle_fees_errors()
@require_POST
def matter_archive(request, matter_id):
    profile, _settings = scope.context(request)
    if request.POST.get("archive") == "0":
        matters.unarchive_matter(profile, matter_id)
        messages.success(request, "Matter made active.")
    else:
        matters.archive_matter(profile, matter_id)
        messages.success(request, "Matter archived.")
    return redirect("fees_matter_detail", matter_id=matter_id)
