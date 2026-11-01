"""Backup retention and staleness rules.

PURE PYTHON on purpose: no Django imports, so these rules can be tested with
plain ``unittest`` even where Django is not installed.
"""
from datetime import timedelta

MIN_RETENTION_DAYS = 30


def effective_retention_days(value):
    """Retention is never shorter than 30 days, whatever the setting says."""
    return max(MIN_RETENTION_DAYS, int(value))


def select_expired(entries, now, retention_days):
    """Return the ids of backups that may be deleted.

    ``entries`` is a list of ``(id, created_at)``. A backup is expired when it
    is older than the effective retention period. The newest entry is ALWAYS
    kept, so pruning can never leave the system with no backup at all.
    """
    entries = list(entries)
    if not entries:
        return []
    cutoff = now - timedelta(days=effective_retention_days(retention_days))
    newest_id = max(entries, key=lambda entry: (entry[1], entry[0]))[0]
    return [entry_id for entry_id, created_at in entries if created_at < cutoff and entry_id != newest_id]


def is_stale(last_success_at, now, stale_hours):
    """True when there has been no successful backup within ``stale_hours``."""
    if last_success_at is None:
        return True
    return now - last_success_at > timedelta(hours=stale_hours)
