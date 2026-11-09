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
    """``(names, brand_modes, site_name)`` for this request from one query, cached on the request. Never raises."""
    cached = getattr(request, "_suite_all", None)
    if cached is None:
        try:
            cached = suite.read_all()
        except Exception:
            logger.exception("Could not read the suite display names")
            cached = (dict(suite.DEFAULT_NAMES), {key: suite.BRAND_WORDS for key in suite.BRAND_KEYS},
                      suite.default_site_name())
        request._suite_all = cached
        request._suite_names = cached[0]  # reused by program_label so the page does not query twice
    return cached


def suite_names(request):
    """Expose the display names to every template as ``home_name`` and ``diary_name``, and the suite-wide header bar
    choice (Words or Logo, set on Admins > Appearance) as ``suite_brand`` (``{"home"|"diary"|"fees": "words"|"logo"}``)
    and ``home_header_words`` (True when Home, Admins, Settings and Help pages show words)."""
    names, modes, site = _read(request)
    return {"site_name": site,
            "home_name": names[suite.KEY_HOME], "diary_name": names[suite.KEY_DIARY], "fees_name": names[suite.KEY_FEES],
            "investments_name": names[suite.KEY_INVESTMENTS],
            "investments_on": programs.investments_enabled(),
            "suite_brand": modes,
            "home_header_words": modes[suite.KEY_HOME] == suite.BRAND_WORDS}


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
    """``header_words``: True when the header bar shows words instead of icons (Logo) on this page (the default). Search, Home and Sign out
    ignore it and are always icons. The choice is
    suite-wide (Admins > Appearance), per program: the Fee Register's pages use its choice, every other page the Case
    Law Diary's; base_suite_home.html swaps in the Home choice (``home_header_words``) for the Home, Admins, Settings and
    Help pages. No extra query (shared with ``suite_names``).
    ``justify_text``: True when the signed-in user chose to justify text (My settings, Display); base_suite.html puts the class on <html>."""
    user = getattr(request, "user", None)
    program = current_program_key(request)
    mode = _read(request)[1].get(program, suite.BRAND_WORDS)
    justify = bool(user is not None and user.is_authenticated and getattr(user, "justify_text", False))
    return {"header_words": mode == suite.BRAND_WORDS, "justify_text": justify}


#: The main Home page header (D86): each entry is one header item; its tabs are the sub-pages shown across the top of
#: every page of the group. A tab is (url name, label, Admin only, "is this the current page" test on the url name).
#: The header item opens the first tab the user may see, and is marked current on every page of the group.
def _starts(*prefixes):
    return lambda n: any(n.startswith(p) for p in prefixes)


def _is(*names):
    return lambda n: n in names


MY_SETTINGS_PAGES = ("my_settings", "format_preview", "password_change")

#: The labels of the Settings menu links to a program's own Settings tab: the program's current display name (renamed on
#: Admins > Appearance) followed by "settings". suite_nav resolves them.
DIARY_SETTINGS = object()
FEES_SETTINGS = object()
INVESTMENTS_SETTINGS = object()


def _plain(test):
    return lambda name, request: test(name)


def _never(name, request):
    """A program's Settings tab is a page of that program (its own header), so it is never current on a suite page."""
    return False


#: One entry per header item: (label, icon, tabs). A tab is (url name, label, who may see it, current-page test,
#: query string). Who: "all", "admin", "profile" (a Case Law Diary profile) or "fees" (a Fee Register profile). Admins
#: holds everything only an Admin may do (Users, Profiles, Profile Access, Appearance, Backups). Settings is a short list of links: My
#: settings (everyone) and each program's Settings tab, only for a user who can open that program (the Fee Register
#: also only while it is switched on). Help is one link.
SUITE_GROUPS = (
    ("Admins", "icons/admin.svg.html", (
        ("user_list", "Users", "admin", _plain(_starts("user_")), ""),
        ("profile_list", "Profiles", "admin", _plain(_starts("profile_list", "profile_create", "profile_edit",
                                                             "profile_delete", "profile_clear", "profile_restore",
                                                             "offline_link_admin")), ""),
        ("admin_profile_access", "Profile Access", "admin", _plain(_is("admin_profile_access")), ""),
        ("settings", "Appearance", "admin", _plain(_is("settings")), ""),
        ("backup_list", "Backups", "admin",
         _plain(lambda n: n.startswith("backup_") or n.startswith("restore_")), ""),
    )),
    ("Settings", "icons/gear.svg.html", (
        ("my_settings", "My Settings", "all", _plain(lambda n: n in MY_SETTINGS_PAGES), ""),
        ("profile_settings", DIARY_SETTINGS, "profile", _never, ""),
        ("fees_settings", FEES_SETTINGS, "fees", _never, ""),
        ("investments_settings", INVESTMENTS_SETTINGS, "investments", _never, ""),
    )),
    ("Help", "icons/help.svg.html", (
        ("help", "Help", "all", _plain(_is("help")), ""),
    )),
)


def suite_nav(request):
    """``suite_nav`` (the header items of the main Home page) and ``suite_tabs`` (the sub-pages of the group the current
    page belongs to, shown only when the user may see two or more). At most one cached query (the user's profiles)."""
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
            return f"{program_name(suite.KEY_DIARY)} Settings"
        if name is FEES_SETTINGS:
            return f"{program_name(suite.KEY_FEES)} Settings"
        if name is INVESTMENTS_SETTINGS:
            return f"{program_name(suite.KEY_INVESTMENTS)} Settings"
        return name

    items, tabs_here = [], []
    for label, icon, tabs in SUITE_GROUPS:
        mine = [
            {"url": reverse(url_name) + query, "name": label_of(name), "on": is_current(current, request)}
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
