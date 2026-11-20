"""Settings page and its saves, bank accounts, the Word template and signature (upload and download), the
file-name preview and the statistics grid."""
import datetime
import re
from types import SimpleNamespace
from urllib.parse import urlencode

from django.contrib import messages
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_safe, require_POST

from fees import forms, scope
from fees.decorators import fees_editor, fees_read_write, fees_reader, handle_fees_errors
from fees.errors import FeesError
from fees.exports import tag_reference
from fees.exports.filenames import DEFAULT_PATTERN, PLACEHOLDERS, memo_export_filename, validate_pattern
from fees.models import BankAccount, Memo
from fees.pages import DOCX_TYPE, bytes_response, json_ok, render_page
from fees.services import settings as settings_service
from fees.services import fy_options, statistics, word_template
from fees.services.financial_year import current_financial_year
from fees.views_statistics import adjustment_rows, ensure_statistics_on, financial_year_param, is_page_post, page_post

#: Largest Word template accepted (the template prepare step has its own, tighter limits).
MAX_TEMPLATE_UPLOAD = 20 * 1024 * 1024

#: The left-hand sections of the Settings page, in order (the numbers in the menu are 1 to 6).
SETTINGS_SECTIONS = ("memos", "payments", "word", "years", "display", "data")
PAYMENT_AMOUNT_CHOICES = (("zero", "Blank"), ("full", "Full Amount Due"), ("netOfTds", "Amount Due Less TDS"))
MONEY_UNIT_CHOICES = (("full", "Full Figures"), ("truncated", "Short (Thousand, Lac, Crore)"))


#: Ready-made file name patterns for the builder (each is checked by ``validate_pattern`` in the tests).
FILENAME_PRESETS = (
    {"label": "Standard", "pattern": DEFAULT_PATTERN},
    {"label": "Number and matter", "pattern": "Memo {memo_no}[ of {fy}] {matter}"},
    {"label": "Date first", "pattern": "{date_iso} {firm} {matter} Memo {memo_no}"},
    {"label": "Owner and number", "pattern": "{owner} Memo {memo_no}[ of {fy}]"},
)
#: Buttons that insert a piece of pattern text at the cursor.
FILENAME_PARTS = (
    {"label": "Memo number", "text": "{memo_no}"},
    {"label": "Financial year", "text": "{fy}"},
    {"label": "Date (dd.mm.yyyy)", "text": "{date}"},
    {"label": "Date (yyyy-mm-dd)", "text": "{date_iso}"},
    {"label": "Today", "text": "{today}"},
    {"label": "Firm", "text": "{firm}"},
    {"label": "Matter", "text": "{matter}"},
    {"label": "Owner name", "text": "{owner}"},
    {"label": "Optional [ ]", "text": "[]"},
    {"label": "Space", "text": " "},
    {"label": "Dash", "text": " - "},
    {"label": "Underscore", "text": "_"},
    {"label": "Brackets ( )", "text": "()"},
)


def settings_context(profile, fy=None, tab="memos"):
    """What the Settings page shows besides the form values.

    ``fy`` is the financial year of the Edit statistics grid (the current year when not given); the grid is
    built only while Statistics is switched on.
    """
    config = settings_service.get_settings(profile)
    context = {
        "filename_presets": FILENAME_PRESETS,
        "filename_parts": FILENAME_PARTS,
        "filename_tokens": PLACEHOLDERS,
        "filename_errors": validate_pattern(config["memo_filename_pattern"]),
        "config": config,
        "party_types_text": {"plaintiff": "\n".join(config["plaintiff_types"]), "defendant": "\n".join(config["defendant_types"])},
        "max_party_types": settings_service.MAX_PARTY_TYPES,
        "max_party_type": settings_service.MAX_PARTY_TYPE,
        "start_year_options": fy_options.start_year_options(
            profile, (config["initial_financial_year"], config["memos_start_year"], config["feebook_start_year"])
        ),
        "bank_accounts": settings_service.list_bank_accounts(profile),
        "template_info": word_template.get_template_info(profile),
        "payment_amount_choices": PAYMENT_AMOUNT_CHOICES,
        "money_unit_choices": MONEY_UNIT_CHOICES,
        "money_unit": config["money_unit"],
        "tab": tab if tab in SETTINGS_SECTIONS else "memos",
    }
    if config["statistics_enabled"]:
        fy = fy or current_financial_year()
        years = fy_options.financial_year_options(profile, config["initial_financial_year"], fy)
        # Every year in one grid with one Save (owner round 2026-11); the year asked for (the current one by default) is open.
        context.update(
            fy=fy,
            fy_options=years,
            adjustment_rows=adjustment_rows(profile, fy),
            adjustment_years=_adjustment_years(profile, years, fy),
        )
    return context


