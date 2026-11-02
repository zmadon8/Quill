import logging

from . import suite
from .models import ROLE_EDITOR
from .profiles import request_profile, request_role

logger = logging.getLogger(__name__)


def suite_names(request):
    """Expose the display names to every template as ``home_name`` and ``diary_name``."""
    try:
        names = suite.get_names()
    except Exception:
        logger.exception("Could not read the suite display names")
        names = dict(suite.DEFAULT_NAMES)
    return {"home_name": names[suite.KEY_HOME], "diary_name": names[suite.KEY_DIARY]}


def program_label(request):
    """``program_label``: the signed-in user's profile Display Name if it has one, else the program name.

    Used in the page title and the Home program button. Never raises: a failure falls back to the program name."""
    try:
        profile = request_profile(request) if getattr(request, "user", None) and request.user.is_authenticated else None
        name = (profile.display_name or "").strip() if profile is not None else ""
        if name:
            return {"program_label": name}
        return {"program_label": suite.get_names()[suite.KEY_DIARY]}
    except Exception:
        logger.exception("Could not work out the program label")
        return {"program_label": suite.DEFAULT_NAMES[suite.KEY_DIARY]}


def current_profile(request):
    """Expose the signed-in user's Case Law Diary profile to templates as ``current_profile``."""
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {"current_profile": None, "diary_editor": False}
    profile = request_profile(request)
    return {"current_profile": profile, "diary_editor": profile is not None and request_role(request) == ROLE_EDITOR}
