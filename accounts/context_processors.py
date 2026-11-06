import logging

from . import programs, suite
from .models import ROLE_EDITOR
from .profiles import request_memberships, request_profile, request_role

logger = logging.getLogger(__name__)


def current_program_key(request):
    """The program the current page belongs to, from the URL namespace, falling back to the diary.

    Each program is mounted under a URL namespace equal to its key (``diary``). A request with no match
    (for example a context processor called with a plain test request) uses the diary, as before.
    """
    match = getattr(request, "resolver_match", None)
    namespace = getattr(match, "namespace", "") if match is not None else ""
    if namespace and programs.get_program(namespace) is not None:
        return namespace
    # A program with no URL namespace (the Fee Register) names its pages ``<key>_...``; the diary's names are
    # global and unprefixed, so it stays the fallback.
    url_name = (getattr(match, "url_name", "") or "") if match is not None else ""
    for key in programs.program_keys():
        if key != suite.KEY_DIARY and url_name.startswith(f"{key}_"):
            return key
    return suite.KEY_DIARY


def suite_names(request):
    """Expose the display names to every template as ``home_name`` and ``diary_name``."""
    try:
        names = suite.get_names()
        request._suite_names = names  # reused by program_label so the page does not query twice
    except Exception:
        logger.exception("Could not read the suite display names")
        names = dict(suite.DEFAULT_NAMES)
    return {"home_name": names[suite.KEY_HOME], "diary_name": names[suite.KEY_DIARY]}


def _names():
    try:
        return suite.get_names()
    except Exception:
        logger.exception("Could not read the suite display names")
        return dict(suite.DEFAULT_NAMES)


def program_label(request):
    """``program_label``: the signed-in user's profile Display Name if it has one, else the program name.

    Used in the page title and the Home program button. Never raises: a failure falls back to the program name."""
    try:
        program = current_program_key(request)
        profile = (
            request_profile(request, program)
            if getattr(request, "user", None) and request.user.is_authenticated
            else None
        )
        name = (profile.display_name or "").strip() if profile is not None else ""
        if name:
            return {"program_label": name}
        names = getattr(request, "_suite_names", None) or suite.get_names()
        return {"program_label": names[program]}
    except Exception:
        logger.exception("Could not work out the program label")
        return {"program_label": suite.DEFAULT_NAMES[suite.KEY_DIARY]}


def current_profile(request):
    """Expose the signed-in user's Case Law Diary profile to templates as ``current_profile``, and ``other_profiles``:
    the other profiles they may switch to (round 18, D95; the same query, so no extra cost)."""
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {"current_profile": None, "diary_editor": False, "other_profiles": []}
    profile = request_profile(request)
    others = [m.profile for m in request_memberships(request)[1:]]
    return {"current_profile": profile, "diary_editor": profile is not None and request_role(request) == ROLE_EDITOR,
            "other_profiles": others}


def header_style(request):
    """``header_words``: True when the signed-in user chose Words for the header bar (My settings); Icons otherwise.
    ``justify_text``: True when they chose to justify text (My settings, Display); base_suite.html puts the class on <html>."""
    user = getattr(request, "user", None)
    words = bool(user is not None and user.is_authenticated and getattr(user, "header_style", "icons") == "words")
    justify = bool(user is not None and user.is_authenticated and getattr(user, "justify_text", False))
    return {"header_words": words, "justify_text": justify}


#: The main Home page header (D86): each entry is one header item; its tabs are the sub-pages shown across the top of
#: every page of the group. A tab is (url name, label, Admin only, "is this the current page" test on the url name).
#: The header item opens the first tab the user may see, and is marked current on every page of the group.
def _starts(*prefixes):
    return lambda n: any(n.startswith(p) for p in prefixes)


def _is(*names):
    return lambda n: n in names


#: The my_settings tabs (``?tab=``): (key, label, needs a diary profile). Round 18 (D96): Account and Display are under
#: Settings; Numbers is under the Case Law Diary tab.
SETTINGS_TABS = (("account", "Account", False), ("display", "Display", False), ("numbers", "Numbers", True))
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


def _my_settings_tab(key, label, who):
    return ("my_settings", label, who, _settings_tab(key), f"?tab={key}")


#: The label of a header item or tab that is the Case Law Diary's own name (renamed on Admins > Page Names). Used both
#: for the diary group label (history) and now for the diary TAB label inside the Settings group; suite_nav resolves it
#: to the current display name.
DIARY_NAME = object()

#: Same idea for the Fee Register tab of the Settings group (its program name, renamed on Admins > Page Names).
FEES_NAME = object()


def _never(name, request):
    """The Fee Register tab is a link out to that program's Settings screen, so it is never current on a suite page."""
    return False


