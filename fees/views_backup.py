"""Backup page and the Excel backup download. Editors only: the backup carries every payment note."""
import datetime

from django.views.decorators.http import require_GET

from fees import scope
from fees.decorators import fees_editor, handle_fees_errors
from fees.pages import XLSX_TYPE, file_response, render_page
from fees.services import excel_backup
from fees.services.excel_restore import RESTORE_CONFIRMATION
from fees.services.heavy import heavy_operation


@fees_editor
@handle_fees_errors()
@require_GET
def backup_page(request):
    profile, _settings = scope.context(request)
    return render_page(
        request,
        "fees/backup.html",
        {"restore_phrase": RESTORE_CONFIRMATION, "clear_phrase": profile.name},
    )


@fees_editor
@handle_fees_errors()
@require_GET
def backup_download(request):
    profile, _settings = scope.context(request)
    with heavy_operation("excel_backup"):
        fileobj = excel_backup.export_workbook(profile)
    name = f"Fee Register Backup {datetime.date.today().isoformat()}.xlsx"
    return file_response((name, fileobj), XLSX_TYPE)
