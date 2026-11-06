"""Settings page and its saves, bank accounts, the Word template and signature (upload and download), the
file-name preview and the statistics grid."""
import datetime
from types import SimpleNamespace

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods, require_safe, require_POST

from fees import forms, scope
from fees.decorators import fees_editor, fees_read_write, fees_reader, handle_fees_errors
from fees.errors import FeesError
from fees.exports import tag_reference
from fees.exports.filenames import memo_export_filename, validate_pattern
from fees.models import BankAccount, Memo
from fees.pages import DOCX_TYPE, bytes_response, json_ok, render_page
from fees.services import settings as settings_service
from fees.services import statistics, word_template
from fees.views_statistics import ensure_statistics_on, financial_year_param, is_page_post, page_post

#: Largest Word template accepted (the template prepare step has its own, tighter limits).
MAX_TEMPLATE_UPLOAD = 20 * 1024 * 1024

DEFAULT_TAB_CHOICES = ("memos", "dashboard", "statistics", "firms", "feebook", "outstanding", "settings")
PAYMENT_AMOUNT_CHOICES = (("zero", "Blank"), ("full", "Full amount due"), ("netOfTds", "Amount due less TDS"))
MONEY_UNIT_CHOICES = (("full", "Full figures"), ("truncated", "Short (thousand, lac, crore)"))


def settings_context(profile):
    """What the Settings page shows besides the form values."""
    return {
        "config": settings_service.get_settings(profile),
        "bank_accounts": settings_service.list_bank_accounts(profile),
        "template_info": word_template.get_template_info(profile),
        "tab_choices": DEFAULT_TAB_CHOICES,
        "payment_amount_choices": PAYMENT_AMOUNT_CHOICES,
        "money_unit_choices": MONEY_UNIT_CHOICES,
    }


@fees_read_write
@handle_fees_errors()
@require_http_methods(["GET", "HEAD", "POST"])
def settings_page(request):
    profile, _settings = scope.context(request)
    if request.method == "POST":
        try:
            settings_service.update_settings(profile, forms.settings_data_from_post(request.POST))
        except FeesError as err:
            if err.status == 404:
                raise Http404(err.message) from err
            context = settings_context(profile)
            context["errors"] = [err.message]
            return render_page(request, "fees/settings.html", context, status=err.status)
        messages.success(request, "Settings saved.")
        return redirect("fees_settings")
    return render_page(request, "fees/settings.html", settings_context(profile))


def _bank_account_or_404(profile, account_id):
    if not BankAccount.objects.filter(profile=profile, pk=account_id).exists():
        raise Http404("Bank account not found")


@fees_editor
@handle_fees_errors(fallback="fees_settings")
@require_POST
def bank_account_add(request):
    profile, _settings = scope.context(request)
    settings_service.add_bank_account(profile, request.POST.get("name", ""))
    messages.success(request, "Bank account added.")
    return redirect("fees_settings")


@fees_editor
@handle_fees_errors(fallback="fees_settings")
@require_POST
def bank_account_rename(request, account_id):
    profile, _settings = scope.context(request)
    _bank_account_or_404(profile, account_id)
    settings_service.update_bank_account(profile, account_id, request.POST.get("name", ""))
    messages.success(request, "Bank account renamed.")
    return redirect("fees_settings")


@fees_editor
@handle_fees_errors(fallback="fees_settings")
@require_POST
def bank_account_delete(request, account_id):
    profile, _settings = scope.context(request)
    _bank_account_or_404(profile, account_id)
    settings_service.delete_bank_account(profile, account_id)
    messages.success(request, "Bank account removed.")
    return redirect("fees_settings")


def _uploaded(request, limit, message):
    """``(file name, bytes, content type)`` of the ``file`` upload, read at most ``limit`` bytes plus one."""
    upload = request.FILES.get("file")
    if upload is None:
        raise FeesError("INVALID_UPLOAD", "Choose a file to upload.")
    data = upload.read(limit + 1)
    if len(data) > limit:
        raise FeesError("INVALID_UPLOAD", message)
    return upload.name, data, upload.content_type


@fees_editor
@handle_fees_errors(fallback="fees_settings")
@require_POST
def template_upload(request):
    profile, _settings = scope.context(request)
    name, data, _type = _uploaded(request, MAX_TEMPLATE_UPLOAD, "The template is larger than 20 MB.")
    word_template.upload_template(profile, name, data)
    messages.success(request, "Word template saved.")
    return redirect("fees_settings")


