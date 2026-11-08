"""One-at-a-time guard for heavy suite operations (R-NFR-6).

A heavy job (suite backup, suite restore, Excel import or restore, annual export,
clear-all) can use a large amount of memory. Running two at once on the small
Render worker risks the memory ceiling, so only one may run at a time. This is
enforced with a PostgreSQL session-level advisory lock: the first request takes
the lock, a second request that cannot take it is told the system is busy.

On a non-PostgreSQL backend (for example SQLite in a local test run) advisory
locks do not exist, so the guard degrades to a no-op that always "acquires": the
rest of the application still works and concurrency is simply not enforced. The
real behaviour is exercised by CI, which runs on PostgreSQL. The concurrency
test is skipped when ``connection.vendor != "postgresql"``.

No module-level state and no import of diary or fees models: this helper only
needs the standard library and the current database connection.
"""
import contextlib
import hashlib

from django.db import connection


class Busy(Exception):
    """Another heavy operation holds the lock.

    Views turn this into a 503 "busy, try again" page (see templates/fees/busy.html).
    """

    def __init__(self, message=None):
        super().__init__(message or "Another large job is running. Please try again in a minute.")


# pg_try_advisory_lock takes a signed 64-bit integer (bigint). These bounds map
# an unsigned hash into that range.
_BIGINT_MIN = -(2 ** 63)
_BIGINT_SPAN = 2 ** 64


def _lock_key(name):
    """A stable signed 64-bit lock key derived from ``name``.

    The same name always gives the same key across processes, so every worker
    that calls ``heavy_operation("suite_backup")`` competes for the same lock.
    The first eight bytes of a SHA-256 digest are read as an unsigned 64-bit
    integer and shifted into the signed bigint range PostgreSQL accepts.
    """
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    unsigned = int.from_bytes(digest[:8], "big")
    return (unsigned % _BIGINT_SPAN) + _BIGINT_MIN


@contextlib.contextmanager
def heavy_operation(name):
    """Run a heavy operation while holding the named advisory lock.

    On PostgreSQL this tries ``pg_try_advisory_lock``; if the lock is already
    held it raises :class:`Busy` without blocking, otherwise it yields and
    always releases the lock in a ``finally`` (even if the wrapped block raises).

    PostgreSQL session advisory locks are re-entrant and counted within one
    session: the same connection may take the same lock more than once and each
    acquire must be matched by one release. ``create_backup`` is called inside
    ``restore_backup`` (the pre-restore safety backup), so the "suite_backup"
    lock may be acquired while another heavy guard is already held on the same
    connection; the stacked acquire succeeds and each ``finally`` releases once,
    so the count stays balanced. A second *separate* connection still cannot take
    the lock and gets :class:`Busy`.

    On a non-PostgreSQL backend there is no advisory lock, so this is a no-op that
    always yields.
    """
    if connection.vendor != "postgresql":
        # SQLite and the like: no advisory locks, so do not enforce concurrency.
        yield
        return

    key = _lock_key(name)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [key])
        acquired = cursor.fetchone()[0]
    if not acquired:
        # Did not acquire the lock, so do not release one we never took.
        raise Busy()
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [key])
