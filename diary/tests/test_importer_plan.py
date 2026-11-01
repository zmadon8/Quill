"""Pure tests of the Word reader, the record plan and the reports (no database needed)."""
import unittest
from pathlib import Path

from diary.importer import plan as plan_module
from diary.importer.docx_reader import DocxError, read_docx
from diary.importer.plan import EXPECTED, build_plan, classify_item, runs_to_html, strip_colon, summary_counts
from diary.importer.report import dry_run_report, section_groups
from diary.importer.docx_reader import Run
from diary.tests.docx_builder import SMALL, make_docx

REAL_FILE = Path(__file__).resolve().parents[2] / "Case Law Diary.docx"


def small_plan(lines=None):
    paragraphs, notes = read_docx(make_docx(lines or SMALL))
    return build_plan(paragraphs, notes)


class ClassifyItemTests(unittest.TestCase):
    def test_clean_line_is_split_at_the_dash(self):
        self.assertEqual(
            classify_item("A proposition - Alpha v Beta [(2010) 1 SCC 1]"),
            (None, "A proposition", "Alpha v Beta [(2010) 1 SCC 1]"),
        )

    def test_each_doubtful_shape_is_kept_whole_with_its_reason(self):
        cases = {
            " leading space - X [(2010) 1 SCC 1]": "spaces",
            "Open - X [(2010) 1 SCC 1": "unbalanced",
            "[A whole remark - X [(2010) 1 SCC 1]]": "bracketed",
            "Many - (i) X [(2010) 1 SCC 1] ; (ii) Y [(2011) 2 SCC 2]": "multi_marker",
            "Only a case name": "no_dash",
            "A - B - C [(2010) 1 SCC 1]": "many_dash",
            "Flagged - X [(2010) 1 SCC 1] [NO LONGER GOOD LAW]": "flag",
            "Prop - Bom HC order of the court": "not_citation",
            "Double  space - X [(2010) 1 SCC 1]": "double_space",
        }
        for line, reason in cases.items():
            with self.subTest(line=line):
                self.assertEqual(classify_item(line), (reason, line, ""))

    def test_year_and_report_name_without_brackets_is_accepted(self):
        self.assertIsNone(classify_item("Prop - Case v Case (2019) 5 SCC 192")[0])

    def test_trailing_colon_rule(self):
        self.assertEqual(strip_colon("Scope:"), "Scope")
        self.assertEqual(strip_colon("Scope : "), "Scope")
        self.assertEqual(strip_colon("Scope"), "Scope")


class RunsToHtmlTests(unittest.TestCase):
    def test_slice_keeps_formatting_and_escapes(self):
        runs = [Run("A & B - ", bold=True), Run("cite", italic=True)]
        self.assertEqual(runs_to_html(runs, 0, 5), "<p><b>A &amp; B</b></p>")
        self.assertEqual(runs_to_html(runs), "<p><b>A &amp; B - </b><i>cite</i></p>")

    def test_unformatted_runs_merge(self):
        self.assertEqual(runs_to_html([Run("a"), Run("b")]), "<p>ab</p>")


