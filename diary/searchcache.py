"""A short-lived, in-memory copy of what Search reads, so a search does not read and prepare the whole profile every time.

What is kept is the list of searchable records of one profile (and of one kind of search). Before it is used again, a
*fingerprint* of the profile's seven record tables is compared with the one taken when the list was built: for each table the
number of rows, how many are in the Trash, the newest ``updated_at``, the sum of the ``version`` numbers, and the sum and
largest of the ids. Every edit, move, delete, restore and Undo goes through ``services.core.commit`` (version +1, ``updated_at``
now), and an import or a restore changes the counts or ids, so any of them gives a different fingerprint and the list is built
again. No write path has to remember to tell the cache anything. A copy is also dropped after ``SEARCH_CACHE_SECONDS``
(10 minutes), whatever the fingerprint says, as a last guard.

The cache lives in each web worker's own memory (nothing is shared, nothing is stored on disk or in the database) and keeps at most
``MAX_ENTRIES`` lists of at most ``MAX_RECORDS`` records. ``SEARCH_CACHE_SECONDS=0`` switches it off (the tests do, apart from
the ones about the cache itself). The fingerprint costs seven small aggregate queries; a rebuild costs what a search cost before.
"""
import threading
import time
from collections import OrderedDict

from django.conf import settings
from django.db.models import Count, Max, Q, Sum

from .models import Case, Item, Note, Section, Subject, Subtopic, Topic

MAX_ENTRIES = 6
MAX_RECORDS = 150_000

_TABLES = (Subject, Topic, Subtopic, Section, Item, Case, Note)
_lock = threading.Lock()
_entries = OrderedDict()  # key -> (fingerprint, built_at, records)


def enabled():
    return getattr(settings, "SEARCH_CACHE_SECONDS", 0) > 0


def fingerprint(profile):
    """A tuple that changes whenever any live or trashed record of ``profile`` is added, changed, trashed, restored or removed."""
    parts = []
    for model in _TABLES:
        row = model._base_manager.filter(profile=profile).aggregate(
            rows=Count("pk"),
            trashed=Count("pk", filter=Q(deleted_at__isnull=False)),
            changed=Max("updated_at"),
            versions=Sum("version"),
            ids=Sum("pk"),
            last=Max("pk"),
        )
        parts.append((row["rows"], row["trashed"], row["changed"], row["versions"], row["ids"], row["last"]))
    return tuple(parts)


def clear():
    with _lock:
        _entries.clear()


def cached(profile, variant, build):
    """``build()``'s list for this profile and kind of search (``variant``), reused while the profile's fingerprint is unchanged.

    The fingerprint is taken BEFORE building: if something changes while the list is being built, the stored fingerprint is
    already out of date, so the next search builds again (a stale list is never served as current).
    """
    if not enabled():
        return build()
    taken = fingerprint(profile)
    key = (profile.pk, profile.created_at, variant)
    now = time.monotonic()
    ttl = settings.SEARCH_CACHE_SECONDS
    with _lock:
        hit = _entries.get(key)
        if hit is not None and hit[0] == taken and now - hit[1] < ttl:
            _entries.move_to_end(key)
            return hit[2]
    records = build()
    if len(records) <= MAX_RECORDS:
        with _lock:
            _entries[key] = (taken, now, records)
            _entries.move_to_end(key)
            while len(_entries) > MAX_ENTRIES:
                _entries.popitem(last=False)
    return records
