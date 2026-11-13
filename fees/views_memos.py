"""Memo pages: the list, drafts, one memo, the new, edit and based-on forms, and the memo write actions."""
from django.contrib import messages
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods, require_safe, require_POST

from fees import forms, scope
from fees.decorators import fees_editor, fees_read_write, fees_reader, handle_fees_errors
from fees.errors import FeesError
from fees.pages import json_ok, memo_filters, page_number, render_page
from fees.services import firms as firms_service
from fees.services import filter_options, fy_options, matters, memo_fees, memo_lists, memos, payments, prefs
from fees.services.fees_in_words import fees_in_words
from fees.services import settings as settings_service
from fees.services import word_template
from fees.services.financial_year import current_financial_year

#: Every input name on the memo form (used to show back what the user typed after a failed save).
FORM_FIELDS = (
    ("date", "matter_id", "custom_memo_number")
    + forms.MEMO_TEXT_FIELDS
    + forms.MEMO_COUNT_FIELDS
    + forms.MEMO_RATE_FIELDS
    + forms.MEMO_CUSTOM_FIELDS
)


def _list_page(request, draft_mode, template):
    profile, settings = scope.context(request)
    current = current_financial_year()
    filters = memo_filters(request.GET, current)
    options = filter_options.memo_options(profile, filters, draft_mode)
    if "fy" not in request.GET:
        # No year in the link: the current year, or the newest year with rows when the current year has none.
        chosen = filter_options.default_year(options["years"], current)
        if chosen != filters.get("financial_year"):
            filters = {k: v for k, v in filters.items() if k != "financial_year"}
            if chosen:
                filters["financial_year"] = chosen
            options = filter_options.memo_options(profile, filters, draft_mode)
    items = memo_lists.list_memos(profile, filters, draft_mode=draft_mode)
    page_items, meta = memo_lists.paginate(
        items, page_number(request.GET), memo_lists.page_size_for(prefs.personal_items_per_page(profile, request.user, settings))
    )
    return render_page(
        request,
        template,
        {
            "items": page_items,
            "meta": meta,
            "totals": memo_lists.footer_totals(items),
            "filters": filters,
            "firm_choices": options["firms"],
            "fy_options": fy_options.financial_year_options(
                profile, settings.memos_start_year, filters.get("financial_year"), only_years=options["years"]
            ),
            "money_unit": settings.money_unit,
            "query_string": _without_page(request, filters),
        },
    )


def _without_page(request, filters):
    """The query string for the pager and the Export link; the financial year shown is carried even when defaulted."""
    query = request.GET.copy()
    query.pop("page", None)
    if "fy" not in query and filters.get("financial_year"):
        query["fy"] = filters["financial_year"]
    return query.urlencode()


@fees_reader
@handle_fees_errors()
@require_safe
def memo_list(request):
    return _list_page(request, "exclude_drafts", "fees/memos.html")


@fees_reader
@handle_fees_errors()
@require_safe
def draft_list(request):
    return _list_page(request, "drafts_only", "fees/drafts.html")


@fees_reader
@handle_fees_errors()
@require_safe
def memo_detail(request, memo_id):
    profile, settings = scope.context(request)
    memo = memos.get_memo(profile, memo_id)
    return render_page(
        request,
        "fees/memo_detail.html",
        {
            "memo": memo,
            "payments": payments.list_payments_for_memo(profile, memo_id),
            "money_unit": settings.money_unit,
        },
    )


def _flag(value):
    return str(value or "").strip().lower() in ("1", "true", "on", "yes")


def _matter_groups(profile, firm_id, show_archived):
    """The matters of one firm for the picker as ``[{"name": group name, "matters": [...]}]`` (active only unless ``show_archived``)."""
    if not firm_id:
        return []
    groups = {}
    for matter in matters.list_matters(profile, firm_id=firm_id, status_filter="all" if show_archived else "active"):
        groups.setdefault(matter.group.name, []).append(matter)
    return [{"name": name, "matters": rows} for name, rows in groups.items()]