class SmallFilePlanTests(unittest.TestCase):
    def setUp(self):
        self.plan = small_plan()
        self.by_text = {n.original_line: n for n in self.plan.nodes}

    def test_no_problems_and_counts(self):
        self.assertEqual(self.plan.problems, [])
        counts = summary_counts(self.plan)
        self.assertEqual(counts["subjects"], 4)
        self.assertEqual(counts["main_subjects"], 2)
        self.assertEqual(counts["other_subjects"], 2)
        self.assertEqual(counts["topics"], 3)
        self.assertEqual(counts["sections"], 2)
        self.assertEqual(counts["blank_paragraphs"], 1)
        self.assertEqual(counts["colon_changes"], 2)

    def test_miscellaneous_is_not_a_subject_and_its_topics_are_other_subjects(self):
        names = [n.name for n in self.plan.of("subject")]
        self.assertNotIn("Miscellaneous", names)
        stamp = self.by_text["Stamp Act"]
        self.assertTrue(stamp.other_subject)
        self.assertEqual(stamp.other_position, 1)
        self.assertEqual(self.by_text["Tender"].other_position, 2)
        self.assertEqual([r for r, _ in self.plan.skipped_headings], ["para-%04d" % 11])

    def test_other_subject_holds_sub_topics_and_items_directly(self):
        duty = self.by_text["Duty"]
        self.assertIs(duty.parent, self.by_text["Stamp Act"])
        self.assertIs(self.by_text["Tender item - Broken [(2019) 1 SCC 1"].parent, self.by_text["Tender"])

    def test_colon_removed_from_names_but_original_kept(self):
        node = self.by_text["Scope:"]
        self.assertEqual(node.name, "Scope")
        self.assertTrue(node.colon_removed)
        self.assertEqual(node.original_line, "Scope:")

    def test_clean_and_flagged_items(self):
        clean = self.by_text["Clean proposition - Alpha v Beta [(2010) 1 SCC 1]"]
        self.assertEqual(clean.citation, "Alpha v Beta [(2010) 1 SCC 1]")
        self.assertEqual(clean.text_html, "<p>Clean proposition</p>")
        self.assertFalse(clean.needs_review)
        whole = self.by_text["Only a case name"]
        self.assertEqual((whole.citation, whole.reason), ("", "no_dash"))
        self.assertTrue(whole.needs_review)
        self.assertIn("Imported whole as Text with no Citation", whole.review_note)

    def test_formatting_survives_in_text_and_citation_is_plain(self):
        node = self.by_text["Italic start - Delta [(2012) 3 SCC 3]"]
        self.assertEqual(node.text_html, "<p>Italic start</p>")
        self.assertEqual(node.citation, "Delta [(2012) 3 SCC 3]")

    def test_positions_restart_per_parent(self):
        self.assertEqual(self.by_text["Scope:"].position, 1)
        self.assertEqual(self.by_text["Direct items"].position, 2)
        self.assertEqual(self.by_text["Clean proposition - Alpha v Beta [(2010) 1 SCC 1]"].position, 1)
        self.assertEqual(self.by_text["Direct one - Eps [(2013) 4 SCC 4]"].position, 1)
        self.assertEqual(self.by_text["Direct two - Zeta [(2014) 5 SCC 5]"].position, 2)

    def test_sections_share_the_position_order_with_their_items(self):
        a, b = self.by_text["Ex Parte"], self.by_text["Determining"]
        self.assertEqual((a.position, b.position), (1, 3))
        self.assertTrue(a.needs_review and b.needs_review)
        self.assertEqual(a.review_note, plan_module.SECTION_REVIEW_NOTE)
        self.assertEqual([g[2] for g in section_groups(self.plan)], [1, 2])

    def test_list_restart_is_reported_but_not_after_a_section(self):
        restarted = [n.original_line for n in self.plan.nodes if n.list_restarted]
        self.assertEqual(restarted, ["Direct two - Zeta [(2014) 5 SCC 5]"])

    def test_expected_order_puts_other_subjects_after_main_ones(self):
        order = self.plan.expected_order
        refs = {n.original_line: n.ref for n in self.plan.nodes}
        self.assertLess(order.index(refs["Procedure"]), order.index(refs["Stamp Act"]))

    def test_dry_run_report_shows_counts_and_reasons(self):
        text = dry_run_report(self.plan, "small.docx", "abc123", 10, "now")
        self.assertIn("DRY RUN", text)
        self.assertIn("Review-marked records", text)
        self.assertIn('no " - " separator', text)
        self.assertIn("'Scope:' -> 'Scope'", text)
        self.assertIn("Ex Parte", text)
        self.assertNotIn("PROBLEMS", text)


class StructureProblemTests(unittest.TestCase):
    def test_line_directly_under_miscellaneous_stops_the_import(self):
        plan = small_plan([("subject", "Miscellaneous"), ("subtopic", "Orphan")])
        self.assertEqual(len(plan.problems), 1)
        self.assertIn("directly under 'Miscellaneous'", plan.problems[0])
        self.assertIn("PROBLEMS", dry_run_report(plan, "x", "y", 1, "now"))

    def test_line_before_any_topic_of_a_main_subject_stops_the_import(self):
        plan = small_plan([("subject", "Contracts"), ("item", "Stray - X [(2010) 1 SCC 1]")])
        self.assertEqual(len(plan.problems), 1)

    def test_bullets_are_not_guessed(self):
        plan = small_plan([("subject", "Contracts"), ("topic", "T"), ("bullet", "A bullet")])
        self.assertIn("unrecognised line", plan.problems[0])

    def test_duplicate_subject_names_stop_the_import(self):
        plan = small_plan([("subject", "Contracts"), ("topic", "T"), ("subject", "contracts"), ("topic", "U")])
        self.assertTrue(any("must be unique" in p for p in plan.problems))

    def test_not_a_word_file(self):
        with self.assertRaises(DocxError):
            read_docx(b"this is not a zip file")


@unittest.skipUnless(REAL_FILE.exists(), "Case Law Diary.docx is not in the project folder")
class RealFileTests(unittest.TestCase):
    """The figures the owner approved in docs/IMPORT_ANALYSIS.md."""

    @classmethod
    def setUpClass(cls):
        paragraphs, notes = read_docx(REAL_FILE.read_bytes())
        cls.plan = build_plan(paragraphs, notes)

    def test_counts_match_the_analysis(self):
        self.assertEqual(self.plan.problems, [])
        self.assertEqual(summary_counts(self.plan), EXPECTED)

    def test_only_the_two_sections_and_the_flagged_items_are_review_marked(self):
        marked = [n for n in self.plan.nodes if n.needs_review]
        self.assertEqual(len(marked), 259)
        self.assertEqual(sum(1 for n in marked if n.kind == "section"), 2)

    def test_sections_hold_two_and_ten_items(self):
        self.assertEqual([g[2] for g in section_groups(self.plan)], [2, 10])

    def test_every_item_line_can_be_rebuilt_exactly(self):
        for node in self.plan.of("item"):
            text = node.text_html.replace("<p>", "").replace("</p>", "")
            for tag in ("b", "i", "u"):
                text = text.replace(f"<{tag}>", "").replace(f"</{tag}>", "")
            text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            rebuilt = text + (f" - {node.citation}" if node.citation else "")
            self.assertEqual(rebuilt, node.original_line, node.ref)