@fees_read_write
@handle_fees_errors()
@require_http_methods(["GET", "HEAD", "POST"])
def settings_page(request):
    profile, _settings = scope.context(request)
    tab = request.POST.get("tab") or request.GET.get("tab") or ""
    if request.method == "POST":
        try:
            settings_service.update_settings(profile, forms.settings_data_from_post(request.POST))
        except FeesError as err:
            if err.status == 404:
                raise Http404(err.message) from err
            context = settings_context(profile, tab=tab)
            context["personal_form"] = _personal_form(request, profile)
            context["errors"] = [err.message]
            return render_page(request, "fees/settings.html", context, status=err.status)
        messages.success(request, "Settings saved.")
        # A save from one section returns to that section; an older form that names none returns to the page.
        return redirect(f"{reverse('fees_settings')}?tab={tab}" if tab in SETTINGS_SECTIONS else "fees_settings")
    context = settings_context(profile, financial_year_param(request.GET, default=False), tab=tab)
    context["personal_form"] = _personal_form(request, profile)
    return render_page(request, "fees/settings.html", context)


def _personal_form(request, profile):
    """My items per page (Only you): saved through My settings (tab "fees"), shown here with the other Display settings."""
    from fees.models import FeesSettings
    from fees.personal_form import FeesPersonalForm

    return FeesPersonalForm(
        prefix="fees", profile=profile, user=request.user, fees_settings=FeesSettings.objects.filter(profile=profile).first(),
    )


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
        client_position="Sample Brief on Behalf of",
        matter=SimpleNamespace(name="Sample Matter", short_name=""),
        firm=SimpleNamespace(name="Sample Firm"),
        group=SimpleNamespace(name="Sample Partner"),
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


def _adjustment_years(profile, years, open_fy):
    """Every year of the Edit Statistics grid, its saved months read in ONE query: [{fy, rows, open}]."""
    from fees.models import PeriodAdjustment
    from fees.services.statistics.adjustments import _to_dto

    saved = {}
    for row in PeriodAdjustment.objects.filter(profile=profile, financial_year__in=years):
        saved.setdefault(row.financial_year, {})[row.month] = _to_dto(row)
    return [{"fy": year, "rows": adjustment_rows(profile, year, saved.get(year, {})), "open": year == open_fy} for year in years]


def _optional(text, parse):
    value = (text or "").strip()
    return parse(value) if value else None


def _parse_adjustment(post, fy, month):
    """One month's adjustment from posted values (``post`` maps the plain field names: working_days, override_billed ...)."""
    adjustment = {
        "financial_year": fy,
        "month": month,
        "working_days": forms.parse_int(post.get("working_days"), "Working days"),
        "extra_appearances": forms.parse_int(post.get("extra_appearances"), "Extra appearances"),
        "extra_conferences": forms.parse_int(post.get("extra_conferences"), "Extra conferences"),
        "extra_drafts": forms.parse_int(post.get("extra_drafts"), "Extra drafts"),
    }
    for key in ("override_appearances", "override_conferences", "override_drafts"):
        label = "Replace " + key[len("override_"):]
        adjustment[key] = _optional(post.get(key), lambda v, k=label: forms.parse_int(v, k))
    for key in ("override_billed", "override_received", "override_received_plus_tds"):
        adjustment[key] = forms.parse_decimal(post.get(key), key)
    return adjustment


