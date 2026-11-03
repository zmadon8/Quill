import logging

from . import suite
from .models import ROLE_EDITOR
from .profiles import request_profile, request_role

logger = logging.getLogger(__name__)


def suite_names(request):
    """Expose the display names to every template as ``home_name`` and ``diary_name``."""
    try:
        names = suite.get_names()
        request._suite_names = names  # reused by program_label so the page does not query twice
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
        names = getattr(request, "_suite_names", None) or suite.get_names()
        return {"program_label": names[suite.KEY_DIARY]}
    except Exception:
        logger.exception("Could not work out the program label")
        return {"program_label": suite.DEFAULT_NAMES[suite.KEY_DIARY]}


def current_profile(request):
    """Expose the signed-in user's Case Law Diary profile to templates as ``current_profile``."""
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {"current_profile": None, "diary_editor": False}
    profile = request_profile(request)
    return {"current_profile": profile, "diary_editor": profile is not None and request_role(request) == ROLE_EDITOR}


def header_style(request):
    """``header_words``: True when the signed-in user chose Words for the header bar (My settings); Icons otherwise."""
    user = getattr(request, "user", None)
    words = bool(user is not None and user.is_authenticated and getattr(user, "header_style", "icons") == "words")
    return {"header_words": words}


#: The main Home page header: (url name, label, icon, admin only, "is this the current page" test on the url name).
SUITE_NAV = (
    ("profile_list", "Profiles", "icons/profiles.svg.html", True, lambda n: n.startswith("profile_")),
    ("user_list", "Users", "icons/users.svg.html", True, lambda n: n.startswith("user_")),
    ("import_word", "Import", "icons/import.svg.html", True, lambda n: n == "import_word"),
    ("backup_list", "Backups", "icons/backups.svg.html", True, lambda n: n.startswith("backup_") or n.startswith("restore_")),
    ("settings", "Settings", "icons/gear.svg.html", True, lambda n: n == "settings"),
    ("help", "Help", "icons/help.svg.html", False, lambda n: n == "help"),
    ("my_settings", "My settings", "icons/mysettings.svg.html", False, lambda n: n == "my_settings"),
)


def suite_nav(request):
    """``suite_nav``: the links of the main Home page header bar, for ``templates/base_suite_home.html``."""
    from django.urls import reverse

    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"suite_nav": []}
    match = getattr(request, "resolver_match", None)
    current = (match.url_name or "") if match else ""
    items = []
    for url_name, label, icon, admin_only, is_current in SUITE_NAV:
        if admin_only and not user.is_admin:
            continue
        items.append({"url": reverse(url_name), "name": label, "icon": icon, "on": is_current(current)})
    return {"suite_nav": items}

