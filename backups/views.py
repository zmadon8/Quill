import hashlib
import io
import os
import re

from django.conf import settings
from django.contrib import messages
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from accounts.permissions import admin_required

from . import services
from .models import BackupFile, BackupLog

CONFIRM_WORD = "RESTORE"


def _max_bytes():
    return settings.MAX_BACKUP_UPLOAD_MB * 1024 * 1024


@admin_required
def backup_list(request):
    backups = BackupFile.objects.defer("data").order_by("-created_at", "-id")
    logs = BackupLog.objects.select_related("created_by").order_by("-started_at", "-id")[:30]
    return render(request, "backups/backup_list.html", {"backups": backups, "logs": logs})


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
        content_type="application/gzip",
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
        {"backup": backup, "rows": rows, "confirm_word": CONFIRM_WORD},
    )
