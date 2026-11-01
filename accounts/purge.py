"""Permanent removal of deleted profiles after the retention period (see docs/DESIGN.md, Profiles).

The job refuses to delete anything unless a backup taken today succeeded, so a profile's data is
always in a fresh backup before it is gone for good.
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from backups import registry
from backups.models import BackupLog

from .models import Profile, PurgeLog
from .profiles import retention_days


def expired_profiles(now=None):
    now = now or timezone.now()
    return Profile.objects.filter(deleted_at__isnull=False, deleted_at__lte=now - timedelta(days=retention_days()))


def todays_backup_ok(now=None):
    """True if the latest daily or manual backup attempt made today (local date) succeeded."""
    today = timezone.localdate(now)
    latest = None
    for log in BackupLog.objects.filter(kind__in=["daily", "manual"]).order_by("-started_at", "-id")[:20]:
        if timezone.localdate(log.started_at) == today:
            latest = log
            break
    return bool(latest and latest.success and latest.backup_id)


def _purge_one(profile):
    counts = {}
    diary_models = [model for model in registry.get_models() if model._meta.label in registry.PROFILE_MODELS]
    for model in reversed(diary_models):
        _total, per_label = model._base_manager.filter(profile=profile).delete()
        for label, number in per_label.items():
            counts[label] = counts.get(label, 0) + number
    _total, per_label = profile.delete()
    for label, number in per_label.items():
        counts[label] = counts.get(label, 0) + number
    return counts


def purge_expired_profiles(now=None):
    """Permanently delete profiles past the window, with all their data, in one transaction.

    Returns the PurgeLog row, or None if there was nothing to purge. Refuses (and logs) if today's
    backup did not succeed.
    """
    now = now or timezone.now()
    profiles = list(expired_profiles(now).order_by("id"))
    if not profiles:
        return None
    names = ", ".join(f"{p.name} (#{p.pk})" for p in profiles)
    if not todays_backup_ok(now):
        return PurgeLog.objects.create(
            ran_at=now,
            success=False,
            message=f"Nothing removed: no successful backup was taken today. Waiting to remove: {names}.",
        )
    totals = {}
    with transaction.atomic():
        for profile in profiles:
            for label, number in _purge_one(profile).items():
                totals[label] = totals.get(label, 0) + number
    return PurgeLog.objects.create(
        ran_at=now,
        success=True,
        message=f"Removed {len(profiles)} deleted profile(s): {names}.",
        counts=totals,
    )