def _picker(profile, matter_id="", firm_id="", show_archived=False):
    """What the single Firm then Matter picker shows. The matter chosen (posted again or linked as ``?matter=``) fixes the firm; a chosen
    archived firm or matter switches "Show archived" on so that it is still in the lists. A matter that is not this profile's is ignored."""
    chosen = None
    if str(matter_id).isdigit():
        chosen = matters.list_matters(profile).filter(pk=int(matter_id)).first()
    if chosen is not None:
        firm_id = chosen.firm_id
    firm_id = int(firm_id) if str(firm_id).isdigit() else None
    firm_rows = list(firms_service.list_firms(profile, status_filter="all"))
    if firm_id not in {f.pk for f in firm_rows}:
        firm_id = None
    selected = next((f for f in firm_rows if f.pk == firm_id), None)
    show_archived = show_archived or bool(selected and selected.status == "archived") or bool(chosen and chosen.is_archived)
    return {
        "chosen": chosen,
        "firm_id": firm_id,
        "show_archived": show_archived,
        "firms": [f for f in firm_rows if show_archived or f.status != "archived"],
        "matter_groups": _matter_groups(profile, firm_id, show_archived),
    }


def _form_page(request, form, memo=None, based_on=None, errors=None, status=200):
    profile, _settings = scope.context(request)
    picker = None
    if memo is None:
        picker = _picker(profile, form.get("matter_id", ""), request.GET.get("firm", ""), _flag(request.GET.get("archived")))
    return render_page(
        request,
        "fees/memo_form.html",
        {
            "form": form,
            "memo": memo,
            "based_on": based_on,
            "picker": picker,
            "has_signature": word_template.has_signature(profile),
            "errors": errors or [],
        },
        status=status,
    )


def _failed(request, err, form, memo=None, based_on=None):
    """Show the form again with the error and what the user typed. A missing record is still a 404."""
    if err.status == 404:
        raise Http404(err.message)
    return _form_page(request, form, memo=memo, based_on=based_on, errors=[err.message], status=err.status)


def _saved(request, memo):
    messages.success(request, "Draft saved." if memo.is_draft else f"Memo {memo.memo_number} saved.")
    response = redirect("fees_memo_detail", memo_id=memo.pk)
    if request.POST.get("action") == "save_export" and not memo.is_draft:
        response["Location"] += "?export=word"  # the memo page starts the Word download
    return response


def _create(request, based_on=None):
    profile, _settings = scope.context(request)
    form = forms.echo_memo_form(request.POST, FORM_FIELDS)
    try:
        data = forms.memo_data_from_post(request.POST)
        if data["matter_id"] is None:
            raise FeesError("INVALID_MEMO", "Choose a matter.")
        firm_id = (request.POST.get("firm_id") or "").strip()
        if firm_id and not matters.list_matters(profile, firm_id=int(firm_id) if firm_id.isdigit() else -1).filter(pk=data["matter_id"]).exists():
            raise FeesError("INVALID_MEMO", "That matter does not belong to the chosen firm.")
        memo = memos.create_memo(profile, data, is_draft=request.POST.get("action") == "draft")
    except FeesError as err:
        return _failed(request, err, form, based_on=based_on)
    return _saved(request, memo)


@fees_read_write
@handle_fees_errors()
@require_http_methods(["GET", "HEAD", "POST"])
def memo_new(request):
    if request.method == "POST":
        return _create(request)
    profile, _settings = scope.context(request)
    config = settings_service.get_settings(profile)
    form = forms.blank_memo_form(config)
    matter_id = request.GET.get("matter", "").strip()
    if matter_id.isdigit():
        matter = matters.get_matter(profile, int(matter_id))
        firm_id = request.GET.get("firm", "").strip()
        # The picker's own form sends the firm and the matter it last showed: a matter of another firm is left out (the firm was just changed).
        if not firm_id.isdigit() or int(firm_id) == matter.firm_id:
            form = forms.apply_matter_defaults(form, matter)
    return _form_page(request, form)


