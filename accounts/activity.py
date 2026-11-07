"""Who is active: the Active Now and Earlier Today panel on Home (visible to Admins and to users an Admin allowed)."""
from datetime import timedelta

from django.db.models import F
from django.utils import timezone

from .models import ProfileMembership, User
from .suite import get_names

ACTIVE_MINUTES = 5


def can_see_active(user):
    """An Admin always; anyone else only when an Admin switched on Can See Who Is Active for them."""
    return bool(
        user is not None
        and user.is_authenticated
        and (user.is_admin or user.can_see_active)
    )


def active_panel():
    """Context for Home: ``show_active``, ``active_now`` and ``earlier_today`` (newest first). Two queries."""
    now = timezone.now()
    start_of_day = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    users = list(
        User.objects.filter(last_seen_at__gte=start_of_day, is_active=True, deleted_at__isnull=True)
        .order_by("-last_seen_at", "username")
    )
    where = {}
    if users:
        memberships = (
            ProfileMembership.objects.filter(
                user__in=[u.pk for u in users], suspended=False, profile__deleted_at__isnull=True
            )
            .select_related("profile")
            .order_by(F("last_used_at").desc(nulls_last=True), "pk")
        )
        names = get_names()
        for m in memberships:
            if m.user_id not in where:  # the most recently used one comes first
                profile = (m.profile.display_name or "").strip() or m.profile.name
                where[m.user_id] = f"{names.get(m.program, m.program)} \u00b7 {profile}"
    cutoff = now - timedelta(minutes=ACTIVE_MINUTES)
    rows = [
        {"name": u.get_full_name().strip() or u.username, "where": where.get(u.pk, ""), "recent": u.last_seen_at >= cutoff}
        for u in users
    ]
    return {
        "show_active": True,
        "active_now": [r for r in rows if r["recent"]],
        "earlier_today": [r for r in rows if not r["recent"]],
    }
