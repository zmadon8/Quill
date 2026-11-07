"""Clear all Fee Register data of one profile (T4.4, R-SET-5, ports ``clearAllData``).

``clear_all(profile, confirmation, user=None)``:

1. the typed confirmation must equal the profile name (exactly, after trimming), else ``INVALID_CONFIRMATION``;
2. the heavy-operation lock (``heavy_operation("clear_all")``) is taken (R-NFR-6);
3. a ``pre_clear`` suite backup is taken FIRST, outside the transaction (the same safety net the diary
   clear uses). If it fails nothing is deleted. The suite backup carries everything, including the
   Word template and signature bytes;
4. in one transaction this profile's fee rows are deleted child first, the settings row is reset to
   defaults (``data_version`` keeps counting up), and ``touch`` bumps the version and drops the
   profile's ``StatsCache`` rows.

Only this profile is touched: every delete filters on ``profile``. The Word template (``WordTemplate``,
including the signature image) is an uploaded asset and not data, so it is kept (it stays in the
pre-clear backup either way). The view layer (Phase 7) offers the Excel backup download before it calls
this, as the original did.

``wipe_profile_data`` and ``reset_settings`` are shared with the Excel restore.
"""
import logging

from django.db import transaction

from fees.errors import FeesError
from fees.models import (
    Allocation,
    BankAccount,
    FeesSettings,
    Firm,
    Group,
    Matter,
    Memo,
    NumberSequence,
    Payment,
    PeriodAdjustment,
    SavedView,
)
from fees.services.heavy import heavy_operation
from fees.services.memos import touch

__all__ = ["DELETE_ORDER", "wipe_profile_data", "reset_settings", "check_confirmation", "clear_all"]

logger = logging.getLogger(__name__)

#: Data models deleted by a clear or a restore, children first (``Allocation`` and ``Memo`` are
#: PROTECT-ed, so allocations go before payments and memos, memos before matters, matters before
#: groups, groups before firms). ``FeesSettings`` and ``WordTemplate`` are not deleted.
DELETE_ORDER = [
    SavedView,
    Allocation,
    PeriodAdjustment,
    Payment,
    Memo,
    Matter,
    Group,
    Firm,
    BankAccount,
    NumberSequence,
]

_BATCH = 500
_KEEP_FIELDS = {"id", "profile", "data_version", "created_at", "updated_at"}


def wipe_profile_data(profile):
    """Delete this profile's fee rows child first, in batches of 500 ids (flat memory).

    Returns ``{model label: rows deleted}`` (rows removed by cascade are not counted). Call inside a
    transaction.
    """
    counts = {}
    for model in DELETE_ORDER:
        deleted = 0
        while True:
            ids = list(model.objects.filter(profile=profile).values_list("pk", flat=True)[:_BATCH])
            if not ids:
                break
            model.objects.filter(pk__in=ids).delete()
            deleted += len(ids)
        counts[model._meta.label] = deleted
    return counts


def reset_settings(profile):
    """Reset every setting of the profile to its model default; return the saved ``FeesSettings``.

    ``data_version`` is left alone (it must keep counting up so a cached statistics result can never
    look current). The caller bumps it with ``touch``.
    """
    settings, _created = FeesSettings.objects.get_or_create(profile=profile)
    for field in FeesSettings._meta.concrete_fields:
        if field.name not in _KEEP_FIELDS:
            setattr(settings, field.name, field.get_default())
    settings.save()
    return settings


def check_confirmation(profile, confirmation):
    """Raise ``INVALID_CONFIRMATION`` unless ``confirmation`` is the profile name (trimmed, exact)."""
    if (confirmation or "").strip() != (profile.name or "").strip():
        raise FeesError(
            "INVALID_CONFIRMATION",
            "Type the name of this profile exactly to confirm. Nothing was deleted.",
        )


def _default_backup(kind, user):
    from backups import services

    return services.create_backup(kind, user)


def clear_all(profile, confirmation, user=None, backup_func=None):
    """Back up, then delete every fee row of ``profile`` and reset its settings.

    Returns ``{"counts": {model label: rows deleted}, "backup_id": id of the pre_clear backup or None}``.
    ``backup_func(kind, user)`` defaults to the suite ``create_backup``; a test may pass a stub.
    Raises ``FeesError("INVALID_CONFIRMATION")`` (nothing done) or ``FeesError("CLEAR_FAILED")`` (the
    safety backup failed, so nothing was deleted). ``Busy`` propagates when another heavy job runs.
    """
    check_confirmation(profile, confirmation)
    backup_func = backup_func or _default_backup
    with heavy_operation("clear_all"):
        try:
            backup = backup_func("pre_clear", user)
        except Exception as exc:
            logger.exception("Safety backup before clear-all failed")
            raise FeesError(
                "CLEAR_FAILED",
                f"The safety backup could not be made, so nothing was deleted. ({exc})",
            ) from exc
        from accounts.models import Profile

        with transaction.atomic():
            # Serialise with a restore or another clear on the same profile.
            Profile.objects.select_for_update().get(pk=profile.pk)
            counts = wipe_profile_data(profile)
            reset_settings(profile)
            touch(profile)
    return {"counts": counts, "backup_id": getattr(backup, "pk", None)}
