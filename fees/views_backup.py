"""Backup page, the Excel backup download, restore from an Excel file and clear all. Editors only.

The backup carries every payment note, so it is not offered to a Reader. Restore and clear replace or delete
all of the profile's data: both need the typed confirmation, and both take a safety backup first (the
services do that). A second large job at the same moment gets the "busy" page (``handle_fees_errors``).
"""
import datetime

from django.contrib import messages
from django.shortcuts import redirect
from django.views.decorators.http import require_GET, require_http_methods

from fees import scope
from fees.decorators import fees_editor, handle_fees_errors
from fees.errors import FeesError
from fees.pages import XLSX_TYPE, file_response, render_page
from fees.services import clear_all, excel_backup, excel_restore
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


def _upload(request):
    upload = request.FILES.get("file")
    if upload is None:
        raise FeesError("INVALID_UPLOAD", "Choose a file to upload.")
    return upload


@fees_editor
@handle_fees_errors(fallback="fees_backup")
@require_http_methods(["GET", "POST"])
def restore(request):
    """Restore from an Excel backup in two steps: ``action=preview`` shows what the file holds and what it
    would replace; ``action=restore`` (with the typed phrase and the file again) does it."""
    profile, _settings = scope.context(request)
    if request.method == "GET":
        return redirect("fees_backup")
    upload = _upload(request)
    if request.POST.get("action") == "restore":
        result = excel_restore.restore_workbook(
            profile, upload, request.POST.get("confirmation", ""), user=request.user
        )
        return render_page(request, "fees/restore_result.html", {"result": result})
    preview = excel_restore.preview_workbook(upload, profile)
    return render_page(
        request,
        "fees/restore_preview.html",
        {"preview": preview, "restore_phrase": RESTORE_CONFIRMATION, "file_name": upload.name},
    )


@fees_editor
@handle_fees_errors(fallback="fees_backup")
@require_http_methods(["GET", "POST"])
def clear(request):
    """Delete all of this profile's Fee Register data. The user types the profile name to confirm."""
    profile, _settings = scope.context(request)
    if request.method == "GET":
        return render_page(request, "fees/clear_confirm.html", {"clear_phrase": profile.name})
    result = clear_all.clear_all(profile, request.POST.get("confirmation", ""), user=request.user)
    messages.success(request, "All Fee Register data was deleted. A safety backup was made first.")
    return render_page(request, "fees/clear_result.html", {"result": result})
