"""Profiles: separate data spaces inside a program (see docs/DESIGN.md, Profiles).

A user may have several profiles in a program (round 18, D95), each with its own role; the one in use is the one
used most recently (switched to from the header or the Home page). The "default profile" helpers take the model
classes as arguments so the data migrations (which use historical models) and the tests share
exactly the same logic.
"""
import math
import re
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.db.models.functions import Lower
from django.utils import timezone

from .models import ROLE_EDITOR, ROLE_READER, Profile, ProfileMembership
from .programs import program_keys
from .suite import KEY_DIARY, KEY_FEES, KEY_INVESTMENTS, get_names

DEFAULT_PROFILE_NAME = "Main"


def live_memberships(user, program=KEY_DIARY, raw=False):
    """Every membership of ``user`` that gives access in ``program`` (live profile, not suspended), the one in use first.

    In use: the one switched to most recently; never-used ones follow by profile name. Profiles are loaded too.
    ``program=None`` returns the memberships of every program (one query), in the same order.

    A suite Admin is an Admin in every program (the owner's rule): unless ``raw`` is True they get every live profile
    of ``program`` as an Editor, with or without a membership (the ones without are unsaved stand-ins). ``raw=True``
    gives only the stored memberships, with their stored roles (the Users screens). Non-Admins cost one query.
    """
    if user is None or not getattr(user, "pk", None):
        return []
    found = ProfileMembership.objects.filter(user=user, suspended=False, profile__deleted_at__isnull=True)
    if program is not None:
        found = found.filter(program=program)
    memberships = list(
        found
        .select_related("profile")
        .order_by(F("last_used_at").desc(nulls_last=True), Lower("profile__name"), "pk")
    )
    if raw or not getattr(user, "is_admin", False):
        return memberships
    return _admin_memberships(user, program, memberships)


def _admin_memberships(user, program, memberships):
    """An Admin's view of ``memberships``: Editor everywhere, plus a stand-in for each live profile with no membership.

    Order: the Admin's own memberships (the profile used most recently first, then by name), then the other profiles
    by name. So an Admin with no memberships uses the first profile by name until they switch to another.
    """
    has = {m.profile_id for m in memberships}
    for m in memberships:
        m.role = ROLE_EDITOR  # in memory only: the stored role is untouched
    profiles = Profile.objects.filter(deleted_at__isnull=True).exclude(pk__in=has)
    if program is not None:
        profiles = profiles.filter(program=program)
    standins = [
        ProfileMembership(user=user, profile=p, program=p.program, role=ROLE_EDITOR)
        for p in profiles.order_by(Lower("name"), "pk")
    ]
    # Their own profiles come first (already in order); profiles they have no membership in follow, by name.
    return memberships + standins


def get_membership_for(user, program=KEY_DIARY):
    """The user's membership of the live profile they are using in ``program`` (with the profile loaded), or None."""
    memberships = live_memberships(user, program)
    return memberships[0] if memberships else None


def use_profile(user, profile):
    """Make ``profile`` the one ``user`` is using (from now on, on every device). False if they may not use it.

    A suite Admin may use any live profile; one without a membership gets a Reader membership to record the choice
    (they still work as an Editor, since an Admin is an Admin in every program). That membership is marked
    ``admin_access``: it is not a profile given to them, so Home does not list it (Admin Profile Access does).
    """
    if getattr(user, "is_admin", False) and profile.deleted_at is None:
        membership, _ = ProfileMembership.objects.get_or_create(
            user=user, profile=profile, defaults={"program": profile.program, "role": ROLE_READER, "admin_access": True}
        )
        if membership.suspended:
            return False
        membership.last_used_at = timezone.now()
        membership.save(update_fields=["last_used_at"])
        return True
    updated = ProfileMembership.objects.filter(
        user=user, profile=profile, suspended=False, profile__deleted_at__isnull=True
    ).update(last_used_at=timezone.now())
    return bool(updated)


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
        # One query for every program: the header asks for the diary and the Fee Register on each page.
        everything = live_memberships(getattr(request, "user", None), None)
        # Every known program is filled in, so asking about one the user has no access to costs nothing more.
        for key in {program, KEY_DIARY, KEY_FEES, *program_keys(), *(m.program for m in everything)}:
            memberships = [m for m in everything if m.program == key]
            membership = memberships[0] if memberships else None
            setattr(request, f"_memberships_{key}", memberships)
            setattr(request, f"_membership_{key}", membership)
            setattr(request, f"_profile_{key}", membership.profile if membership else None)
    return getattr(request, attr)


