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


def _read(request):
    """``(names, site_name)`` for this request from one query, cached on the request. Never raises."""
    cached = getattr(request, "_suite_all", None)
    if cached is None:
        try:
            cached = suite.read_all()
        except Exception:
            logger.exception("Could not read the suite display names")
            cached = (dict(suite.DEFAULT_NAMES), suite.default_site_name())
        request._suite_all = cached
        request._suite_names = cached[0]  # reused by program_label so the page does not query twice
    return cached


def suite_names(request):
    """Expose the display names to every template as ``home_name``, ``diary_name`` and so on, and
    ``home_header_words`` (always True: the header bar shows words; only the user badge, Search, Home and Sign out are icons)."""
    names, site = _read(request)
    return {"site_name": site,
            "home_name": names[suite.KEY_HOME], "diary_name": names[suite.KEY_DIARY], "fees_name": names[suite.KEY_FEES],
            "investments_name": names[suite.KEY_INVESTMENTS],
            "investments_on": programs.investments_enabled(),
            "home_header_words": True}


def _names():
    try:
        return suite.get_names()
    except Exception:
        logger.exception("Could not read the suite display names")
        return dict(suite.DEFAULT_NAMES)


def program_label(request):
    """The names of the current program's profile for the templates. Never raises (falls back to the program name).

    ``program_label``: the profile's Home Page Name (``display_name``) if it has one, else the program name; used in
    the page title and the Home program button.
    ``program_header_label``: the name for the program header, the Header Name, else the Home Page Name, else ""
    (the header then shows the program name and the profile name).
    ``program_full_label``: the full Home page name, shown when the mouse is over the header name: the Home Page Name,
    else "<program name> · <profile name>"."""
    try:
        program = current_program_key(request)
        profile = (
            request_profile(request, program)
            if getattr(request, "user", None) and request.user.is_authenticated
            else None
        )
        names = getattr(request, "_suite_names", None) or suite.get_names()
        home = " ".join((profile.display_name or "").split()) if profile is not None else ""
        header = profile.header_text() if profile is not None else ""
        full = home or (f"{names[program]} \u00b7 {profile.name}" if profile is not None else names[program])
        return {"program_label": home or names[program], "program_header_label": header, "program_full_label": full}
    except Exception:
        logger.exception("Could not work out the program label")
        name = suite.DEFAULT_NAMES[suite.KEY_DIARY]
        return {"program_label": name, "program_header_label": "", "program_full_label": name}


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
    """``header_words``: always True, the header bar shows words (there is no Words or Logo choice). Search, Home, Sign out and the
    user badge are always icons.
    ``justify_text``: True when the signed-in user chose to justify text (My settings, Display); base_suite.html puts the class on <html>.
    ``colour_theme``: the signed-in user's accent colour (My settings, Display); base_suite.html puts it on <html data-theme>.
    ``remove_citation_hyphen``: True when the signed-in user left the hyphen out between an Item's text and its citations (My settings, Display)."""
    user = getattr(request, "user", None)
    signed_in = user is not None and user.is_authenticated
    justify = bool(signed_in and getattr(user, "justify_text", False))
    theme = (getattr(user, "colour_theme", "") if signed_in else "") or "oxblood"
    return {"header_words": True, "justify_text": justify, "colour_theme": theme,
            "remove_citation_hyphen": bool(signed_in and getattr(user, "remove_citation_hyphen", False))}


#: The main Home page header (D86): each entry is one header item; its tabs are the sub-pages shown across the top of
#: every page of the group. A tab is (url name, label, Admin only, "is this the current page" test on the url name).
#: The header item opens the first tab the user may see, and is marked current on every page of the group.
def _starts(*prefixes):
    return lambda n: any(n.startswith(p) for p in prefixes)


def _is(*names):
    return lambda n: n in names


MY_SETTINGS_PAGES = ("my_settings", "format_preview", "password_change")

#: The labels of the program tabs of Settings: the program's current display name (renamed on Settings > Display > Names).
#: suite_nav resolves them.
DIARY_SETTINGS = object()
FEES_SETTINGS = object()
INVESTMENTS_SETTINGS = object()


def _plain(test):
    return lambda name, request: test(name)


def _my_tab(*tabs):
    """Current on a My settings page showing one of ``tabs`` (``?tab=``); "" is the Account and Profile View page."""
    def test(name, request):
        if name not in MY_SETTINGS_PAGES:
            return False
        asked = request.GET.get("tab") or request.POST.get("tab") or ""
        asked = asked if asked in ("display", "start") else ""
        return name != "my_settings" and "" in tabs or asked in tabs
    return test


