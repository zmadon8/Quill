"""Profiles: separate data spaces inside a program (see docs/DESIGN.md, Profiles).

Each user has at most one profile per program. The "default profile" helpers take the model
classes as arguments so the data migrations (which use historical models) and the tests share
exactly the same logic.
"""
import math
import re
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import ROLE_READER, Profile, ProfileMembership
from .suite import KEY_DIARY, get_names

DEFAULT_PROFILE_NAME = "Main"


def get_membership_for(user, program=KEY_DIARY):
    """The user's membership of a live profile in ``program`` (with the profile loaded), or None."""
    if user is None or not getattr(user, "pk", None):
        return None
    return (
        ProfileMembership.objects.filter(user=user, program=program, profile__deleted_at__isnull=True)
        .select_related("profile")
        .first()
    )


def get_profile_for(user, program=KEY_DIARY):
    """The live profile ``user`` may use in ``program``, or None if there is none."""
    membership = get_membership_for(user, program)
    return membership.profile if membership else None


def ensure_default_profile(profile_model=Profile, program=KEY_DIARY, name=DEFAULT_PROFILE_NAME):
    """Return the live profile called ``name`` in ``program``, creating it if missing."""
    found = profile_model.objects.filter(program=program, name__iexact=name, deleted_at__isnull=True).first()
    if found is not None:
        return found
    return profile_model.objects.create(program=program, name=name)


def assign_unassigned_users(user_model, membership_model, profile, role=ROLE_READER):
    """Give every user who has no profile in ``profile.program`` access to ``profile``.

    Users who already have a profile in that program are left alone (one per program).
    Returns the number of users assigned.
    """
    memberships = membership_model.objects.filter(program=profile.program)
    if any(field.name == "suspended" for field in membership_model._meta.get_fields()):
        # Memberships of deleted profiles do not count (older migrations run before this column exists).
        memberships = memberships.filter(suspended=False)
    already = memberships.values_list("user_id", flat=True)
    count = 0
    for user_id in user_model.objects.exclude(pk__in=list(already)).values_list("pk", flat=True):
        membership_model.objects.create(user_id=user_id, profile=profile, program=profile.program, role=role)
        count += 1
    return count


def request_profile(request, program=KEY_DIARY):
    """The signed-in user's profile for ``program``, looked up once per request (None if none)."""
    attr = f"_profile_{program}"
    if not hasattr(request, attr):
        membership = get_membership_for(getattr(request, "user", None), program)
        setattr(request, f"_membership_{program}", membership)
        setattr(request, attr, membership.profile if membership else None)
    return getattr(request, attr)


def request_role(request, program=KEY_DIARY):
    """The signed-in user's role in ``program`` for this request ("editor", "reader" or None); no extra query."""
    request_profile(request, program)
    membership = getattr(request, f"_membership_{program}", None)
    return membership.role if membership else None


def set_user_profile(user, profile, role=ROLE_READER, program=KEY_DIARY):
    """Make ``profile`` the user's only profile in ``program`` with ``role``; None removes access.

    Replaces any existing membership, so the one-per-program rule is never broken.
    """
    with transaction.atomic():
        # Suspended memberships (of deleted profiles) are kept so those profiles stay restorable.
        ProfileMembership.objects.filter(user=user, program=program, suspended=False).exclude(
            profile=profile
        ).delete()
        if profile is not None:
            membership, created = ProfileMembership.objects.get_or_create(
                user=user, profile=profile, defaults={"program": program, "role": role}
            )
            if not created and membership.role != role:
                membership.role = role
                membership.save(update_fields=["role"])


def profile_usage(profile):
    """(members, live diary subjects) counts, used to refuse deleting a profile in use."""
    from diary.models import Subject

    members = ProfileMembership.objects.filter(profile=profile).count()
    subjects = Subject.objects.filter(profile=profile, deleted_at__isnull=True).count()
    return members, subjects


def retention_days():
    return settings.PROFILE_RETENTION_DAYS


def purge_due(profile):
    """When a deleted profile becomes eligible for the purge job."""
    return profile.deleted_at + timedelta(days=retention_days())


def days_left(profile, now=None):
    """Whole days left to restore a deleted profile (0 once the window has passed)."""
    seconds = (purge_due(profile) - (now or timezone.now())).total_seconds()
    return max(0, math.ceil(seconds / 86400))


def delete_profile(profile, user=None):
    """Soft delete: hide the profile, suspend its memberships (kept for a restore), note who did it."""
    with transaction.atomic():
        ProfileMembership.objects.filter(profile=profile).update(suspended=True)
        profile.deleted_at = timezone.now()
        profile.deleted_by = user if user is not None and getattr(user, "pk", None) else None
        profile.save(update_fields=["deleted_at", "deleted_by", "updated_at"])


def restore_conflicts(profile):
    """Users of a deleted profile who were given another profile in the same program meanwhile."""
    suspended = ProfileMembership.objects.filter(profile=profile, suspended=True).values_list("user_id", flat=True)
    taken = ProfileMembership.objects.filter(
        program=profile.program, suspended=False, user_id__in=list(suspended)
    ).select_related("user")
    return sorted({m.user.username for m in taken}, key=str.lower)


def name_clash(profile):
    """True if a live profile in the same program already has this profile's name (ignoring case)."""
    return Profile.objects.filter(
        program=profile.program, name__iexact=profile.name, deleted_at__isnull=True
    ).exclude(pk=profile.pk).exists()


def restore_profile(profile):
    """Bring a deleted profile back exactly as it was, with its members. Callers check conflicts first."""
    with transaction.atomic():
        ProfileMembership.objects.filter(profile=profile).update(suspended=False)
        profile.deleted_at = None
        profile.deleted_by = None
        profile.save(update_fields=["deleted_at", "deleted_by", "updated_at"])


_ILLEGAL_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')


def effective_export_name(profile):
    """The name this profile's exported files start with: its own ``export_name`` or the default.

    The default is "<program display name> <profile name>", for example "Case Law Diary Main".
    """
    custom = " ".join((profile.export_name or "").split())
    if custom:
        return custom
    return f"{get_names().get(profile.program, profile.program)} {profile.name}"


def safe_file_name(name):
    """``name`` made safe as a file name: illegal characters removed, spaces tidied, no edge dots."""
    cleaned = _ILLEGAL_FILENAME_CHARS.sub("", name or "")
    return " ".join(cleaned.split()).strip(". ")


def export_file_name(profile):
    """File-name-safe version of the profile's effective export name (never empty)."""
    return safe_file_name(effective_export_name(profile)) or safe_file_name(profile.name) or "Export"
