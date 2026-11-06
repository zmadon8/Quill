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
from fees.services import firms, matters, memo_lists, memos, payments
from fees.services import settings as settings_service
from fees.services.financial_year import current_financial_year

PAGE_SIZE = 50
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
    filters = memo_filters(request.GET)
    items = memo_lists.list_memos(profile, filters, draft_mode=draft_mode)
    page_items, meta = memo_lists.paginate(items, page_number(request.GET), PAGE_SIZE)
    return render_page(
        request,
        template,
        {
            "items": page_items,
            "meta": meta,
            "totals": memo_lists.footer_totals(items),
            "filters": filters,
            "firm_choices": firms.list_firms(profile),
            "money_unit": settings.money_unit,
            "query_string": _without_page(request),
        },
    )


def _without_page(request):
    query = request.GET.copy()
    query.pop("page", None)
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


def _form_page(request, form, memo=None, based_on=None, errors=None, status=200):
    profile, _settings = scope.context(request)
    return render_page(
        request,
        "fees/memo_form.html",
        {
            "form": form,
            "memo": memo,
            "based_on": based_on,
            "matter_choices": matters.list_matters(profile, status_filter="active"),
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
    return redirect("fees_memo_detail", memo_id=memo.pk)


def _create(request, based_on=None):
    profile, _settings = scope.context(request)
    form = forms.echo_form(request.POST, FORM_FIELDS)
    try:
        data = forms.memo_data_from_post(request.POST)
        if data["matter_id"] is None:
            raise FeesError("INVALID_MEMO", "Choose a matter.")
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
        form = forms.apply_matter_defaults(form, matters.get_matter(profile, int(matter_id)))
    return _form_page(request, form)


@fees_read_write
@handle_fees_errors()
@require_http_methods(["GET", "HEAD", "POST"])
def memo_edit(request, memo_id):
    profile, _settings = scope.context(request)
    detail = memos.get_memo(profile, memo_id)
    if request.method == "GET":
        return _form_page(request, forms.memo_form_from_detail(detail), memo=detail)
    form = forms.echo_form(request.POST, FORM_FIELDS)
    try:
        data = forms.memo_data_from_post(request.POST)
        data["matter_id"] = detail["matter_id"]  # a memo never changes matter
        if detail["is_draft"] and request.POST.get("action") == "save":
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


@fees_editor
@handle_fees_errors()
@require_POST
def memo_delete(request, memo_id):
    profile, _settings = scope.context(request)
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