def _diary_tab_current(name, request):
    """The Case Law Diary tab (and the Settings header item) are current on the Numbers settings tab and on My edits."""
    if name == "my_edits":
        return True
    return _settings_tab("numbers")(name, request)


#: One entry per header item: (label, icon, tabs). A tab is (url name, label, who may see it, current-page test,
#: query string). Who: "all", "admin", "profile" (a Case Law Diary profile) or "fees" (a Fee Register profile). The label may be the DIARY_NAME sentinel,
#: which suite_nav resolves to the diary's current display name. Round 19: Admins (everything only an Admin may do),
#: Settings (my account, display, and - for users with a diary profile - the Case Law Diary tab by its current name,
#: whose own sub-tabs are Numbers and Edits), Help.
SUITE_GROUPS = (
    ("Admins", "icons/admin.svg.html", (
        ("user_list", "Users", "admin", _plain(_starts("user_")), ""),
        ("profile_list", "Profiles", "admin", _plain(_starts("profile_list", "profile_create", "profile_edit",
                                                             "profile_delete", "profile_clear", "profile_restore",
                                                             "offline_link_admin")), ""),
        ("settings", "Page Names", "admin", _plain(_is("settings")), ""),
        ("backup_list", "Backups", "admin",
         _plain(lambda n: (n.startswith("backup_") and n != "backup_email") or n.startswith("restore_")), ""),
        ("backup_email", "Email Backups", "admin", _plain(_is("backup_email")), ""),
        ("import_word", "Import", "admin", _plain(_is("import_word")), ""),
    )),
    ("Settings", "icons/gear.svg.html", (
        _my_settings_tab("account", "Account", "all"),
        _my_settings_tab("display", "Display", "all"),
        ("my_settings", DIARY_NAME, "profile", _diary_tab_current, "?tab=numbers"),
        ("fees_settings", FEES_NAME, "fees", _never, ""),
    )),
    ("Help", "icons/help.svg.html", (
        ("help", "Help", "all", _plain(_is("help")), ""),
    )),
)

#: The second-level sub-tabs of the Case Law Diary tab (Numbers and Edits). Shown only when that tab is current and only
#: to users with a diary profile. Plain links, no JavaScript needed. Each is (url name, label, current-page test, query).
DIARY_SUBTABS = (
    ("my_settings", "Numbers", _settings_tab("numbers"), "?tab=numbers"),
    ("my_edits", "Edits", _plain(_is("my_edits")), ""),
)


def suite_nav(request):
    """``suite_nav`` (the header items of the main Home page), ``suite_tabs`` (the sub-pages of the group the current page
    belongs to, shown only when the user may see two or more) and ``suite_subtabs`` (the second-level sub-tabs of the
    Case Law Diary tab, shown only when that tab is current). At most one cached query (the user's diary profile)."""
    from django.urls import reverse

    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"suite_nav": [], "suite_tabs": [], "suite_subtabs": []}
    match = getattr(request, "resolver_match", None)
    current = (match.url_name or "") if match else ""
    has_profile = None

    def allowed(who):
        nonlocal has_profile
        if who == "admin":
            return user.is_admin
        if who == "fees":
            return programs.fees_enabled() and request_profile(request, suite.KEY_FEES) is not None
        if who == "profile":
            if has_profile is None:
                has_profile = request_profile(request) is not None
            return has_profile
        return True

    def diary_name():
        names = getattr(request, "_suite_names", None)
        return (names or _names())[suite.KEY_DIARY]

    def fees_name():
        names = getattr(request, "_suite_names", None)
        return (names or _names())[suite.KEY_FEES]

    items, tabs_here = [], []
    for label, icon, tabs in SUITE_GROUPS:
        if label is DIARY_NAME:
            label = diary_name()
        mine = [
            {"url": reverse(url_name) + query,
             "name": diary_name() if name is DIARY_NAME else (fees_name() if name is FEES_NAME else name),
             "on": is_current(current, request)}
            for url_name, name, who, is_current, query in tabs
            if allowed(who)
        ]
        if not mine:
            continue
        on = any(t["on"] for t in mine)
        items.append({"url": mine[0]["url"], "name": label, "icon": icon, "on": on})
        if on and len(mine) > 1:
            tabs_here = mine
    # Second level: the Case Law Diary tab's own sub-tabs (Numbers, Edits), only for users with a diary profile and only
    # while that tab is the current one.
    subtabs = []
    if allowed("profile") and _diary_tab_current(current, request):
        subtabs = [
            {"url": reverse(url_name) + query, "name": name, "on": is_current(current, request)}
            for url_name, name, is_current, query in DIARY_SUBTABS
        ]
    return {"suite_nav": items, "suite_tabs": tabs_here, "suite_subtabs": subtabs}
