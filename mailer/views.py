from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.permissions import admin_required

from . import services
from .forms import EmailBackupForm
from .models import EmailBackupSchedule


@admin_required
@require_http_methods(["GET", "POST"])
def backup_email(request):
    """Admin only: set up emailed backups, send one now, or send a test email."""
    schedule = EmailBackupSchedule.load()
    action = request.POST.get("action", "save")
    form = EmailBackupForm(request.POST or None, instance=schedule)
    if request.method == "POST":
        if action == "test":
            # The test uses the addresses typed in the form (even unsaved), else the Admin's own address.
            addresses, error = services.check_recipients(request.POST.get("recipients", ""))
            if error:
                messages.error(request, error)
            else:
                ok, message = services.send_test_email(addresses or ([request.user.email] if request.user.email else []))
                (messages.success if ok else messages.error)(request, message if ok else f"The test email FAILED: {message}")
            return redirect("backup_email")
        if form.is_valid():
            saved = form.save(commit=False)
            saved.owner = request.user
            saved.save()
            if action == "send_now":
                ok, message = services.send_scheduled_backup(saved)
                (messages.success if ok else messages.error)(request, message if ok else f"The email FAILED: {message}")
            else:
                messages.success(request, "Saved.")
            return redirect("backup_email")
    return render(request, "mailer/backup_email.html", {
        "form": form, "schedule": schedule, "configured": services.is_configured(),
        "max_mb": settings.EMAIL_BACKUP_MAX_MB, "due": services.is_due(schedule),
    })
