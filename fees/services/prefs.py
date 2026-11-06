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

__all__ = ["KEY_RE", "MIN_PX", "MAX_PX", "MAX_COLUMNS", "MAX_BYTES", "get_prefs", "set_pref"]

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
