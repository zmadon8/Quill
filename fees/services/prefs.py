"""Per-user interface preferences for the Fee Register (owner item 2.14: resizable column widths).

``get_prefs(profile, user, key)`` returns the saved JSON object for a key (``{}`` when none) and
``set_pref(profile, user, key, data)`` validates and stores it. One ``FeesUserPrefs`` row per
``(profile, user, key)``.

Only keys of the form ``col-widths:<table-id>`` are accepted (for example ``col-widths:memos``). The value
is a JSON object of column key to a whole number of pixels between ``MIN_PX`` and ``MAX_PX``, at most
``MAX_COLUMNS`` columns and ``MAX_BYTES`` of JSON, so a client cannot fill the table.

This is interface state, not fee data. So, on purpose, ``set_pref`` does NOT call ``memos.touch``: it must not
bump ``data_version`` or drop the statistics cache, and a Reader may save their own preferences (the view
allows any Fee Register role). The row is private to the user: every query filters on the user as well as the
profile.
"""
import json
import re

from django.db import transaction

from fees.errors import FeesError
from fees.models import FeesUserPrefs

__all__ = [
    "KEY_RE", "MIN_PX", "MAX_PX", "MAX_COLUMNS", "MAX_BYTES", "SETTINGS_KEY", "get_prefs", "get_all_widths", "set_pref",
    "get_personal", "set_personal", "personal_default_tab", "personal_items_per_page",
]

KEY_RE = re.compile(r"^col-widths:[a-z0-9][a-z0-9_-]{0,39}$")
_COLUMN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")
MIN_PX = 40
MAX_PX = 1200
MAX_COLUMNS = 60
MAX_BYTES = 4000


def _invalid(message):
    return FeesError("INVALID_PREF", message)


def _check_key(key):
    key = str(key or "")
    if not KEY_RE.match(key):
        raise _invalid("Unknown preference.")
    return key


def get_prefs(profile, user, key):
    """The saved object for ``key`` ({} when none). Read only."""
    key = _check_key(key)
    row = FeesUserPrefs.objects.filter(profile=profile, user=user, key=key).first()
    return dict(row.data) if row is not None and isinstance(row.data, dict) else {}


def get_all_widths(profile, user):
    """Every saved column-width object as ``{table_id: {column: px}}``; one query, read only.

    Rendered into each page so the widths apply before first paint, with no extra request.
    """
    prefix = "col-widths:"
    rows = FeesUserPrefs.objects.filter(profile=profile, user=user, key__startswith=prefix).values_list("key", "data")
    return {key[len(prefix):]: dict(data) for key, data in rows if isinstance(data, dict)}


def _clean(data):
    if not isinstance(data, dict):
        raise _invalid("Column widths must be an object.")
    if len(data) > MAX_COLUMNS:
        raise _invalid(f"At most {MAX_COLUMNS} columns can be saved.")
    clean = {}
    for column, width in data.items():
        if not isinstance(column, str) or not _COLUMN_RE.match(column):
            raise _invalid("A column name is not valid.")
        if isinstance(width, bool) or not isinstance(width, int):
            raise _invalid("A column width must be a whole number of pixels.")
        if width < MIN_PX or width > MAX_PX:
            raise _invalid(f"A column width must be between {MIN_PX} and {MAX_PX} pixels.")
        clean[column] = width
    if len(json.dumps(clean)) > MAX_BYTES:
        raise _invalid("The saved widths are too large.")
    return clean


def set_pref(profile, user, key, data):
    """Validates and stores ``data`` for ``key``; returns the stored object. No ``touch`` (see the module doc)."""
    key = _check_key(key)
    clean = _clean(data)
    with transaction.atomic():
        FeesUserPrefs.objects.update_or_create(
            profile=profile, user=user, key=key, defaults={"data": clean}
        )
    return clean


# ---------------------------------------------------------------------------
# My settings: the two personal Fee Register choices (Opening page, Items per page)
# ---------------------------------------------------------------------------

#: The ``FeesUserPrefs`` key holding a user's personal Fee Register settings: ``{"default_tab": ..., "items_per_page": ...}``.
#: It is not reachable through ``set_pref`` / the prefs endpoint (their keys are column widths only); only
#: ``set_personal`` writes it, after the same validation as the profile settings.
SETTINGS_KEY = "settings"
_PERSONAL_FIELDS = ("default_tab", "items_per_page")
#: Rows per page when the user has not chosen a number.
DEFAULT_ITEMS_PER_PAGE = 50


def get_personal(profile, user):
    """The user's saved personal settings, only the known keys present ({} when none). Read only."""
    row = FeesUserPrefs.objects.filter(profile=profile, user=user, key=SETTINGS_KEY).first()
    data = row.data if row is not None and isinstance(row.data, dict) else {}
    return {name: data[name] for name in _PERSONAL_FIELDS if name in data}


def set_personal(profile, user, data):
    """Saves the personal Opening page and/or Items per page; returns the stored object.

    A key given as ``None`` is removed, so the standard value applies again. Each value is checked
    exactly like the profile setting of the same name (a bad value raises ``FeesError`` 422). No ``touch``: this is
    one person's preference, not fee data, and a Reader may keep their own.
    """
    from fees.services import settings as settings_service  # lazy: keeps this module's import light

    clean = get_personal(profile, user)
    for name in _PERSONAL_FIELDS:
        if name not in data:
            continue
        if data[name] is None:
            clean.pop(name, None)
        else:
            clean[name] = settings_service._validate_candidate(name, data[name])
    with transaction.atomic():
        FeesUserPrefs.objects.update_or_create(
            profile=profile, user=user, key=SETTINGS_KEY, defaults={"data": clean}
        )
    return clean


def personal_default_tab(profile, user, settings):
    """The Opening page for this user: their own choice, else ``memos``. (``settings`` is kept for the callers.)"""
    return get_personal(profile, user).get("default_tab") or "memos"


def personal_items_per_page(profile, user, settings):
    """Items per page for this user (0 means All): their own choice, else 50. (``settings`` is kept for the callers.)"""
    own = get_personal(profile, user).get("items_per_page")
    return DEFAULT_ITEMS_PER_PAGE if own is None else own
