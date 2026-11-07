"""Record when a signed-in user was last seen, for the Active Now panel on Home."""
from django.db import DatabaseError
from django.utils import timezone

from .models import User

#: A user is touched at most this often (seconds).
TOUCH_SECONDS = 60
_SKIP_PREFIXES = ("/static/", "/healthz", "/favicon")


class LastSeenMiddleware:
    """Set ``User.last_seen_at`` at most once per ``TOUCH_SECONDS`` per user.

    The check uses the value already loaded on ``request.user`` so most requests add no query. The write is one
    queryset UPDATE (no save signals). Anonymous and static requests are skipped.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path_info.startswith(_SKIP_PREFIXES):
            user = getattr(request, "user", None)
            if user is not None and user.is_authenticated:
                now = timezone.now()
                seen = user.last_seen_at
                if seen is None or (now - seen).total_seconds() >= TOUCH_SECONDS:
                    try:
                        User.objects.filter(pk=user.pk).update(last_seen_at=now)
                        user.last_seen_at = now
                    except DatabaseError:
                        pass  # presence is a convenience: fail open (locked or read-only database)
        return self.get_response(request)