@fees_reader
@handle_fees_errors(json=True)
@require_safe
def memo_picker(request):
    """JSON for the New Memo picker: the firms (active, or all with ``archived=1``) and, for ``firm=ID``, that firm's matters by group."""
    profile, _settings = scope.context(request)
    picker = _picker(profile, "", request.GET.get("firm", ""), _flag(request.GET.get("archived")))
    return json_ok({
        "show_archived": picker["show_archived"],
        "firm_id": picker["firm_id"],
        "firms": [{"id": f.pk, "name": f.name, "archived": f.status == "archived"} for f in picker["firms"]],
        "groups": [
            {"name": g["name"], "matters": [{"id": m.pk, "name": m.name, "archived": m.is_archived} for m in g["matters"]]}
            for g in picker["matter_groups"]
        ],
    })


@fees_reader
@handle_fees_errors(json=True)
@require_safe
def memo_matter_defaults(request):
    """JSON: the memo defaults of one matter (``?matter=ID``) as ``{field name: text}``, only the fields the matter fills. Reads only."""
    profile, _settings = scope.context(request)
    matter_id = request.GET.get("matter", "").strip()
    if not matter_id.isdigit():
        raise FeesError("INVALID_MEMO", "Choose a matter.")
    matter = matters.get_matter(profile, int(matter_id))   # another profile's matter is a 404
    values = forms.apply_matter_defaults({}, matter)
    values.pop("matter_id", None)
    return json_ok({"matter_id": matter.pk, "firm_id": matter.firm_id, "archived": matter.is_archived, "fields": values})


@fees_read_write
@handle_fees_errors()
@require_http_methods(["GET", "HEAD", "POST"])
def memo_edit(request, memo_id):
    profile, _settings = scope.context(request)
    detail = memos.get_memo(profile, memo_id)
    if request.method == "GET":
        return _form_page(request, forms.memo_form_from_detail(detail), memo=detail)
    form = forms.echo_memo_form(request.POST, FORM_FIELDS)
    try:
        data = forms.memo_data_from_post(request.POST)
        data["matter_id"] = detail["matter_id"]  # a memo never changes matter
        if detail["is_draft"] and request.POST.get("action") in ("save", "save_export"):
            # "Save memo" on a draft: check it as a finished memo first, then save and number it together.
            memos.validate_memo_input(data, is_draft=False)
            with transaction.atomic():
                memos.update_memo(profile, memo_id, data)
                memo = memos.finalize_draft(profile, memo_id, data.get("custom_memo_number") or None)
        else:
            memo = memos.update_memo(profile, memo_id, data)
    except FeesError as err:
        return _failed(request, err, form, memo=detail)
    return _saved(request, memo)


@fees_read_write
@handle_fees_errors()
@require_http_methods(["GET", "HEAD", "POST"])
def memo_based_on(request, memo_id):
    profile, _settings = scope.context(request)
    if request.method == "POST":
        memos.get_memo(profile, memo_id)  # another profile's memo is a 404
        return _create(request, based_on=memo_id)
    source = memos.create_based_on(profile, memo_id)
    return _form_page(request, forms.memo_form_from_detail(source), based_on=memo_id)


def _move_page(request, memo, errors=None, status=200):
    """The move confirmation page: a matter picker grouped by firm, active matters other than the current one."""
    profile, _settings = scope.context(request)
    by_firm = {}
    for matter in matters.list_matters(profile, status_filter="active"):
        if matter.pk != memo["matter_id"]:
            by_firm.setdefault(matter.firm.name, []).append(matter)
    groups = [{"firm": name, "matters": by_firm[name]} for name in sorted(by_firm, key=str.lower)]
    return render_page(
        request,
        "fees/memo_move.html",
        {"memo": memo, "firm_groups": groups, "errors": errors or []},
        status=status,
    )


