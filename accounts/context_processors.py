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


#: The main Home page header (D86): each entry is one header item; its tabs are the sub-pages shown across the top of
#: every page of the group. A tab is (url name, label, Admin only, "is this the current page" test on the url name).
#: The header item opens the first tab the user may see, and is marked current on every page of the group.
def _starts(*prefixes):
    return lambda n: any(n.startswith(p) for p in prefixes)


def _is(*names):
    return lambda n: n in names


#: The tabs of the merged Settings page (round 17, D93), in order: (my_settings ``?tab=``, label, needs a diary profile).
SETTINGS_TABS = (("account", "Account", False), ("display", "Display", False), ("numbers", "Numbers", True),
                 ("export", "Word export", True))
MY_SETTINGS_PAGES = ("my_settings", "format_preview", "password_change")


def _settings_tab(key):
    def current(name, request):
        if name not in MY_SETTINGS_PAGES:
            return False
        if name == "password_change":
            return key == "account"
        return (request.GET.get("tab") or request.POST.get("tab") or "account") == key
    return current


def _plain(test):
    return lambda name, request: test(name)


#: One entry per header item: (label, icon, tabs). A tab is (url name, label, who may see it, current-page test,
#: query string). Who: "all", "admin" or "profile" (a Case Law Diary profile).
SUITE_GROUPS = (
    ("Users & Profiles", "icons/users.svg.html", (
        ("user_list", "Users", "admin", _plain(_starts("user_")), ""),
        ("profile_list", "Profiles", "admin", _plain(_starts("profile_list", "profile_create", "profile_edit",
                                                             "profile_delete", "profile_clear", "profile_restore")), ""),
    )),
    ("Backups & Import", "icons/backups.svg.html", (
        ("backup_list", "Backups", "admin",
         _plain(lambda n: (n.startswith("backup_") and n != "backup_email") or n.startswith("restore_")), ""),
        ("backup_email", "Email backups", "admin", _plain(_is("backup_email")), ""),
        ("import_word", "Import", "admin", _plain(_is("import_word")), ""),
    )),
    ("Settings", "icons/gear.svg.html", tuple(
        ("my_settings", label, "profile" if needs_profile else "all", _settings_tab(key), f"?tab={key}")
        for key, label, needs_profile in SETTINGS_TABS
    ) + (
        ("profile_settings", "Diary", "profile", _plain(_is("profile_settings")), ""),
        ("my_edits", "My edits", "profile", _plain(_is("my_edits")), ""),
        ("settings", "Site", "admin", _plain(_is("settings")), ""),
    )),
    ("Help", "icons/help.svg.html", (
        ("help", "Help", "all", _plain(_is("help")), ""),
    )),
)


def suite_nav(request):
    """``suite_nav`` (the header items of the main Home page) and ``suite_tabs`` (the sub-pages of the group the current
    page belongs to, shown only when the user may see two or more). At most one cached query (the user's diary profile)."""
    from django.urls import reverse

    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"suite_nav": [], "suite_tabs": []}
    match = getattr(request, "resolver_match", None)
    current = (match.url_name or "") if match else ""
    has_profile = None

    def allowed(who):
        nonlocal has_profile
        if who == "admin":
            return user.is_admin
        if who == "profile":
            if has_profile is None:
                has_profile = request_profile(request) is not None
            return has_profile
        return True

    items, tabs_here = [], []
    for label, icon, tabs in SUITE_GROUPS:
        mine = [
            {"url": reverse(url_name) + query, "name": name, "on": is_current(current, request)}
            for url_name, name, who, is_current, query in tabs
            if allowed(who)
        ]
        if not mine:
            continue
        on = any(t["on"] for t in mine)
        items.append({"url": mine[0]["url"], "name": label, "icon": icon, "on": on})
        if on and len(mine) > 1:
            tabs_here = mine
    return {"suite_nav": items, "suite_tabs": tabs_here}
