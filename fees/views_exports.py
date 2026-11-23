"""Excel and Word exports. Every export is a GET and a pure read, so a Reader may use them (R-EX-6)."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_safe

from fees import scope
from fees.decorators import fees_reader, handle_fees_errors
from fees.exports import xlsx
from fees.errors import FeesError
from fees.pages import DOCX_TYPE, PDF_TYPE, XLSX_TYPE, bank_on, feebook_filters, file_response, memo_filters, outstanding_filters, overdue_on
from fees.services import memos, word_template
from fees.views_ledger import client_param, group_param, scope_for


@fees_reader
@handle_fees_errors()
@require_safe
def memo_word(request, memo_id):
    profile, _settings = scope.context(request)
    memos.get_memo(profile, memo_id)  # another profile's memo is a 404 before any template work
    return file_response(word_template.render_memo_docx(profile, memo_id), DOCX_TYPE)


@fees_reader
@handle_fees_errors()
@require_safe
def memo_pdf(request, memo_id):
    """The memo as PDF: the Word memo converted by Microsoft 365 (docs/FEES_PDF_EXPORT.md). A user who switched PDF off on My
    settings is refused; any failure goes back to the memo page with the reason and a link to the Word file."""
    from fees.exports import pdf_graph

    profile, _settings = scope.context(request)
    memos.get_memo(profile, memo_id)  # another profile's memo is a 404 before anything else
    if not getattr(request.user, "pdf_export", True):
        raise PermissionDenied("PDF is switched off for you on My settings.")
    try:
        if not pdf_graph.available():
            raise pdf_graph.PdfError(pdf_graph.NOT_SET_UP if not pdf_graph.configured() else pdf_graph.NOT_CONNECTED)
        return file_response(word_template.render_memo_pdf(profile, memo_id), PDF_TYPE)
    except (FeesError, pdf_graph.PdfError) as err:
        messages.error(request, f"The PDF could not be made. {err.message}")
        return redirect(reverse("fees_memo_detail", kwargs={"memo_id": memo_id}) + "?pdf=failed")


@fees_reader
@handle_fees_errors()
@require_safe
def memos_export(request):
    profile, _settings = scope.context(request)
    return file_response(xlsx.export_memos(profile, memo_filters(request.GET)), XLSX_TYPE)


@fees_reader
@handle_fees_errors()
@require_safe
def memo_statement(request, memo_id):
    """The Statement workbook of the memo's matter."""
    profile, _settings = scope.context(request)
    detail = memos.get_memo(profile, memo_id)
    return file_response(xlsx.export_statement(profile, {"matter_id": detail["matter_id"]}), XLSX_TYPE)


@fees_reader
@handle_fees_errors()
@require_safe
def firm_statement_export(request, firm_id):
    profile, _settings = scope.context(request)
    ledger_scope, _owner = scope_for(profile, "firm", firm_id, group_param(request), client_param(request))
    return file_response(xlsx.export_statement(profile, ledger_scope), XLSX_TYPE)


@fees_reader
@handle_fees_errors()
@require_safe
def firm_ledger_export(request, firm_id):
    profile, _settings = scope.context(request)
    ledger_scope, _owner = scope_for(profile, "firm", firm_id, group_param(request), client_param(request))
    return file_response(xlsx.export_ledger(profile, ledger_scope), XLSX_TYPE)


@fees_reader
@handle_fees_errors()
@require_safe
def matter_statement_export(request, matter_id):
    profile, _settings = scope.context(request)
    ledger_scope, _owner = scope_for(profile, "matter", matter_id)
    return file_response(xlsx.export_statement(profile, ledger_scope), XLSX_TYPE)


@fees_reader
@handle_fees_errors()
@require_safe
def matter_ledger_export(request, matter_id):
    profile, _settings = scope.context(request)
    ledger_scope, _owner = scope_for(profile, "matter", matter_id)
    return file_response(xlsx.export_ledger(profile, ledger_scope), XLSX_TYPE)


@fees_reader
@handle_fees_errors()
@require_safe
def feebook_export(request):
    profile, settings = scope.context(request)
    if bank_on(settings):
        return file_response(xlsx.export_feebook(profile, feebook_filters(request.GET)), XLSX_TYPE)
    # Bank switched off: no Bank column and no bank filter from an old link.
    keys = [c[0] for c in xlsx.FEEBOOK_COLUMNS if c[0] != "bank"]
    return file_response(xlsx.export_feebook(profile, feebook_filters(request.GET, with_bank=False), visible_keys=keys), XLSX_TYPE)


@fees_reader
@handle_fees_errors()
@require_safe
def outstanding_export(request):
    profile, settings = scope.context(request)
    return file_response(xlsx.export_outstanding(profile, outstanding_filters(request.GET, overdue_on(settings))), XLSX_TYPE)


@fees_reader
@handle_fees_errors()
@require_safe
def outstanding_summary_export(request):
    profile, settings = scope.context(request)
    sort = "name" if request.GET.get("sort") in ("name", "firm") else "amount"  # the page's own sort links are -firm, memos, ...
    return file_response(xlsx.export_outstanding_by_firm(profile, outstanding_filters(request.GET, overdue_on(settings)), sort), XLSX_TYPE)


def _hidden_columns(request):
    """``?hide=2,5``: the positions hidden in the Matter page's Columns menu (sent by columns.js from this browser's choice)."""
    return [int(x) for x in (request.GET.get("hide") or "").split(",") if x.strip().isdigit()]


@fees_reader
@handle_fees_errors()
@require_safe
def matter_memos_export(request, matter_id):
    """The Matter page's memo table as Excel: all its memos, or only the outstanding ones (``?outstanding=1``), with its shown columns."""
    from fees.services import matters
    from fees.views_matters import matter_memo_items

    profile, _settings = scope.context(request)
    matter = matters.get_matter(profile, matter_id)
    outstanding_only = request.GET.get("outstanding") == "1"
    items = matter_memo_items(profile, matter_id, outstanding_only)
    title = f"Memos - {matter.name}" + (" - Outstanding" if outstanding_only else "")
    return file_response(xlsx.export_matter_memos(items, title, _hidden_columns(request)), XLSX_TYPE)


@fees_reader
@handle_fees_errors()
@require_safe
def firm_memos_export(request, firm_id):
    """Every memo of each matter the firm page shows (``?matters=all|active|archived``), matter by matter, with the Matter page's columns."""
    from fees.services import firms
    from fees.views_firms import filter_matter_rows, matters_shown
    from fees.views_matters import matter_memo_items

    profile, settings = scope.context(request)
    detail = firms.get_firm(profile, firm_id)
    shown = matters_shown(request, settings)
    items = []
    for row in filter_matter_rows(detail["matters"], shown):
        items.extend(matter_memo_items(profile, row["matter"].pk))
    label = {"active": " - Active Matters", "archived": " - Archived Matters"}.get(shown, "")
    return file_response(xlsx.export_matter_memos(items, f"Memos - {detail['firm'].name}{label}", _hidden_columns(request), with_matter=True),
                         XLSX_TYPE)