@fees_editor
@handle_fees_errors()
@require_http_methods(["GET", "HEAD", "POST"])
def memo_move(request, memo_id):
    """Move a memo to another active matter. The number, payments and totals do not change."""
    profile, _settings = scope.context(request)
    memo = memos.get_memo(profile, memo_id)  # another profile's memo is a 404
    if request.method != "POST":
        return _move_page(request, memo)
    target = (request.POST.get("matter_id") or "").strip()
    try:
        if not target.isdigit():
            raise FeesError("INVALID_MEMO", "Choose the matter to move this memo to.")
        moved = memos.move_memo(profile, memo_id, int(target))
    except FeesError as err:
        if err.status == 404:
            raise Http404(err.message) from err
        return _move_page(request, memo, errors=[err.message], status=err.status)
    messages.success(request, f"Memo {moved.memo_number or '(draft)'} moved.")
    return redirect("fees_memo_detail", memo_id=memo_id)


@fees_editor
@handle_fees_errors()
@require_POST
def memo_delete(request, memo_id):
    profile, _settings = scope.context(request)
    memos.get_memo(profile, memo_id)  # another profile's memo is a 404 before the confirm check
    if request.POST.get("confirm") != "1":
        messages.error(request, "Tick the box to confirm that you want to delete this memo.")
        return redirect("fees_memo_detail", memo_id=memo_id)
    memos.delete_memo(profile, memo_id)
    messages.success(request, "Memo deleted.")
    return redirect("fees_memos")


@fees_editor
@handle_fees_errors()
@require_POST
def memo_write_off(request, memo_id):
    profile, _settings = scope.context(request)
    written_off = request.POST.get("written_off") == "1"
    memos.set_memo_written_off(profile, memo_id, written_off)
    messages.success(request, "Memo written off." if written_off else "Write-off removed.")
    return redirect("fees_memo_detail", memo_id=memo_id)


@fees_editor
@handle_fees_errors()
@require_POST
def memo_finalise(request, memo_id):
    profile, _settings = scope.context(request)
    memo = memos.finalize_draft(profile, memo_id, (request.POST.get("custom_memo_number") or "").strip() or None)
    messages.success(request, f"Memo {memo.memo_number} numbered.")
    return redirect("fees_memo_detail", memo_id=memo_id)


@fees_reader
@handle_fees_errors(json=True)
@require_safe
def preview_number(request):
    """JSON: the number the next memo of a date would get. Reads only; nothing is reserved."""
    profile, _settings = scope.context(request)
    date = forms.parse_date(request.GET.get("date")) or current_financial_year()
    return json_ok({"number": memos.preview_number(profile, date)})


@fees_reader
@handle_fees_errors(json=True)
@require_safe
def preview_totals(request):
    """JSON: the fees a memo form would save, worked out by the one fee rule, and the total in words.

    Reads only. The form's JavaScript shows this as a preview; the save always recomputes on the server.
    """
    data = {}
    for name in forms.MEMO_COUNT_FIELDS:
        data[name] = forms.parse_int(request.GET.get(name), name.replace("_", " ").capitalize())
    for name in forms.MEMO_RATE_FIELDS:
        data[name] = forms.parse_decimal(request.GET.get(name), name.replace("_", " ").capitalize()) or 0
    for name in forms.MEMO_CUSTOM_FIELDS:
        data[name] = forms.parse_decimal(request.GET.get(name), name.replace("_", " ").capitalize())
    fees = memo_fees.resolve_memo_fees(data)
    return json_ok(
        {
            "fees_appearances": fees.fees_appearances,
            "fees_conferences": fees.fees_conferences,
            "fees_misc": fees.fees_misc,
            "total_fees": fees.total_fees,
            "words": fees_in_words(max(fees.total_fees, 0)),
        }
    )
