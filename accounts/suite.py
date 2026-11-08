"""Display names for the Home page and each program in the suite.

Only the names people see can be changed (Settings). Keys are fixed internal identifiers.
A key with no stored row uses its default here, so a fresh install or an older backup
that lacks the table still shows sensible names.
"""
from django.conf import settings

from .models import SuiteName

KEY_HOME = "home"
KEY_DIARY = "diary"
KEY_FEES = "fees"

DEFAULT_NAMES = {
    KEY_HOME: "Home",
    KEY_DIARY: "Case Law Diary",
    KEY_FEES: "Fee Register",
}
MAX_NAME_LENGTH = 60
#: The name of the whole website (emails, password reset, shared page titles), set on Admins > Appearance. Kept in a
#: ``SuiteName`` row of its own (not one of the program names above); no row means ``settings.SITE_NAME``.
KEY_SITE = "site"


def default_site_name():
    return getattr(settings, "SITE_NAME", "") or "Madon.co.in"


#: Header bar style per program (round 20, 3.1): Words (the names as words) or Logo (the icons). Suite-wide, for
#: everyone, set by an Admin on Admins > Appearance. Stored in ``SuiteName`` rows keyed ``brand_<key>`` (the mode is
#: kept in ``display_name``), so no new table is needed; ``get_names`` ignores them. No row means Words (the default since round 22; Search, Home and Sign out are always icons).
BRAND_WORDS = "words"
BRAND_LOGO = "logo"
BRAND_MODES = (BRAND_WORDS, BRAND_LOGO)
BRAND_KEYS = (KEY_HOME, KEY_DIARY, KEY_FEES)
BRAND_PREFIX = "brand_"


def read_all():
    """Return ``(names, brand_modes, site_name)`` from one query: ``{key: display_name}``, ``{key: "words" | "logo"}``
    and the website's name.

    Defaults fill every missing row. The context processors use this so a page asks the table once.
    """
    names = dict(DEFAULT_NAMES)
    modes = {key: BRAND_WORDS for key in BRAND_KEYS}
    site = default_site_name()
    wanted = [*DEFAULT_NAMES, *(BRAND_PREFIX + key for key in BRAND_KEYS), KEY_SITE]
    for row in SuiteName.objects.filter(key__in=wanted):
        if row.key == KEY_SITE:
            site = " ".join(row.display_name.split()) or site
        elif row.key in DEFAULT_NAMES:
            if row.display_name.strip():
                names[row.key] = row.display_name
        elif row.display_name in BRAND_MODES:
            modes[row.key[len(BRAND_PREFIX):]] = row.display_name
    return names, modes, site


def get_site_name():
    """The website's name (Admins > Appearance), else ``settings.SITE_NAME`` (Madon.co.in). Never raises."""
    try:
        row = SuiteName.objects.filter(key=KEY_SITE).first()
    except Exception:
        return default_site_name()
    return (" ".join(row.display_name.split()) if row is not None else "") or default_site_name()


def set_site_name(value):
    """Store the website's name; blank goes back to the default."""
    value = " ".join((value or "").split())
    if value:
        SuiteName.objects.update_or_create(key=KEY_SITE, defaults={"display_name": value})
    else:
        SuiteName.objects.filter(key=KEY_SITE).delete()


def get_names():
    """Return ``{key: display_name}`` for every key, using defaults for missing rows."""
    return read_all()[0]


def set_names(new_names):
    """Store ``{key: display_name}`` (only known keys)."""
    for key, value in new_names.items():
        if key in DEFAULT_NAMES:
            SuiteName.objects.update_or_create(key=key, defaults={"display_name": value})


def get_brand_modes():
    """Return ``{key: "words" | "logo"}`` for Home, the Case Law Diary and the Fee Register (Words when not set)."""
    return read_all()[1]


def set_brand_modes(new_modes):
    """Store ``{key: mode}`` (only known keys and modes)."""
    for key, mode in new_modes.items():
        if key in BRAND_KEYS and mode in BRAND_MODES:
            SuiteName.objects.update_or_create(key=BRAND_PREFIX + key, defaults={"display_name": mode})
