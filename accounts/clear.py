"""Delete ALL diary data of one profile (the profile, its name, export name and members stay).

A dedicated "Before clearing profile" backup is made and committed first; if it fails nothing is
deleted. The deletion is one transaction with the Profile row locked, the same lock the Word import
takes, so it cannot overlap an import into that profile.
"""
from django.db import DatabaseError, transaction
from django.db.models import Max
from django.utils import timezone

from backups import registry, services

from .models import Profile, PurgeLog, forget_copy


class ClearRefused(Exception):
    """Nothing was deleted; the message is plain language for the Admin."""


def _models(profile):
    """The profile-scoped models of ``profile``'s program, parents first (for preview and fingerprint)."""
    return list(reversed(registry.profile_models_for(profile.program)))


def clear_preview(profile):
    """[(record type name, count)] of every diary row of ``profile``, trashed and imported rows included."""
    rows = []
    for model in _models(profile):
        rows.append((model._meta.verbose_name_plural.title(), model._base_manager.filter(profile=profile).count()))
    return rows


def _fingerprint(profile):
    """Per record type: row count and newest updated_at (when the type has one)."""
    result = {}
    for model in _models(profile):
        qs = model._base_manager.filter(profile=profile)
        newest = None
        if any(f.name == "updated_at" for f in model._meta.get_fields()):
            newest = qs.aggregate(m=Max("updated_at"))["m"]
        result[model._meta.label] = (qs.count(), newest)
    return result


def clear_profile(profile, user):
    """Back up, then delete every diary row of ``profile``. Returns {model label: rows deleted}."""
    before = _fingerprint(profile)
    try:
        backup = services.create_backup("pre_clear", user)
    except Exception as exc:
        raise ClearRefused(f"The safety backup could not be made, so nothing was deleted. ({exc})")
    try:
        with transaction.atomic():
            try:
                Profile.objects.select_for_update(nowait=True).get(pk=profile.pk)
            except DatabaseError:
                raise ClearRefused("An import into this profile is running. Wait for it to finish. Nothing was deleted.")
            if _fingerprint(profile) != before:
                raise ClearRefused(
                    "The profile changed while the backup was being taken; nothing was deleted. Please try again."
                )
            counts = {}
            for model in registry.profile_models_for(profile.program):
                _total, per_label = model._base_manager.filter(profile=profile).delete()
                for label, number in per_label.items():
                    counts[label] = counts.get(label, 0) + number
            forget_copy(profile)  # the saved Offline copy holds the diary too (round 21)
    except ClearRefused:
        raise
    except Exception as exc:
        raise ClearRefused(f"Clearing failed and nothing was deleted. ({exc})")
    counts = {label: number for label, number in counts.items() if number}
    PurgeLog.objects.create(
        ran_at=timezone.now(),
        success=True,
        message=f"Cleared all diary data in profile '{profile.name}' (#{profile.pk}). "
        f"Backup first: {backup.filename}.",
        counts=counts,
    )
    return counts
