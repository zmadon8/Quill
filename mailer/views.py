from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from accounts.permissions import admin_required

from . import services
from .forms import EmailBackupForm
from .models import EmailBackupSchedule


def email_context(form=None):
    """What the Email backups section of the Admin Backups page shows (``form`` is a bound form after an error)."""
    schedule = EmailBackupSchedule.load()
    return {
        "email_form": form or EmailBackupForm(instance=schedule), "schedule": schedule,
        "configured": services.is_configured(), "max_mb": settings.EMAIL_BACKUP_MAX_MB,
        "due": services.is_due(schedule), "backup_size": services.newest_backup_size(),
    }


def _back_to_email():
    return redirect(reverse("backup_list") + "?tab=email")


@admin_required
@require_http_methods(["GET", "POST"])
def backup_email(request):
    """Admin only. Email backups are a section of the Backups page now: the old address redirects there. The form on
    that page posts here to set up emailed backups, send one now, or send a test email."""
    if request.method == "GET":
        return _back_to_email()
    schedule = EmailBackupSchedule.load()
    action = request.POST.get("action", "save")
    form = EmailBackupForm(request.POST, instance=schedule)
    if action == "test":
        # The test uses the addresses typed in the form (even unsaved), else the Admin's own address.
        addresses, error = services.check_recipients(request.POST.get("recipients", ""))
        if error:
            messages.error(request, error)
        else:
            ok, message = services.send_test_email(addresses or ([request.user.email] if request.user.email else []))
            (messages.success if ok else messages.error)(request, message if ok else f"The test email FAILED: {message}")
        return _back_to_email()
    if form.is_valid():
        saved = form.save(commit=False)
        saved.owner = request.user
        saved.save()
        if action == "send_now":
            ok, message = services.send_scheduled_backup(saved)
            (messages.success if ok else messages.error)(request, message if ok else f"The email FAILED: {message}")
        else:
            messages.success(request, "Saved.")
        return _back_to_email()
    from backups.views import render_backup_page  # lazy: backups imports this app for the shared page

    return render_backup_page(request, email_form=form, tab="email")
