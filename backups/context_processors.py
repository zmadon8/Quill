from django.conf import settings
from django.utils import timezone

from . import policy
from .models import BackupLog

BACKUP_KINDS = ["daily", "manual", "pre_restore", "pre_migration"]


def backup_banner(request):
    """Warn Admins at the top of every page if backups are failing or old."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or not user.is_admin:
        return {"backup_warning": None}

    logs = BackupLog.objects.filter(kind__in=BACKUP_KINDS)
    latest = logs.order_by("-started_at", "-id").first()
    if latest is not None and not latest.success:
        when = timezone.localtime(latest.started_at).strftime("%Y-%m-%d %H:%M")
        return {"backup_warning": f"The last backup FAILED ({when} UTC). Open Backups."}

    last_ok = logs.filter(success=True).order_by("-started_at", "-id").first()
    last_ok_at = last_ok.started_at if last_ok else None
    hours = settings.BACKUP_STALE_HOURS
    if policy.is_stale(last_ok_at, timezone.now(), hours):
        return {"backup_warning": f"No successful backup in the last {hours} hours."}
    return {"backup_warning": None}
