"""Tests for the heavy-operation advisory lock (T1.5, R-NFR-6).

The lock is a PostgreSQL feature (``pg_try_advisory_lock`` / ``pg_advisory_unlock``).
Tests that need the real lock are skipped on any other backend (for example a local
SQLite run), where the guard degrades to a no-op. CI runs on PostgreSQL, so the real
behaviour is exercised there.

Covered:

* on PostgreSQL a second, separate connection that already holds the lock makes
  ``heavy_operation`` raise :class:`Busy`; after that connection releases, the
  guard works again (second concurrent acquisition gets ``Busy``);
* the lock is released after an exception inside the block, so it can be taken
  again straight away;
* on a non-PostgreSQL backend the guard is a no-op that always yields;
* ``templates/fees/busy.html`` renders through the template loader.
"""
import unittest

from django.db import connection, connections
from django.template.loader import render_to_string
from django.test import TestCase, TransactionTestCase

from fees.services.heavy import Busy, _lock_key, heavy_operation

POSTGRES_ONLY = unittest.skipUnless(
    connection.vendor == "postgresql",
    "Advisory locks are a PostgreSQL feature; skipped on other databases.",
)


class LockKeyTests(TestCase):
    def test_key_is_stable_and_in_bigint_range(self):
        key = _lock_key("suite_backup")
        self.assertEqual(key, _lock_key("suite_backup"))
        self.assertNotEqual(_lock_key("suite_backup"), _lock_key("suite_restore"))
        self.assertGreaterEqual(key, -(2 ** 63))
        self.assertLessEqual(key, 2 ** 63 - 1)


class HeavyNoOpTests(TestCase):
    """On a non-PostgreSQL backend the guard must not get in the way."""

    def test_yields_without_error_off_postgres(self):
        if connection.vendor == "postgresql":
            self.skipTest("This no-op behaviour only applies off PostgreSQL.")
        with heavy_operation("suite_backup"):
            ran = True
        self.assertTrue(ran)
        # And it can be entered again, because nothing is actually locked.
        with heavy_operation("suite_backup"):
            pass


class HeavyReleaseTests(TestCase):
    def test_lock_is_released_after_an_exception(self):
        # Works on every backend: off PostgreSQL this is a no-op, on PostgreSQL the
        # finally must release so the next acquire on the same connection succeeds.
        with self.assertRaises(ValueError):
            with heavy_operation("suite_backup"):
                raise ValueError("boom")
        # Acquiring again must not raise Busy.
        with heavy_operation("suite_backup"):
            pass


@POSTGRES_ONLY
class HeavyConcurrencyTests(TransactionTestCase):
    """Real advisory-lock behaviour across two separate connections.

    A ``TransactionTestCase`` is used so the default connection is not wrapped in a
    single test transaction; the second connection then sees a genuinely separate
    session, which is what advisory-lock contention needs.
    """

    def _other_connection(self):
        # A second, independent session using the same database settings.
        other = connections.create_connection("default")
        other.connect()
        return other

    def test_second_acquisition_gets_busy_then_recovers(self):
        key = _lock_key("suite_backup")
        other = self._other_connection()
        try:
            with other.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", [key])
                self.assertTrue(cursor.fetchone()[0])
            # The lock is held elsewhere, so our guard must refuse.
            with self.assertRaises(Busy):
                with heavy_operation("suite_backup"):
                    self.fail("the block must not run while the lock is held")
            # Release on the other connection; now the guard can take it.
            with other.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [key])
                self.assertTrue(cursor.fetchone()[0])
            with heavy_operation("suite_backup"):
                pass
        finally:
            with other.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock_all()")
            other.close()

    def test_busy_does_not_release_a_lock_it_never_took(self):
        key = _lock_key("suite_restore")
        other = self._other_connection()
        try:
            with other.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", [key])
                self.assertTrue(cursor.fetchone()[0])
            with self.assertRaises(Busy):
                with heavy_operation("suite_restore"):
                    pass
            # The other connection must still hold exactly one lock: a single unlock
            # returns True (not released by our failed guard already).
            with other.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [key])
                self.assertTrue(cursor.fetchone()[0])
        finally:
            with other.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock_all()")
            other.close()


class BusyTemplateTests(TestCase):
    def test_busy_template_renders(self):
        html = render_to_string("fees/busy.html")
        self.assertIn("busy", html.lower())
        self.assertIn("try again", html.lower())
