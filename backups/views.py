import hashlib
import io
import logging
import os
import re

from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from accounts.permissions import admin_required

from . import services
from .models import KEEP_KINDS, BackupFile, BackupLog

logger = logging.getLogger(__name__)

CONFIRM_WORD = "RESTORE"


def csrf_failure(request, reason=""):
    """Plain 403 page for a failed security check (stale page, cookies blocked, other address)."""
    logger.warning("CSRF check failed: %s (path %s, host %s)", reason, request.path, request.get_host())
    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse({"ok": False, "csrf": True, "errors": ["Your session has expired. Reload the page and sign in again."]}, status=403)
    return render(request, "403_csrf.html", status=403)


def _max_bytes():
    return settings.MAX_BACKUP_UPLOAD_MB * 1024 * 1024


@admin_required
def backup_list(request):
    backups = BackupFile.objects.defer("data").order_by("-created_at", "-id")
    logs = BackupLog.objects.select_related("created_by").order_by("-started_at", "-id")[:30]
    return render(request, "backups/backup_list.html", {"backups": backups, "logs": logs, "offsite": services.offsite_status()})


@admin_required
@require_POST
def backup_now(request):
    try:
        backup = services.create_backup("manual", request.user)
    except Exception as exc:
        messages.error(request, f"The backup FAILED: {exc}")
    else:
        messages.success(request, f"Backup taken: {backup.filename}")
    return redirect("backup_list")


@admin_required
def backup_download(request, pk):
    backup = get_object_or_404(BackupFile, pk=pk)
    return FileResponse(
        io.BytesIO(bytes(backup.data)),
        as_attachment=True,
        filename=backup.filename,
        content_type="application/octet-stream",
    )


@admin_required
@require_http_methods(["GET", "POST"])
def restore_upload(request):
    if request.method == "POST":
        upload = request.FILES.get("backup_file")
        if upload is None:
            messages.error(request, "Choose a backup file first.")
            return redirect("restore_upload")
        if upload.size > _max_bytes():
            messages.error(request, f"That file is larger than the {settings.MAX_BACKUP_UPLOAD_MB} MB limit.")
            return redirect("restore_upload")
        raw = upload.read()
        try:
            document = services.parse_backup(raw, _max_bytes())
        except services.BackupError as exc:
            messages.error(request, str(exc))
            return redirect("restore_upload")
        name = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(upload.name or "uploaded-backup.json.gz"))
        backup = BackupFile.objects.create(
            kind="uploaded",
            filename=name[:200] or "uploaded-backup.json.gz",
            data=raw,
            size_bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            record_counts=document.get("counts") if isinstance(document.get("counts"), dict) else {},
            created_by=request.user,
        )
        return redirect("restore_preview", pk=backup.pk)
    return render(request, "backups/restore_upload.html", {"max_mb": settings.MAX_BACKUP_UPLOAD_MB})


@admin_required
@require_http_methods(["GET", "POST"])
def backup_delete(request, pk):
    """Delete one import backup ("Before import" / "After import") after a confirmation. Other kinds are
    removed by the automatic clean-up only."""
    backup = get_object_or_404(BackupFile.objects.defer("data"), pk=pk, kind__in=KEEP_KINDS)
    if request.method == "POST":
        name = backup.filename
        backup.delete()
        messages.success(request, f"Deleted the backup {name}.")
        return redirect("backup_list")
    return render(request, "backups/backup_confirm_delete.html", {"backup": backup})


def _load_document(backup):
    raw = bytes(backup.data)
    if hashlib.sha256(raw).hexdigest() != backup.sha256:
        raise services.BackupError("This stored backup does not match its checksum and may be damaged.")
    return services.parse_backup(raw, _max_bytes())


@admin_required
@require_http_methods(["GET", "POST"])
def restore_preview(request, pk):
    backup = get_object_or_404(BackupFile.objects.defer("data"), pk=pk)
    full = BackupFile.objects.get(pk=pk)
    try:
        document = _load_document(full)
    except services.BackupError as exc:
        messages.error(request, str(exc))
        return redirect("backup_list")

    if request.method == "POST":
        if request.POST.get("confirm", "").strip() != CONFIRM_WORD:
            messages.error(request, f"Nothing was changed. Type the word {CONFIRM_WORD} to confirm.")
            return redirect("restore_preview", pk=pk)
        try:
            services.restore_backup(document, request.user)
        except services.BackupError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Restore finished. A safety backup of the earlier data was taken first.")
        return redirect("backup_list")

    rows = services.preview_restore(document)
    return render(
        request,
        "backups/restore_preview.html",
        {
            "backup": backup,
            "rows": rows,
            "profiles": services.profile_summary(document),
            "legacy_note": " ".join(filter(None, [
                services.legacy.describe(document.get("legacy_mapping") or services.legacy.new_stats()),
                services.nested_conversion.describe(
                    document.get("nested_mapping") or services.nested_conversion.new_stats()),
            ])),
            "confirm_word": CONFIRM_WORD,
        },
    )
