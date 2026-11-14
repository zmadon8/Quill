"""The Fee Register's History log: one ``FeesHistory`` row per action, written by the services.

``record`` is called inside the same ``transaction.atomic()`` as the change it describes, so a change that is
rolled back leaves no line. The signed-in user is not passed down through every service: ``FeesActorMiddleware``
remembers the current request and ``record`` reads ``request.user`` from it. Outside a request (an import run
from the command line, tests that call a service directly) the user is empty and the History tab shows "System".
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from fees.models import FeesHistory

#: How many rows the History tab shows.
LIMIT = 100

ACTION_LABELS = {
    "create": "Added",
    "update": "Changed",
    "delete": "Deleted",
    "finalise": "Finalised",
    "write_off": "Wrote off",
    "unwrite_off": "Removed write-off from",
    "move": "Moved",
    "restore": "Restored",
    "import": "Imported",
    "clear": "Cleared",
}

OBJECT_LABELS = {
    "memo": "memo",
    "payment": "payment",
    "firm": "firm",
    "group": "group",
    "matter": "matter",
    "settings": "settings",
    "bank": "bank account",
    "profile": "Fee Register",
}

_request = ContextVar("fees_history_request", default=None)
_quiet = ContextVar("fees_history_quiet", default=False)


@contextmanager
def quiet():
    """Inside this block ``record`` writes nothing. A bulk job (the memo import) uses it and then records one summary line."""
    token = _quiet.set(True)
    try:
        yield
    finally:
        _quiet.reset(token)


def set_request(request):
    """Remember the request being served (returns the token ``reset_request`` needs)."""
    return _request.set(request)


def reset_request(token):
    _request.reset(token)


def current_user():
    """The signed-in user of the request being served, or None outside a request."""
    request = _request.get()
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return user
    return None


def record(profile, action, object_type, object_id=None, summary=""):
    """Add one line to the History of ``profile``. Call it inside the transaction of the change."""
    if _quiet.get():
        return None
    return FeesHistory.objects.create(
        profile=profile,
        user=current_user(),
        action=action,
        object_type=object_type,
        object_id=object_id,
        summary=(summary or "")[:300],
    )


def memo_name(memo):
    """How a memo is named in a summary: its number, or "draft" before it has one."""
    return f"memo {memo.memo_number}" if memo.memo_number else "draft memo"


def recent(profile, limit=LIMIT):
    """The latest ``limit`` actions in ``profile``, newest first, with the user loaded."""
    return list(FeesHistory.objects.filter(profile=profile).select_related("user").order_by("-at", "-id")[:limit])


def purgeable(now=None):
    """History rows older than ``HISTORY_RETENTION_DAYS``."""
    cutoff = (now or timezone.now()) - timedelta(days=settings.HISTORY_RETENTION_DAYS)
    return FeesHistory.objects.filter(at__lt=cutoff)
