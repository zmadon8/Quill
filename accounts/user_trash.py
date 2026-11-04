"""Deleted users (round 18, D94): kept for ``USER_RETENTION_DAYS`` (30) so an Admin can restore them.

Deleting a user turns their account off (they cannot sign in, and any session they had stops working) and lists them
under "Deleted users" on the Users page. Nothing else changes: their profiles, roles, settings and edit history stay
exactly as they were, so Restore brings the account back as it was. Their username and email address stay taken while
they are deleted. After the window, the nightly job removes them for good, but only if that night's backup succeeded
(the same rule as for deleted profiles). Their edits stay in the diary's history, without a name.
"""
import math
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import PurgeLog


def retention_days():
    return settings.USER_RETENTION_DAYS


def live_users():
    return get_user_model().objects.filter(deleted_at__isnull=True)


def deleted_users():
    return get_user_model().objects.filter(deleted_at__isnull=False)


def days_left(user, now=None):
    """Whole days left to restore a deleted user (0 once the window has passed)."""
    due = user.deleted_at + timedelta(days=retention_days())
    return max(0, math.ceil((due - (now or timezone.now())).total_seconds() / 86400))


def delete_user(user, by=None):
    """Soft delete: switch the account off and remember whether it was on, for Restore."""
    with transaction.atomic():
        user.was_active = user.is_active
        user.is_active = False
        user.deleted_at = timezone.now()
        user.deleted_by_name = (getattr(by, "username", "") or "")[:150]
        user.save(update_fields=["was_active", "is_active", "deleted_at", "deleted_by_name"])


def restore_user(user):
    """Bring a deleted user back exactly as they were (switched on again if they were on)."""
    with transaction.atomic():
        user.is_active = user.was_active
        user.deleted_at = None
        user.deleted_by_name = ""
        user.save(update_fields=["is_active", "deleted_at", "deleted_by_name"])


def expired_users(now=None):
    now = now or timezone.now()
    return deleted_users().filter(deleted_at__lte=now - timedelta(days=retention_days()))


def purge_expired_users(now=None):
    """Permanently delete users past the window. Returns the PurgeLog row, or None if nobody is due.

    Refuses (and logs) unless a backup taken today succeeded, so the account is in a fresh backup first.
    """
    from .purge import todays_backup_ok  # lazy: purge imports the backups app

    now = now or timezone.now()
    users = list(expired_users(now).order_by("pk"))
    if not users:
        return None
    names = ", ".join(f"{u.username} (#{u.pk})" for u in users)
    if not todays_backup_ok(now):
        return PurgeLog.objects.create(
            ran_at=now, success=False,
            message=f"No users removed: no successful backup was taken today. Waiting to remove: {names}.",
        )
    totals = {}
    with transaction.atomic():
        for user in users:
            _total, per_label = user.delete()
            for label, number in per_label.items():
                totals[label] = totals.get(label, 0) + number
    return PurgeLog.objects.create(
        ran_at=now, success=True, message=f"Removed {len(users)} deleted user(s): {names}.", counts=totals,
    )
