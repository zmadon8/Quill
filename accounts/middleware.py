"""Record when a signed-in user was last seen, and in which profile, for the Active Now panel on Home."""
from django.db import DatabaseError
from django.utils import timezone

from .models import ProfileMembership, User
from .suite import KEY_DIARY, KEY_FEES, KEY_INVESTMENTS

#: A user is touched at most this often (seconds).
TOUCH_SECONDS = 60
_SKIP_PREFIXES = ("/static/", "/healthz", "/favicon")
#: The pages of each program, by address: a page there counts as using the profile the user has open in it.
PROGRAM_PREFIXES = (("/caselaw/", KEY_DIARY), ("/fees/", KEY_FEES), ("/investments/", KEY_INVESTMENTS))


def _stale(seen, now):
    return seen is None or (now - seen).total_seconds() >= TOUCH_SECONDS


def touch_profile(request, now):
    """Set ``ProfileMembership.last_seen_at`` for the profile this program page used, at most once a minute.

    It reads the membership the page already looked up (``accounts.profiles.request_profile`` caches it on the
    request), so it adds no read query; a page that never looked one up is skipped. An Admin's stand-in for a profile
    they have no membership in (no ``pk``) is skipped too.
    """
    for prefix, program in PROGRAM_PREFIXES:
        if request.path_info.startswith(prefix):
            membership = getattr(request, f"_membership_{program}", None)
            if membership is not None and membership.pk and _stale(membership.last_seen_at, now):
                ProfileMembership.objects.filter(pk=membership.pk).update(last_seen_at=now)
                membership.last_seen_at = now
            return


class LastSeenMiddleware:
    """Set ``User.last_seen_at`` at most once per ``TOUCH_SECONDS`` per user.

    The check uses the value already loaded on ``request.user`` so most requests add no query. The write is one
    queryset UPDATE (no save signals). Anonymous and static requests are skipped.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tracked = False
        if not request.path_info.startswith(_SKIP_PREFIXES):
            user = getattr(request, "user", None)
            if user is not None and user.is_authenticated:
                tracked = True
                now = timezone.now()
                if _stale(user.last_seen_at, now):
                    try:
                        User.objects.filter(pk=user.pk).update(last_seen_at=now)
                        user.last_seen_at = now
                    except DatabaseError:
                        pass  # presence is a convenience: fail open (locked or read-only database)
        response = self.get_response(request)
        if tracked:
            # After the page: by then it has looked up the profile it shows, so which one was used is known.
            try:
                touch_profile(request, timezone.now())
            except DatabaseError:
                pass
        return response
