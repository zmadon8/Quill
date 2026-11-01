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


def current_profile(request):
    """Expose the signed-in user's Case Law Diary profile to templates as ``current_profile``."""
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {"current_profile": None, "diary_editor": False}
    profile = request_profile(request)
    return {"current_profile": profile, "diary_editor": profile is not None and request_role(request) == ROLE_EDITOR}