@fees_editor
@handle_fees_errors(fallback="fees_settings")
@require_POST
def signature_upload(request):
    profile, _settings = scope.context(request)
    name, data, content_type = _uploaded(
        request, word_template.MAX_SIGNATURE_BYTES, "The signature image is larger than 2 MB."
    )
    word_template.upload_signature(profile, name, content_type, data)
    messages.success(request, "Signature image saved.")
    return redirect("fees_settings")


@fees_reader
@handle_fees_errors()
@require_safe
def template_download(request):
    profile, _settings = scope.context(request)
    name, data = word_template.download_template(profile)
    return bytes_response(name, data, DOCX_TYPE)


@fees_reader
@handle_fees_errors()
@require_safe
def template_tags_download(request):
    """The Word template tag reference (every tag, its short name, what it fills in, an example)."""
    return bytes_response(tag_reference.FILE_NAME, tag_reference.build_tag_reference(), DOCX_TYPE)


@fees_reader
@handle_fees_errors()
@require_safe
def signature_download(request):
    profile, _settings = scope.context(request)
    name, content_type, data = word_template.download_signature(profile)
    return bytes_response(name, data, content_type or "application/octet-stream")


def _sample_memo():
    """A built-in memo for the preview when the profile has no memo yet."""
    return SimpleNamespace(
        memo_number="2026-27/5",
        seq=5,
        date=datetime.date(2026, 7, 15),
        client="Sample Client",
        matter=SimpleNamespace(name="Sample Matter", short_name=""),
        firm=SimpleNamespace(name="Sample Firm"),
        group=SimpleNamespace(name="Sample Group"),
    )


@fees_reader
@handle_fees_errors(json=True)
@require_safe
def filename_preview(request):
    """JSON: the file name a memo would get with ``?pattern=``. Uses the same function as the real export."""
    profile, settings = scope.context(request)
    pattern = request.GET.get("pattern", settings.memo_filename_pattern)
    memo = (
        Memo.objects.filter(profile=profile, is_draft=False)
        .select_related("matter", "firm", "group")
        .order_by("-date", "-id")
        .first()
    )
    sample = memo is None
    return json_ok(
        {
            "file_name": memo_export_filename(_sample_memo() if sample else memo, settings, pattern=pattern),
            "errors": validate_pattern(pattern),
            "sample": sample,
        }
    )


def _optional(text, parse):
    value = (text or "").strip()
    return parse(value) if value else None


def _save_adjustment(profile, post):
    """Save one month of the statistics grid from posted form values; returns its financial year."""
    month = forms.parse_int(post.get("month"), "Month", default=0)
    if not 1 <= month <= 12:
        raise FeesError("INVALID_MONTH", "Month must be from 1 to 12.")
    fy = financial_year_param(post)
    adjustment = {
        "financial_year": fy,
        "month": month,
        "working_days": forms.parse_int(post.get("working_days"), "Working days"),
        "extra_appearances": forms.parse_int(post.get("extra_appearances"), "Extra appearances"),
        "extra_conferences": forms.parse_int(post.get("extra_conferences"), "Extra conferences"),
        "extra_drafts": forms.parse_int(post.get("extra_drafts"), "Extra drafts"),
    }
    for key in ("override_appearances", "override_conferences", "override_drafts"):
        adjustment[key] = _optional(post.get(key), lambda v, k=key: forms.parse_int(v, k))
    for key in ("override_billed", "override_received", "override_received_plus_tds"):
        adjustment[key] = forms.parse_decimal(post.get(key), key)
    statistics.save_adjustment(profile, adjustment)
    return fy


@fees_read_write
@handle_fees_errors(json=True)
@require_http_methods(["GET", "HEAD", "POST"])
def statistics_grid(request):
    """JSON: the month-by-month adjustments of one financial year (GET); save one month (POST, Editor)."""
    profile, config = scope.context(request)
    if request.method == "POST":
        post = request.POST

        def save():
            ensure_statistics_on(config)
            return _save_adjustment(profile, post)

        if is_page_post(request):
            fy = post.get("fy") or ""
            return page_post(request, save, "Adjustments saved.", tab="edit", fy=fy)
        fy = save()
        return json_ok({"financial_year": fy, "adjustments": statistics.list_adjustments(profile, fy)})
    ensure_statistics_on(config)
    fy = financial_year_param(request.GET)
    return json_ok({"financial_year": fy, "adjustments": statistics.list_adjustments(profile, fy)})
