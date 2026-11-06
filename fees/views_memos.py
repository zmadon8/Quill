"""Memo pages: the list, drafts, one memo, and the new, edit and based-on forms."""
from django.views.decorators.http import require_GET

from fees import forms, scope
from fees.decorators import fees_read_write, fees_reader, handle_fees_errors
from fees.pages import json_ok, memo_filters, page_number, render_page
from fees.services.financial_year import current_financial_year
from fees.services import firms, matters, memo_lists, memos, payments
from fees.services import settings as settings_service

PAGE_SIZE = 50


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
@require_GET
def memo_list(request):
    return _list_page(request, "exclude_drafts", "fees/memos.html")


@fees_reader
@handle_fees_errors()
@require_GET
def draft_list(request):
    return _list_page(request, "drafts_only", "fees/drafts.html")


@fees_reader
@handle_fees_errors()
@require_GET
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


def _form_page(request, form, memo=None, based_on=None):
    profile, _settings = scope.context(request)
    return render_page(
        request,
        "fees/memo_form.html",
        {
            "form": form,
            "memo": memo,
            "based_on": based_on,
            "matter_choices": matters.list_matters(profile, status_filter="active"),
            "errors": [],
        },
    )


@fees_read_write
@handle_fees_errors()
@require_GET
def memo_new(request):
    profile, _settings = scope.context(request)
    config = settings_service.get_settings(profile)
    form = forms.blank_memo_form(config)
    matter_id = request.GET.get("matter", "").strip()
    if matter_id.isdigit():
        form = forms.apply_matter_defaults(form, matters.get_matter(profile, int(matter_id)))
    return _form_page(request, form)


@fees_read_write
@handle_fees_errors()
@require_GET
def memo_edit(request, memo_id):
    profile, _settings = scope.context(request)
    detail = memos.get_memo(profile, memo_id)
    return _form_page(request, forms.memo_form_from_detail(detail), memo=detail)


@fees_read_write
@handle_fees_errors()
@require_GET
def memo_based_on(request, memo_id):
    profile, _settings = scope.context(request)
    source = memos.create_based_on(profile, memo_id)
    return _form_page(request, forms.memo_form_from_detail(source), based_on=memo_id)


@fees_reader
@handle_fees_errors(json=True)
@require_GET
def preview_number(request):
    """JSON: the number the next memo of a date would get. Reads only; nothing is reserved."""
    profile, _settings = scope.context(request)
    date = forms.parse_date(request.GET.get("date")) or current_financial_year()
    return json_ok({"number": memos.preview_number(profile, date)})
