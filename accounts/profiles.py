"""Profiles: separate data spaces inside a program (see docs/DESIGN.md, Profiles).

Each user has at most one profile per program. The "default profile" helpers take the model
classes as arguments so the data migrations (which use historical models) and the tests share
exactly the same logic.
"""
from django.db import transaction

from .models import ROLE_READER, Profile, ProfileMembership
from .suite import KEY_DIARY

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
    already = membership_model.objects.filter(program=profile.program).values_list("user_id", flat=True)
    count = 0
    for user_id in user_model.objects.exclude(pk__in=list(already)).values_list("pk", flat=True):
        membership_model.objects.create(user_id=user_id, profile=profile, program=profile.program, role=role)
        count += 1
    return count


def request_profile(request, program=KEY_DIARY):
    """The signed-in user's profile for ``program``, looked up once per request (None if none)."""
    attr = f"_profile_{program}"
    if not hasattr(request, attr):
        setattr(request, attr, get_profile_for(getattr(request, "user", None), program))
    return getattr(request, attr)


def set_user_profile(user, profile, role=ROLE_READER, program=KEY_DIARY):
    """Make ``profile`` the user's only profile in ``program`` with ``role``; None removes access.

    Replaces any existing membership, so the one-per-program rule is never broken.
    """
    with transaction.atomic():
        ProfileMembership.objects.filter(user=user, program=program).exclude(profile=profile).delete()
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
