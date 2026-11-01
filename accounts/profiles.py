"""Profiles: separate data spaces inside a program (see docs/DESIGN.md, Profiles).

Each user has at most one profile per program. The "default profile" helpers take the model
classes as arguments so the data migrations (which use historical models) and the tests share
exactly the same logic.
"""
from .models import Profile, ProfileMembership
from .suite import KEY_DIARY

DEFAULT_PROFILE_NAME = "Main"


def get_profile_for(user, program=KEY_DIARY):
    """The live profile ``user`` may use in ``program``, or None if there is none."""
    if user is None or not getattr(user, "pk", None):
        return None
    membership = (
        ProfileMembership.objects.filter(user=user, program=program, profile__deleted_at__isnull=True)
        .select_related("profile")
        .first()
    )
    return membership.profile if membership else None


def ensure_default_profile(profile_model=Profile, program=KEY_DIARY, name=DEFAULT_PROFILE_NAME):
    """Return the live profile called ``name`` in ``program``, creating it if missing."""
    found = profile_model.objects.filter(program=program, name__iexact=name, deleted_at__isnull=True).first()
    if found is not None:
        return found
    return profile_model.objects.create(program=program, name=name)


def assign_unassigned_users(user_model, membership_model, profile):
    """Give every user who has no profile in ``profile.program`` access to ``profile``.

    Users who already have a profile in that program are left alone (one per program).
    Returns the number of users assigned.
    """
    already = membership_model.objects.filter(program=profile.program).values_list("user_id", flat=True)
    count = 0
    for user_id in user_model.objects.exclude(pk__in=list(already)).values_list("pk", flat=True):
        membership_model.objects.create(user_id=user_id, profile=profile, program=profile.program)
        count += 1
    return count
