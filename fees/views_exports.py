"""Excel and Word exports. Every export is a GET and a pure read, so a Reader may use them (R-EX-6)."""
from django.views.decorators.http import require_GET

from fees import scope
from fees.decorators import fees_reader, handle_fees_errors
from fees.exports import xlsx
from fees.pages import DOCX_TYPE, XLSX_TYPE, feebook_filters, file_response, memo_filters, outstanding_filters
from fees.services import memos, word_template
from fees.views_ledger import scope_for


@fees_reader
@handle_fees_errors()
@require_GET
def memo_word(request, memo_id):
    profile, _settings = scope.context(request)
    memos.get_memo(profile, memo_id)  # another profile's memo is a 404 before any template work
    return file_response(word_template.render_memo_docx(profile, memo_id), DOCX_TYPE)


@fees_reader
@handle_fees_errors()
@require_GET
def memos_export(request):
    profile, _settings = scope.context(request)
    return file_response(xlsx.export_memos(profile, memo_filters(request.GET)), XLSX_TYPE)


@fees_reader
@handle_fees_errors()
@require_GET
def memo_statement(request, memo_id):
    """The Statement workbook of the memo's matter."""
    profile, _settings = scope.context(request)
    detail = memos.get_memo(profile, memo_id)
    return file_response(xlsx.export_statement(profile, {"matter_id": detail["matter_id"]}), XLSX_TYPE)


@fees_reader
@handle_fees_errors()
@require_GET
def firm_statement_export(request, firm_id):
    profile, _settings = scope.context(request)
    ledger_scope, _owner = scope_for(profile, "firm", firm_id)
    return file_response(xlsx.export_statement(profile, ledger_scope), XLSX_TYPE)


@fees_reader
@handle_fees_errors()
@require_GET
def firm_ledger_export(request, firm_id):
    profile, _settings = scope.context(request)
    ledger_scope, _owner = scope_for(profile, "firm", firm_id)
    return file_response(xlsx.export_ledger(profile, ledger_scope), XLSX_TYPE)


@fees_reader
@handle_fees_errors()
@require_GET
def matter_statement_export(request, matter_id):
    profile, _settings = scope.context(request)
    ledger_scope, _owner = scope_for(profile, "matter", matter_id)
    return file_response(xlsx.export_statement(profile, ledger_scope), XLSX_TYPE)


@fees_reader
@handle_fees_errors()
@require_GET
def matter_ledger_export(request, matter_id):
    profile, _settings = scope.context(request)
    ledger_scope, _owner = scope_for(profile, "matter", matter_id)
    return file_response(xlsx.export_ledger(profile, ledger_scope), XLSX_TYPE)


@fees_reader
@handle_fees_errors()
@require_GET
def feebook_export(request):
    profile, _settings = scope.context(request)
    return file_response(xlsx.export_feebook(profile, feebook_filters(request.GET)), XLSX_TYPE)


@fees_reader
@handle_fees_errors()
@require_GET
def outstanding_export(request):
    profile, _settings = scope.context(request)
    return file_response(xlsx.export_outstanding(profile, outstanding_filters(request.GET)), XLSX_TYPE)


@fees_reader
@handle_fees_errors()
@require_GET
def outstanding_summary_export(request):
    profile, _settings = scope.context(request)
    sort = "name" if request.GET.get("sort") == "name" else "amount"
    return file_response(xlsx.export_outstanding_by_firm(profile, outstanding_filters(request.GET), sort), XLSX_TYPE)
