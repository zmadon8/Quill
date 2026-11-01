"""Display names for the Home page and each program in the suite.

Only the names people see can be changed (Settings). Keys are fixed internal identifiers.
A key with no stored row uses its default here, so a fresh install or an older backup
that lacks the table still shows sensible names.
"""
from .models import SuiteName

KEY_HOME = "home"
KEY_DIARY = "diary"

DEFAULT_NAMES = {
    KEY_HOME: "Home",
    KEY_DIARY: "Case Law Diary",
}
MAX_NAME_LENGTH = 60


def get_names():
    """Return ``{key: display_name}`` for every key, using defaults for missing rows."""
    names = dict(DEFAULT_NAMES)
    for row in SuiteName.objects.filter(key__in=DEFAULT_NAMES):
        if row.display_name.strip():
            names[row.key] = row.display_name
    return names


def set_names(new_names):
    """Store ``{key: display_name}`` (only known keys)."""
    for key, value in new_names.items():
        if key in DEFAULT_NAMES:
            SuiteName.objects.update_or_create(key=key, defaults={"display_name": value})
