"""Permanent removal of deleted profiles after the retention period (see docs/DESIGN.md, Profiles).

The job refuses to delete anything unless a backup taken today succeeded, so a profile's data is
always in a fresh backup before it is gone for good.
"""
from datetime import timedelta

from django.conf import settings
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
    for model in registry.profile_models_for(profile.program):
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


def purgeable_history(now=None):
    """VersionHistory rows that may go: older than the window, not the newest version of their record, and not
    part of an Undo group that still has a row inside the window (so a recent Undo keeps working)."""
    from django.db.models import F, OuterRef, Q, Subquery

    from diary.models import VersionHistory

    cutoff = (now or timezone.now()) - timedelta(days=settings.HISTORY_RETENTION_DAYS)
    newest = (
        VersionHistory.objects.filter(
            profile=OuterRef("profile"), record_type=OuterRef("record_type"), record_id=OuterRef("record_id")
        )
        .order_by("-version")
        .values("version")[:1]
    )
    recent_groups = VersionHistory.objects.filter(changed_at__gte=cutoff, group__isnull=False).values("group")
    return (
        VersionHistory.objects.filter(changed_at__lt=cutoff)
        .annotate(newest_version=Subquery(newest))
        .exclude(version=F("newest_version"))
        .filter(Q(group__isnull=True) | ~Q(group__in=recent_groups))
    )


def purge_old_history(now=None, chunk=1000):
    """Delete edit history past ``HISTORY_RETENTION_DAYS``. Returns the PurgeLog row, or None if nothing is due.

    Same safety rule as the profile purge: refuses (and logs) unless a backup taken today succeeded, so the
    history is always in a fresh backup before it goes.
    """
    from diary.models import VersionHistory

    now = now or timezone.now()
    ids = list(purgeable_history(now).values_list("pk", flat=True))
    if not ids:
        return None
    days = settings.HISTORY_RETENTION_DAYS
    if not todays_backup_ok(now):
        return PurgeLog.objects.create(
            ran_at=now,
            success=False,
            message=f"Edit history not trimmed: no successful backup was taken today. {len(ids)} old version(s) are waiting.",
        )
    removed = 0
    with transaction.atomic():
        for start in range(0, len(ids), chunk):
            removed += VersionHistory.objects.filter(pk__in=ids[start:start + chunk]).delete()[0]
    return PurgeLog.objects.create(
        ran_at=now,
        success=True,
        message=f"Edit history older than {days} days trimmed (the newest version of every record is kept).",
        counts={"diary.VersionHistory": removed},
    )
