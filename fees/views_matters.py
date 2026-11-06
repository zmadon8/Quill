"""Matter pages: one matter (with its memos), the new and edit forms, and archive."""
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from fees import forms, scope
from fees.decorators import fees_editor, fees_read_write, fees_reader, handle_fees_errors
from fees.errors import FeesError
from fees.pages import int_or_none, render_page
from fees.services import firms, matters, memo_lists
from fees.services.matters import MEMO_DEFAULT_FIELDS


def _form_values(matter=None):
    values = {name: "" for name in MEMO_DEFAULT_FIELDS if name != "addressee_use_firm_name"}
    values.update(name="", firm_id="", group_id="", addressee_use_firm_name=False)
    if matter is not None:
        for name in MEMO_DEFAULT_FIELDS:
            values[name] = getattr(matter, name)
        values.update(name=matter.name, firm_id=matter.firm_id, group_id=matter.group_id)
    return values


def _echo(post):
    values = {name: post.get(name, "") for name in _form_values()}
    values["addressee_use_firm_name"] = post.get("addressee_use_firm_name") == "1"
    values["firm_id"] = int_or_none(post.get("firm_id")) or ""
    values["group_id"] = int_or_none(post.get("group_id")) or ""
    return values


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
@require_http_methods(["GET", "POST"])
def matter_new(request):
    profile, _settings = scope.context(request)
    if request.method == "POST":
        try:
            name, group_id, firm_id, defaults = forms.matter_data_from_post(request.POST)
            if firm_id is None or group_id is None:
                raise FeesError("INVALID_MATTER", "Choose a firm and a group.")
            matter = matters.create_matter(profile, firm_id, group_id, name, **defaults)
        except FeesError as err:
            return _failed(request, err, None)
        messages.success(request, f"Matter {matter.name} created.")
        return redirect("fees_matter_detail", matter_id=matter.pk)
    form = _form_values()
    firm_id = int_or_none(request.GET.get("firm"))
    if firm_id is not None:
        form["firm_id"] = firm_id
    return _form_page(request, None, form)


@fees_reader
@handle_fees_errors()
@require_GET
def matter_detail(request, matter_id):
    profile, settings = scope.context(request)
    matter = matters.get_matter(profile, matter_id)
    items = memo_lists.list_memos_for_matter(profile, matter_id)
    return render_page(
        request,
        "fees/matter_detail.html",
        {
            "matter": matter,
            "items": items,
            "totals": memo_lists.footer_totals(items),
            "money_unit": settings.money_unit,
        },
    )


@fees_read_write
@handle_fees_errors()
@require_http_methods(["GET", "POST"])
def matter_edit(request, matter_id):
    profile, _settings = scope.context(request)
    matter = matters.get_matter(profile, matter_id)
    if request.method == "POST":
        try:
            name, group_id, firm_id, defaults = forms.matter_data_from_post(request.POST)
            matter = matters.update_matter(
                profile, matter_id, name=name, firm_id=firm_id, group_id=group_id, **defaults
            )
        except FeesError as err:
            return _failed(request, err, matter)
        messages.success(request, "Matter saved.")
        return redirect("fees_matter_detail", matter_id=matter.pk)
    form = _form_values(matter)
    firm_id = int_or_none(request.GET.get("firm"))
    if firm_id is not None and firm_id != matter.firm_id:
        # Moving the matter to another firm: show that firm's groups.
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
