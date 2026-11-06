"""Matter pages: one matter (with its memos) and the new and edit forms."""
from django.views.decorators.http import require_GET

from fees import scope
from fees.decorators import fees_read_write, fees_reader, handle_fees_errors
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


def _form_page(request, matter, form):
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
        },
    )


@fees_read_write
@handle_fees_errors()
@require_GET
def matter_new(request):
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
@require_GET
def matter_edit(request, matter_id):
    profile, _settings = scope.context(request)
    matter = matters.get_matter(profile, matter_id)
    form = _form_values(matter)
    firm_id = int_or_none(request.GET.get("firm"))
    if firm_id is not None and firm_id != matter.firm_id:
        # Moving the matter to another firm: show that firm's groups.
        form["firm_id"] = firm_id
        form["group_id"] = ""
    return _form_page(request, matter, form)
