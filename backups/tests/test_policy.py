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


class EffectiveRetentionTests(unittest.TestCase):
    def test_floor_is_30(self):
        self.assertEqual(policy.effective_retention_days(1), 30)
        self.assertEqual(policy.effective_retention_days("0"), 30)

    def test_larger_values_kept(self):
        self.assertEqual(policy.effective_retention_days(35), 35)
        self.assertEqual(policy.effective_retention_days("90"), 90)


class SelectExpiredTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(policy.select_expired([], NOW, 35), [])

    def test_removes_only_older_than_retention(self):
        entries = [(1, ago(10)), (2, ago(29)), (3, ago(31)), (4, ago(40)), (5, ago(100))]
        self.assertEqual(sorted(policy.select_expired(entries, NOW, 35)), [4, 5])

    def test_retention_below_30_is_raised_to_30(self):
        entries = [(1, ago(10)), (2, ago(29)), (3, ago(31))]
        self.assertEqual(policy.select_expired(entries, NOW, 5), [3])

    def test_newest_is_always_kept(self):
        entries = [(1, ago(100)), (2, ago(200))]
        self.assertEqual(policy.select_expired(entries, NOW, 35), [2])

    def test_single_old_entry_is_kept(self):
        self.assertEqual(policy.select_expired([(7, ago(500))], NOW, 35), [])


class IsStaleTests(unittest.TestCase):
    def test_none_is_stale(self):
        self.assertTrue(policy.is_stale(None, NOW, 36))

    def test_recent_is_not_stale(self):
        self.assertFalse(policy.is_stale(NOW - timedelta(hours=35), NOW, 36))

    def test_old_is_stale(self):
        self.assertTrue(policy.is_stale(NOW - timedelta(hours=37), NOW, 36))


if __name__ == "__main__":
    unittest.main()
