import logging

from django.conf import settings
from django.utils import timezone

from . import policy
from .models import BackupLog

logger = logging.getLogger(__name__)

BACKUP_KINDS = ["daily", "manual", "pre_restore", "pre_migration", "pre_import", "post_import", "pre_clear", "pre_inv_delete", "pre_catalogue"]


def backup_banner(request):
    try:
        return _backup_banner(request)
    except Exception:
        logger.exception("Could not work out the backup warning banner")
        return {"backup_warning": None}


def _backup_banner(request):
    """Warn Admins at the top of every page if backups are failing or old."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or not user.is_admin:
        return {"backup_warning": None}

    logs = BackupLog.objects.filter(kind__in=BACKUP_KINDS)
    latest = logs.order_by("-started_at", "-id").first()
    if latest is not None and not latest.success:
        when = timezone.localtime(latest.started_at).strftime("%Y-%m-%d %H:%M")
        return {"backup_warning": f"The last backup FAILED ({when} IST). Open Backups."}

    offsite = BackupLog.objects.filter(kind="offsite").order_by("-started_at", "-id").first()
    if offsite is not None and not offsite.success:
        when = timezone.localtime(offsite.started_at).strftime("%Y-%m-%d %H:%M")
        what = "clean-up" if offsite.message.startswith("Off-site clean-up") else "copy"
        return {"backup_warning": f"The off-site backup {what} FAILED ({when} IST). Open Backups."}

    emailed = _email_backup_failure()
    if emailed:
        return {"backup_warning": emailed}

    last_ok = logs.filter(success=True).order_by("-started_at", "-id").first()
    last_ok_at = last_ok.started_at if last_ok else None
    hours = settings.BACKUP_STALE_HOURS
    if policy.is_stale(last_ok_at, timezone.now(), hours):
        return {"backup_warning": f"No successful backup in the last {hours} hours."}
    return {"backup_warning": None}


def _email_backup_failure():
    """A warning line if emailed backups are switched on and the latest send failed, else ""."""
    from mailer.models import EmailBackupSchedule

    schedule = EmailBackupSchedule.objects.filter(pk=1, enabled=True).first()
    if schedule is None or schedule.last_ok is not False or schedule.last_attempt_at is None:
        return ""
    when = timezone.localtime(schedule.last_attempt_at).strftime("%Y-%m-%d %H:%M")
    return f"The emailed backup FAILED ({when} IST). Open Backups, then Email backups."
