"""Plain unittest: runs without Django.  python -m unittest backups.tests.test_policy"""
import importlib.util
import pathlib
import unittest
from datetime import datetime, timedelta, timezone

# Load policy.py directly so importing the 'backups' package never needs Django.
_spec = importlib.util.spec_from_file_location(
    "backups_policy", pathlib.Path(__file__).resolve().parent.parent / "policy.py"
)
policy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(policy)

NOW = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)


def ago(days):
    return NOW - timedelta(days=days)


class EffectiveKeepCountTests(unittest.TestCase):
    def test_floor_is_1(self):
        self.assertEqual(policy.effective_keep_count(0), 1)
        self.assertEqual(policy.effective_keep_count("-5"), 1)

    def test_values_kept_and_bad_value_gives_default(self):
        self.assertEqual(policy.effective_keep_count(30), 30)
        self.assertEqual(policy.effective_keep_count("12"), 12)
        self.assertEqual(policy.effective_keep_count("x"), 30)


class SelectOverCountTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(policy.select_over_count([], 30), [])

    def test_removes_only_the_oldest_beyond_the_count(self):
        entries = [(1, ago(10)), (2, ago(29)), (3, ago(31)), (4, ago(40)), (5, ago(100))]
        self.assertEqual(sorted(policy.select_over_count(entries, 3)), [4, 5])

    def test_fewer_than_count_removes_nothing_however_old(self):
        self.assertEqual(policy.select_over_count([(7, ago(500)), (8, ago(900))], 30), [])

    def test_newest_is_always_kept(self):
        entries = [(1, ago(100)), (2, ago(200))]
        self.assertEqual(policy.select_over_count(entries, 0), [2])

    def test_protected_ids_are_never_returned(self):
        entries = [(1, ago(1)), (2, ago(2)), (3, ago(3))]
        self.assertEqual(policy.select_over_count(entries, 1, protect_ids=(2,)), [3])


class IsStaleTests(unittest.TestCase):
    def test_none_is_stale(self):
        self.assertTrue(policy.is_stale(None, NOW, 36))

    def test_recent_is_not_stale(self):
        self.assertFalse(policy.is_stale(NOW - timedelta(hours=35), NOW, 36))

    def test_old_is_stale(self):
        self.assertTrue(policy.is_stale(NOW - timedelta(hours=37), NOW, 36))


if __name__ == "__main__":
    unittest.main()
