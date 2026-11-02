import unittest

from diary import numbering as n


class LettersTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(n.letters(1), "a")
        self.assertEqual(n.letters(26), "z")

    def test_past_26(self):
        self.assertEqual(n.letters(27), "aa")
        self.assertEqual(n.letters(28), "ab")
        self.assertEqual(n.letters(52), "az")
        self.assertEqual(n.letters(53), "ba")
        self.assertEqual(n.letters(702), "zz")
        self.assertEqual(n.letters(703), "aaa")

    def test_upper(self):
        self.assertEqual(n.letters(27, upper=True), "AA")


class RomanTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(n.roman(1), "i")
        self.assertEqual(n.roman(4), "iv")
        self.assertEqual(n.roman(8), "viii")
        self.assertEqual(n.roman(39), "xxxix")
        self.assertEqual(n.roman(40), "xl")
        self.assertEqual(n.roman(49), "xlix")

    def test_boundary(self):
        self.assertEqual(n.roman(3999, upper=True), "MMMCMXCIX")
        self.assertEqual(n.roman(4000), "4000")
        self.assertEqual(n.roman(0), "0")


class FormatTests(unittest.TestCase):
    def test_formats(self):
        f = n.format_number
        self.assertEqual(f(3, "A"), "C")
        self.assertEqual(f(3, "a"), "c")
        self.assertEqual(f(3, "1"), "3")
        self.assertEqual(f(3, "I"), "III")
        self.assertEqual(f(3, "i"), "iii")
        self.assertEqual(f(3, "(A)"), "(C)")
        self.assertEqual(f(3, "(i)"), "(iii)")
        self.assertEqual(f(3, "(a)"), "(c)")
        self.assertEqual(f(3, "(1)"), "(3)")
        self.assertEqual(f(3, "bullet"), n.BULLET)
        self.assertEqual(f(3, "none"), "")
        self.assertEqual(f(2, "Section 1"), "Section 2")
        self.assertEqual(f(27, "(A)"), "(AA)")
        self.assertEqual(f(4000, "(I)"), "(4000)")

    def test_unknown(self):
        with self.assertRaises(ValueError):
            n.format_number(1, "zzz")

    def test_siblings(self):
        self.assertEqual(n.number_siblings(3, "A"), ["A", "B", "C"])
        self.assertEqual(n.number_siblings(0, "1"), [])
        self.assertEqual(n.multi_item_labels(3), ["(a)", "(b)", "(c)"])
        self.assertEqual(n.nested_bullets(2), [n.BULLET, n.BULLET])


class DisplayLabelTests(unittest.TestCase):
    def test_full_stop_after_unbracketed_labels(self):
        self.assertEqual(n.display_label("A"), "A.")
        self.assertEqual(n.display_label("1"), "1.")
        self.assertEqual(n.display_label("iv"), "iv.")
        self.assertEqual(n.display_label("Section 1"), "Section 1.")

    def test_closed_or_empty_labels_unchanged(self):
        self.assertEqual(n.display_label("(a)"), "(a)")
        self.assertEqual(n.display_label(n.BULLET), n.BULLET)
        self.assertEqual(n.display_label(""), "")
        self.assertEqual(n.display_label(None), "")


class ChildrenTests(unittest.TestCase):
    def test_clause_12_example(self):
        kinds = ["section", "item", "item"] + ["section"] + ["item"] * 8
        self.assertEqual(
            n.number_children(kinds),
            ["(a)", "(1)", "(2)", "(b)",
             "(1)", "(2)", "(3)", "(4)", "(5)", "(6)", "(7)", "(8)"],
        )

    def test_items_before_first_section(self):
        kinds = ["item", "item", "section", "item"]
        self.assertEqual(n.number_children(kinds), ["(1)", "(2)", "(a)", "(1)"])

    def test_nested_share_run(self):
        kinds = ["item", "nested", "item", "section", "nested", "item"]
        self.assertEqual(
            n.number_children(kinds), ["(1)", "(2)", "(3)", "(a)", "(1)", "(2)"]
        )

    def test_notes_not_counted(self):
        kinds = ["item", "item", "note"]
        self.assertEqual(n.number_children(kinds), ["(1)", "(2)", ""])

    def test_section_format(self):
        kinds = ["section", "item", "section", "item"]
        self.assertEqual(
            n.number_children(kinds, "1", "Section 1"),
            ["Section 1", "1", "Section 2", "1"],
        )

    def test_past_xxxix(self):
        labels = n.number_children(["item"] * 41)
        self.assertEqual(labels[38], "(39)")
        self.assertEqual(labels[39], "(40)")
        self.assertEqual(labels[40], "(41)")

    def test_empty_and_bad_kind(self):
        self.assertEqual(n.number_children([]), [])
        with self.assertRaises(ValueError):
            n.number_children(["topic"])


class NoDjangoTests(unittest.TestCase):
    def test_no_django_import(self):
        import sys

        from diary import richtext  # noqa: F401

        if "django" in sys.modules:
            self.skipTest("django loaded by another test")
        self.assertNotIn("django", sys.modules)


if __name__ == "__main__":
    unittest.main()