def _save_adjustment(profile, post):
    """Save one month of the statistics grid from posted form values; returns its financial year."""
    month = forms.parse_int(post.get("month"), "Month", default=0)
    if not 1 <= month <= 12:
        raise FeesError("INVALID_MONTH", "Month must be from 1 to 12.")
    fy = financial_year_param(post)
    statistics.save_adjustment(profile, _parse_adjustment(post, fy, month))
    return fy


_FY_LABEL = re.compile(r"^\d{4}-\d{2}$")
#: A field of the whole Edit Statistics grid: ``<field>__<financial year>__<month>``, e.g. ``working_days__2026-27__4``.
_GRID_FIELD = re.compile(r"^(working_days|extra_appearances|extra_conferences|extra_drafts|override_appearances|"
                         r"override_conferences|override_drafts|override_billed|override_received|"
                         r"override_received_plus_tds)__(\d{4}-\d{2})__(\d{1,2})$")
_ADJUSTMENT_KEYS = ("working_days", "extra_appearances", "extra_conferences", "extra_drafts", "override_appearances",
                    "override_conferences", "override_drafts", "override_billed", "override_received",
                    "override_received_plus_tds")
_MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                "November", "December")


def _same(saved, adjustment):
    """True when ``adjustment`` holds what is saved (a month never saved counts as all 0 and no replacements)."""
    for key in _ADJUSTMENT_KEYS:
        old = saved.get(key) if saved else None
        if old is None and not key.startswith("override_"):
            old = 0
        if (old is None) != (adjustment[key] is None) or (old is not None and old != adjustment[key]):
            return False
    return True


def _save_grid(profile, post):
    """Save the whole Edit Statistics grid (every year and month on the page) with its one Save button.

    Every month is read first, so a mistake anywhere saves nothing; then only the months that changed are saved, in one
    transaction. Returns the number of months saved.
    """
    cells = {}
    for name, value in post.items():
        match = _GRID_FIELD.match(name)
        if match:
            key, fy, month = match.group(1), match.group(2), int(match.group(3))
            if 1 <= month <= 12:
                cells.setdefault((fy, month), {})[key] = value
    wanted = []
    for (fy, month), values in sorted(cells.items()):
        try:
            wanted.append(_parse_adjustment(values, fy, month))
        except FeesError as err:
            raise FeesError(err.code, f"{_MONTH_NAMES[month - 1]} {fy}: {err.message}") from err
    saved = {}
    for fy in {a["financial_year"] for a in wanted}:
        saved.update({(fy, row["month"]): row for row in statistics.list_adjustments(profile, fy)})
    changed = [a for a in wanted if not _same(saved.get((a["financial_year"], a["month"])), a)]
    with transaction.atomic():
        for adjustment in changed:
            statistics.save_adjustment(profile, adjustment)
    return len(changed)


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

        if is_page_post(request) and post.get("grid") == "1":
            fy = post.get("fy") or ""
            query = {"tab": "years", **({"fy": fy} if _FY_LABEL.match(fy) else {})}
            try:
                ensure_statistics_on(config)
                count = _save_grid(profile, post)
            except FeesError as err:
                if err.status == 404:
                    raise Http404(err.message) from err
                messages.error(request, err.message)
            else:
                if count:
                    messages.success(request, f"Edit Statistics saved ({count} month{'s' if count != 1 else ''} changed).")
                else:
                    messages.info(request, "No changes to save.")
            return redirect(reverse("fees_settings") + "?" + urlencode(query) + "#settings-years")
        if is_page_post(request):
            fy = post.get("fy") or ""
            return page_post(request, save, "Adjustments saved.", _to="fees_settings", _fragment="#settings-years", fy=fy)
        fy = save()
        return json_ok({"financial_year": fy, "adjustments": statistics.list_adjustments(profile, fy)})
    ensure_statistics_on(config)
    fy = financial_year_param(request.GET)
    return json_ok({"financial_year": fy, "adjustments": statistics.list_adjustments(profile, fy)})