def request_memberships(request, program=KEY_DIARY):
    """All the signed-in user's live memberships in ``program`` for this request (the one in use first); no extra query."""
    request_profile(request, program)
    return getattr(request, f"_memberships_{program}", [])


def request_role(request, program=KEY_DIARY):
    """The signed-in user's role in ``program`` for this request ("editor", "reader" or None); no extra query."""
    request_profile(request, program)
    membership = getattr(request, f"_membership_{program}", None)
    return membership.role if membership else None


def set_user_profiles(user, roles, program=KEY_DIARY):
    """Give ``user`` exactly the live profiles in ``roles`` ({profile: role}) in ``program``; others are taken away.

    Memberships of deleted profiles (suspended) are kept, so those profiles stay restorable with their members. A kept
    membership keeps its "last used" time, so the user stays in the profile they were using if they still have it.
    """
    with transaction.atomic():
        keep = [p.pk for p in roles]
        ProfileMembership.objects.filter(user=user, program=program, suspended=False, admin_access=False).exclude(
            profile_id__in=keep
        ).delete()
        for profile, role in roles.items():
            membership, created = ProfileMembership.objects.get_or_create(
                user=user, profile=profile, defaults={"program": program, "role": role}
            )
            if not created and (membership.role != role or membership.admin_access):
                membership.role = role
                membership.admin_access = False  # now given on purpose
                membership.save(update_fields=["role", "admin_access"])


def set_user_profile(user, profile, role=ROLE_READER, program=KEY_DIARY):
    """Make ``profile`` the user's only profile in ``program`` with ``role``; None removes access (first Admin, tests)."""
    set_user_profiles(user, {profile: role} if profile is not None else {}, program)


def profile_usage(profile):
    """(members, live records) counts, used to refuse deleting a profile in use.

    Records are the diary's Subjects, a Fee Register profile's Memos, or an Investments profile's transactions.
    """
    members = ProfileMembership.objects.filter(profile=profile, user__deleted_at__isnull=True).count()
    if profile.program == KEY_FEES:
        from fees.models import Memo

        return members, Memo.objects.filter(profile=profile).count()
    if profile.program == KEY_INVESTMENTS:
        from investments.services import usage

        return members, usage.record_count(profile)
    from diary.models import Subject

    subjects = Subject.objects.filter(profile=profile, deleted_at__isnull=True).count()
    return members, subjects


def profile_usage_map(profiles):
    """``{profile pk: (members, records)}`` for many profiles in two grouped queries (no per-profile queries)."""
    from django.db.models import Count

    profiles = list(profiles)
    pks = [p.pk for p in profiles]
    members = dict(
        ProfileMembership.objects.filter(profile_id__in=pks, user__deleted_at__isnull=True)
        .values_list("profile_id").annotate(n=Count("pk")).order_by()
    )
    fees_pks = [p.pk for p in profiles if p.program == KEY_FEES]
    inv_pks = [p.pk for p in profiles if p.program == KEY_INVESTMENTS]
    diary_pks = [p.pk for p in profiles if p.program not in (KEY_FEES, KEY_INVESTMENTS)]
    records = {}
    if inv_pks:
        from investments.services import usage

        records.update(usage.record_counts(inv_pks))
    if fees_pks:
        from fees.models import Memo

        records.update(Memo.objects.filter(profile_id__in=fees_pks).values_list("profile_id").annotate(n=Count("pk")).order_by())
    if diary_pks:
        from diary.models import Subject

        records.update(
            Subject.objects.filter(profile_id__in=diary_pks, deleted_at__isnull=True)
            .values_list("profile_id").annotate(n=Count("pk")).order_by()
        )
    return {pk: (members.get(pk, 0), records.get(pk, 0)) for pk in pks}


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
    """``name`` made safe as a file name: each illegal character becomes '-' (DESIGN 12.2), spaces tidied, no edge dots."""
    cleaned = _ILLEGAL_FILENAME_CHARS.sub("-", name or "")
    return " ".join(cleaned.split()).strip(". ")


def export_file_name(profile):
    """File-name-safe version of the profile's effective export name (never empty)."""
    return safe_file_name(effective_export_name(profile)) or safe_file_name(profile.name) or "Export"
