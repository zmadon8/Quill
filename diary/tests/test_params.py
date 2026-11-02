import unittest

from diary.params import safe_int


class SafeIntTests(unittest.TestCase):
    def test_plain_digits(self):
        self.assertEqual(safe_int("42"), 42)
        self.assertEqual(safe_int("0"), 0)

    def test_junk_is_none(self):
        for raw in ("", "-1", "1.5", "abc", " 3", "\u00b2", "\u0663", "\uff11", None):
            self.assertIsNone(safe_int(raw), raw)
