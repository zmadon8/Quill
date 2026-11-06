"""Backup retention (keep the newest N) and staleness rules.

PURE PYTHON on purpose: no Django imports, so these rules can be tested with
plain ``unittest`` even where Django is not installed.
"""
from datetime import timedelta

DEFAULT_KEEP_COUNT = 30


def effective_keep_count(value):
    """The number of backups to keep is never below 1; an unreadable value means the default."""
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return DEFAULT_KEEP_COUNT


def select_over_count(entries, keep_count, protect_ids=()):
    """Return the ids of backups that may be deleted so only the newest ``keep_count`` remain.

    ``entries`` is a list of ``(id, created_at)``. Every kind of backup counts the same. Ids in
    ``protect_ids`` (for example the backup just made) are never returned. The newest entry is
    ALWAYS kept, so pruning can never leave the system with no backup at all.
    """
    entries = sorted(entries, key=lambda entry: (entry[1], entry[0]), reverse=True)
    keep = effective_keep_count(keep_count)
    protected = set(protect_ids)
    return [entry_id for entry_id, _created in entries[keep:] if entry_id not in protected]


def is_stale(last_success_at, now, stale_hours):
    """True when there has been no successful backup within ``stale_hours``."""
    if last_success_at is None:
        return True
    return now - last_success_at > timedelta(hours=stale_hours)
