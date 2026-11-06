"""Settings page, the Word template and signature downloads, the file-name preview and the statistics grid."""
import datetime
from types import SimpleNamespace

from django.views.decorators.http import require_GET

from fees import scope
from fees.decorators import fees_read_write, fees_reader, handle_fees_errors
from fees.exports.filenames import memo_export_filename, validate_pattern
from fees.models import Memo
from fees.pages import DOCX_TYPE, bytes_response, json_ok, render_page
from fees.services import settings as settings_service
from fees.services import statistics, word_template
from fees.views_statistics import financial_year_param

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
@require_GET
def settings_page(request):
    profile, _settings = scope.context(request)
    return render_page(request, "fees/settings.html", settings_context(profile))


@fees_reader
@handle_fees_errors()
@require_GET
def template_download(request):
    profile, _settings = scope.context(request)
    name, data = word_template.download_template(profile)
    return bytes_response(name, data, DOCX_TYPE)


@fees_reader
@handle_fees_errors()
@require_GET
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
@require_GET
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


@fees_read_write
@handle_fees_errors(json=True)
@require_GET
def statistics_grid(request):
    """JSON: the month-by-month adjustments of one financial year. (Saving one is a POST, added with the write views.)"""
    profile, _settings = scope.context(request)
    fy = financial_year_param(request.GET)
    return json_ok({"financial_year": fy, "adjustments": statistics.list_adjustments(profile, fy)})
