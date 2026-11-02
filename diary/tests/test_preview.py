import sys
import unittest

from diary import preview


def labels(rows):
    return [(r["kind"], r["label"], r["text"]) for r in rows]


def only(rows, kind):
    return [r["label"] for r in rows if r["kind"] == kind]


class DefaultsTests(unittest.TestCase):
    def setUp(self):
        self.rows = preview.build_preview({})

    def test_starts_with_the_subject(self):
        self.assertEqual(self.rows[0]["kind"], "subject")
        self.assertEqual(self.rows[0]["text"], "Sample Subject")
        self.assertEqual(self.rows[0]["label"], "")

    def test_default_formats(self):
        self.assertEqual(only(self.rows, "topic"), ["A.", "B."])
        self.assertEqual(only(self.rows, "subtopic"), ["1.", "2."])
        self.assertEqual(only(self.rows, "section"), ["(a)", "(b)"])
        self.assertEqual(only(self.rows, "citation"), ["(a)", "(b)"])
        items = [r["label"] for r in self.rows if r["kind"] == "item"]
        self.assertEqual(items, ["(1)", "(2)", "(1)"])

    def test_restart_after_section(self):
        last_item = [r for r in self.rows if r["text"].startswith("First Item after")][0]
        self.assertEqual(last_item["label"], "(1)")

    def test_two_topics_so_letters_show(self):
        self.assertEqual(len(only(self.rows, "topic")), 2)

    def test_indent_grows_with_depth(self):
        by_text = {r["text"]: r["indent"] for r in self.rows}
        self.assertLess(by_text["Sample Topic"], by_text["Sample Sub-topic 1"])
        self.assertLess(by_text["Sample Section"], by_text["First Item"])


class ChosenFormatsTests(unittest.TestCase):
    def test_changed_set(self):
        rows = preview.build_preview({
            "topic": "I", "subtopic": "(A)", "section": "a", "item": "(a)",
            "multi_citation": "1",
        })
        self.assertEqual(only(rows, "topic"), ["I.", "II."])
        self.assertEqual(only(rows, "subtopic"), ["(A)", "(B)"])
        self.assertEqual(only(rows, "section"), ["a.", "b."])
        self.assertEqual(only(rows, "citation"), ["1", "2"])
        items = [r["label"] for r in rows if r["kind"] == "item"]
        self.assertEqual(items, ["(a)", "(b)", "(a)"])

    def test_none_and_section_n(self):
        rows = preview.build_preview({"topic": "none", "section": "Section 1", "item": "none"})
        self.assertEqual(only(rows, "topic"), ["", ""])
        self.assertEqual(only(rows, "section"), ["Section 1.", "Section 2."])
        self.assertEqual([r["label"] for r in rows if r["text"] == "First Item"], [""])

    def test_restart_after_section_with_other_formats(self):
        rows = preview.build_preview({"item": "A", "section": "Section 1"})
        items = [r["label"] for r in rows if r["kind"] == "item"]
        self.assertEqual(items, ["A.", "B.", "A."])

    def test_bullets_are_not_given_a_full_stop(self):
        rows = preview.build_preview({"topic": "bullet", "item": "bullet"})
        self.assertEqual(only(rows, "topic"), ["\u2022", "\u2022"])

    def test_blank_values_use_defaults(self):
        self.assertEqual(preview.build_preview({"topic": ""}), preview.build_preview({}))


class PureTests(unittest.TestCase):
    def test_does_not_import_django(self):
        if "django" in sys.modules:
            self.skipTest("django loaded by another test")
        self.assertNotIn("django", sys.modules)


if __name__ == "__main__":
    unittest.main()