_USERS_PAGES = _starts("user_", "profile_list", "profile_create", "profile_edit", "profile_delete", "profile_clear",
                       "profile_restore", "offline_link_admin", "admin_profile_access")
_INVESTMENTS_SETTINGS_PAGES = ("investments_portfolio_action", "investments_broker_action", "investments_indices_action",
                               "investments_clear_history")

#: Settings (owner round 2026-11): one tab strip over every settings page of the suite, in the Home shell and in each program.
#: A tab is (url name, label, who may see it, current-page test(url name, request), query string). Who: "all", "admin",
#: "profile" (a Case Law Diary profile), "fees" (a Fee Register profile) or "investments" (an Investments profile).
SETTINGS_TABS = (
    ("user_list", "Users & Profiles", "admin", _plain(_USERS_PAGES), ""),
    ("my_settings", "Account and Profile View", "all", _my_tab(""), ""),
    ("backup_list", "Backup", "admin", _plain(lambda n: n.startswith("backup_") or n.startswith("restore_")), ""),
    ("my_settings", "Display", "all",
     lambda n, request: _my_tab("display")(n, request) or n == "settings", "?tab=display"),
    ("my_settings", "Start Screens", "all", _my_tab("start"), "?tab=start"),
    ("profile_settings", DIARY_SETTINGS, "profile", _plain(_is("profile_settings", "export_settings")), ""),
    ("fees_settings", FEES_SETTINGS, "fees", _plain(_starts("fees_settings")), ""),
    ("investments_settings", INVESTMENTS_SETTINGS, "investments",
     _plain(lambda n: n.startswith("investments_settings") or n in _INVESTMENTS_SETTINGS_PAGES), ""),
)

#: Second row under the tab strip, for the tabs that hold more than one page: parent label -> (url name, label, who, test, query).
SETTINGS_SUBTABS = {
    "Users & Profiles": (
        ("user_list", "Users", "admin", _plain(_starts("user_")), ""),
        ("profile_list", "Profiles", "admin", _plain(_starts("profile_list", "profile_create", "profile_edit", "profile_delete",
                                                              "profile_clear", "profile_restore", "offline_link_admin")), ""),
        ("admin_profile_access", "Profile Access", "admin", _plain(_is("admin_profile_access")), ""),
    ),
    "Display": (
        ("my_settings", "My Display", "all", _my_tab("display"), "?tab=display"),
        ("settings", "Names", "admin", _plain(_is("settings")), ""),
    ),
}

#: One entry per header item on Home: (label, icon, url name it opens, tabs). Settings is the tab strip above; Help is one link.
SUITE_GROUPS = (
    ("Settings", "icons/gear.svg.html", "my_settings", SETTINGS_TABS),
    ("Help", "icons/help.svg.html", "help", (
        ("help", "Help", "all", _plain(_is("help")), ""),
    )),
)


def suite_nav(request):
    """``suite_nav`` (the header items of the main Home page), ``suite_tabs`` (the settings tab strip, on every settings page of
    the suite, shown only when the user may see two or more) and ``suite_subtabs`` (the second row of the current tab, if any).
    At most one cached query (the user's profiles)."""
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
        if who == "investments":
            return programs.investments_enabled() and request_profile(request, suite.KEY_INVESTMENTS) is not None
        if who == "profile":
            if has_profile is None:
                has_profile = request_profile(request) is not None
            return has_profile
        return True

    def program_name(key):
        names = getattr(request, "_suite_names", None)
        return (names or _names())[key]

    def label_of(name):
        if name is DIARY_SETTINGS:
            return program_name(suite.KEY_DIARY)
        if name is FEES_SETTINGS:
            return program_name(suite.KEY_FEES)
        if name is INVESTMENTS_SETTINGS:
            return program_name(suite.KEY_INVESTMENTS)
        return name

    def build(tabs):
        return [
            {"url": reverse(url_name) + query, "name": label_of(name), "on": is_current(current, request)}
            for url_name, name, who, is_current, query in tabs
            if allowed(who)
        ]

    items, tabs_here, subtabs_here = [], [], []
    for label, icon, home, tabs in SUITE_GROUPS:
        mine = build(tabs)
        if not mine:
            continue
        on = any(t["on"] for t in mine)
        items.append({"url": reverse(home) if home in {t[0] for t in tabs} else mine[0]["url"], "name": label, "icon": icon, "on": on})
        if on and len(mine) > 1:
            tabs_here = mine
            for t in mine:
                if t["on"] and t["name"] in SETTINGS_SUBTABS:
                    subs = build(SETTINGS_SUBTABS[t["name"]])
                    subtabs_here = subs if len(subs) > 1 else []
    return {"suite_nav": items, "suite_tabs": tabs_here, "suite_subtabs": subtabs_here}
