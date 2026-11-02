"""Word export tests that need no database: the writer, the renderer, file names and the round-trip check."""
import io
import time
import unittest
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from diary.importer.docx_reader import read_docx
from diary.importer.plan import build_plan
from diary.tests.docx_builder import SMALL, make_docx
from diary.tests.wordexport_support import DEFAULT_FMTS, tree_from_plan
from diary.wordexport import docxwriter as dw
from diary.wordexport import model as m
from diary.wordexport import naming, render, roundtrip

REAL_FILE = Path(__file__).resolve().parents[2] / "Case Law Diary.docx"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def paragraphs_of(data):
    return read_docx(data)[0]


def lines_of(data, style=None):
    return [p.text for p in paragraphs_of(data) if style is None or p.style == style]


def item(text, *citations, **kw):
    return m.XItem(html=f"<p>{text}</p>", cases=[m.XCase(c) for c in citations], **kw)


def sample_subject():
    """A Subject with a Section, restarting Items, an Item with citations on separate lines, flags, notes and two citations."""
    container = m.XContainer(
        entries=[
            item("Direct one", "(2020) 1 SCC 1"),
            m.XSection("Ex Parte", needs_review=True, review_note="check me"),
            item("After the Section one", "(2021) 2 SCC 2", flag_label="Overruled"),
            m.XItem(html="<p>Two cites</p>", cases=[m.XCase("(2019) 1 SCC 1", "<p>on <b>facts</b></p>"), m.XCase("(2018) 2 SCC 2")]),
            m.XSection("Determining"),
            item("Restarted", "(2022) 3 SCC 3", needs_review=True, review_note="odd"),
            m.XItem(html="<p>Lines <u>head</u></p>", layout="lines",
                    cases=[m.XCase("(2017) 4 SCC 4", "<p>First <u>point</u></p>"), m.XCase("(2016) 5 SCC 5"),
                           m.XCase("", "<p>comment only</p>")],
                    notes=[m.XNote("<p>an item note</p>", [m.XLink("Law > Tort > Duty")])]),
        ],
        notes=[m.XNote("<p>Subject note</p>", [m.XLink("Law > Gone", deleted=True)])],
    )
    sub = m.XSubtopic("Fraud", 1, m.XContainer([item("<i>Italic</i> start and <b>bold</b>", "(2010) 1 SCC 1")]))
    topic = m.XTopic("Arbitrability", 1, m.XContainer([item("Topic item")]), [sub])
    return m.XSubject("Arbitration", container, [topic, m.XTopic("Zeta", 2)])


def make(**kw):
    base = dict(title="Case Law Diary Main", part="Full", date_text="2026-11-01", fmts=dict(DEFAULT_FMTS),
                main=[sample_subject()])
    base.update(kw)
    return m.ExportInput(**base)


class WriterTests(unittest.TestCase):
    def test_package_is_a_valid_zip_and_every_part_is_well_formed_xml(self):
        doc = dw.Document("T")
        doc.new_section("One")
        doc.add(dw.Para("Heading1", [dw.Run("A & B <c>")], bookmark="b1"))
        doc.new_section("Two")
        doc.add(dw.Para("Normal", [dw.Run("link", anchor="b1")]))
        data = doc.to_bytes()
        archive = zipfile.ZipFile(io.BytesIO(data))
        self.assertIsNone(archive.testzip())
        for name in archive.namelist():
            ET.fromstring(archive.read(name))
        for part in ("[Content_Types].xml", "_rels/.rels", "word/document.xml", "word/styles.xml",
                     "word/header1.xml", "word/header2.xml", "word/footer1.xml"):
            self.assertIn(part, archive.namelist())
        self.assertIn("One", archive.read("word/header1.xml").decode())
        self.assertIn("Two", archive.read("word/header2.xml").decode())

    def test_each_section_has_its_own_header_and_a_page_break(self):
        doc = dw.Document()
        for name in ("A", "B", "C"):
            doc.new_section(name)
            doc.add(dw.Para("Normal", [dw.Run(name)]))
        root = ET.fromstring(zipfile.ZipFile(io.BytesIO(doc.to_bytes())).read("word/document.xml"))
        refs = [r.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                for r in root.iter(W + "headerReference")]
        self.assertEqual(refs, ["rIdHeader1", "rIdHeader2", "rIdHeader3"])
        # Two section breaks sit in paragraphs, the last section's properties close the body.
        self.assertEqual(len(list(root.iter(W + "sectPr"))), 3)
        self.assertEqual(len(list(root.find(W + "body").findall(W + "sectPr"))), 1)

    def test_text_round_trips_through_the_project_reader_including_tabs_and_line_breaks(self):
        doc = dw.Document()
        doc.add(dw.Para("Normal", [dw.Run("(1)"), dw.Run(tab=True), dw.Run("a\tb\nc  d "), dw.Run("x\x01y", italic=True)]))
        paragraph = paragraphs_of(doc.to_bytes())[0]
        self.assertEqual(paragraph.text, "(1)\ta\tb\nc  d xy")
        self.assertTrue(paragraph.runs[-1].italic)

    def test_same_input_gives_the_same_bytes(self):
        self.assertEqual(render.render(make()), render.render(make()))


class RenderStructureTests(unittest.TestCase):
    def setUp(self):
        self.data = render.render(make())
        self.paras = paragraphs_of(self.data)

    def texts(self, style):
        return [p.text for p in self.paras if p.style == style]

    def test_headings_and_levels(self):
        self.assertEqual(self.texts("Heading1"), ["Arbitration"])
        self.assertEqual(self.texts("Heading2"), ["A\tArbitrability", "B\tZeta"])
        self.assertEqual(self.texts("DiarySubtopic"), ["1\tFraud"])

    def test_numbers_are_literal_text_with_no_full_stop_and_items_restart_after_each_section(self):
        items = self.texts("DiaryItem")
        sections = self.texts("DiarySection")
        self.assertEqual(sections, ["(a)\tEx Parte", "(b)\tDetermining"])
        # Direct Items, then the first Section's run, then the second's: the second run restarts at (1).
        self.assertIn("(1)\tDirect one - (2020) 1 SCC 1", items)
        self.assertIn("(1)\tAfter the Section one - (2021) 2 SCC 2 [Overruled]", items)
        self.assertIn("(1)\tRestarted - (2022) 3 SCC 3", items)
        self.assertIn("(2)\tLines head", items)
        self.assertFalse(any(t.split("\t")[0].endswith(".") for t in items + sections))
        numbering_part = zipfile.ZipFile(io.BytesIO(self.data)).namelist()
        self.assertNotIn("word/numbering.xml", numbering_part)  # no Word auto-numbering anywhere

    def test_citations_are_italic_after_a_dash_and_several_are_labelled(self):
        two = next(p for p in self.paras if p.text.startswith("(2)\tTwo cites"))
        self.assertEqual(two.text, "(2)\tTwo cites - (a) (2019) 1 SCC 1 on facts ; (b) (2018) 2 SCC 2")
        italic = "".join(r.text for r in two.runs if r.italic)
        self.assertEqual(italic, "(2019) 1 SCC 1(2018) 2 SCC 2")
        self.assertTrue(any(r.bold and r.text == "facts" for r in two.runs))  # the comment keeps its bold

    def test_rich_text_b_i_u_is_kept(self):
        fraud = next(p for p in self.paras if "start and" in p.text)
        self.assertEqual([(r.text, r.italic, r.bold) for r in fraud.runs if r.text in ("Italic", "bold")],
                         [("Italic", True, False), ("bold", False, True)])
        lines = next(p for p in self.paras if "Lines" in p.text)
        self.assertTrue(any(r.underline and r.text == "head" for r in lines.runs))

    def test_citations_on_separate_lines_are_literal_a_b_c_with_the_comment_first(self):
        self.assertEqual(self.texts("DiaryBullet"),
                         ["(a)\tFirst point - (2017) 4 SCC 4", "(b)\t(2016) 5 SCC 5", "(c)\tcomment only"])
        first = next(p for p in self.paras if p.text.startswith("(a)\tFirst point"))
        self.assertEqual("".join(r.text for r in first.runs if r.italic), "(2017) 4 SCC 4")
        self.assertTrue(any(r.underline and r.text == "point" for r in first.runs))

    def test_sections_are_bold(self):
        section = next(p for p in self.paras if p.style == "DiarySection")
        self.assertTrue(all(r.bold for r in section.runs if r.text != "\t"))

    def test_notes_print_see_also_and_never_linked_from(self):
        text = "\n".join(p.text for p in self.paras)
        self.assertIn("See also: Law > Tort > Duty", text)
        self.assertIn("See also: Law > Gone (target deleted)", text)
        self.assertNotIn("Linked from", text)
        self.assertEqual(self.texts("DiaryNote"), ["an item note", "Subject note"])

    def test_items_precede_child_headings_and_notes_follow_items(self):
        order = [p.style for p in self.paras if p.style.startswith(("Heading", "Diary"))]
        first_heading2 = order.index("Heading2")
        self.assertLess(order.index("DiaryItem"), first_heading2)
        self.assertLess(order.index("DiaryNote"), first_heading2)  # the Subject's own Notes come before its Topics

    def test_flag_is_red_and_review_markers_are_off_by_default(self):
        document = zipfile.ZipFile(io.BytesIO(self.data)).read("word/document.xml").decode()
        self.assertIn(f'<w:color w:val="{dw.RED}"/>', document)
        self.assertNotIn("For review", document.split("Contents")[1])  # the front page says "not included"
        self.assertNotIn("[For review", document)

    def test_review_markers_appear_on_items_and_sections_when_asked(self):
        paras = paragraphs_of(render.render(make(include_review=True)))
        self.assertTrue(any(p.style == "DiarySection" and p.text.endswith("Ex Parte [For review: check me]") for p in paras))
        self.assertTrue(any(p.style == "DiaryItem" and p.text.endswith("[For review: odd]") for p in paras))
        self.assertEqual(sum("[For review" in p.text for p in paras), 2)

    def test_hanging_indents_hold_the_number_in_the_margin(self):
        root = ET.fromstring(zipfile.ZipFile(io.BytesIO(self.data)).read("word/document.xml"))
        item_ind = None
        for p in root.iter(W + "p"):
            style = p.find(f"{W}pPr/{W}pStyle")
            if style is not None and style.get(W + "val") == "DiaryItem":
                item_ind = p.find(f"{W}pPr/{W}ind")
                break
        self.assertEqual(item_ind.get(W + "hanging"), str(render.W))
        self.assertEqual(item_ind.get(W + "left"), str(render.W))

    def test_front_page_has_title_date_count_and_a_contents_list_of_links(self):
        front = [p.text for p in self.paras[:10]]
        self.assertEqual(front[0], "Case Law Diary Main")
        self.assertIn("Exported 2026-11-01. Records in this document: 7 Items.", front)
        root = ET.fromstring(zipfile.ZipFile(io.BytesIO(self.data)).read("word/document.xml"))
        anchors = [h.get(W + "anchor") for h in root.iter(W + "hyperlink")]
        names = {b.get(W + "name") for b in root.iter(W + "bookmarkStart")}
        self.assertTrue(anchors and set(anchors) <= names)

    def test_subject_has_its_own_page_header(self):
        archive = zipfile.ZipFile(io.BytesIO(self.data))
        headers = [archive.read(n).decode() for n in sorted(archive.namelist()) if n.startswith("word/header")]
        self.assertIn("Case Law Diary Main", headers[0])
        self.assertIn("Arbitration", headers[1])

    def test_chosen_number_formats_are_used(self):
        fmts = dict(DEFAULT_FMTS, topic_format="I", subtopic_format="(a)", section_format="Section 1", item_format="a")
        paras = paragraphs_of(render.render(make(fmts=fmts)))
        texts = [p.text for p in paras]
        self.assertIn("I\tArbitrability", texts)
        self.assertIn("(a)\tFraud", texts)
        self.assertIn("Section 1\tEx Parte", texts)
        self.assertIn("a\tAfter the Section one - (2021) 2 SCC 2 [Overruled]", texts)

    def test_empty_item_format_keeps_the_tab_so_the_text_is_still_found(self):
        paras = paragraphs_of(render.render(make(fmts=dict(DEFAULT_FMTS, item_format="none"))))
        self.assertIn("\tDirect one - (2020) 1 SCC 1", [p.text for p in paras])


class GroupingTests(unittest.TestCase):
    def others(self):
        return [m.XSubject("Stamp Act", m.XContainer([item("one")]), subtopics=[m.XSubtopic("Duty", 1, m.XContainer([item("two")]))]),
                m.XSubject("Tender", m.XContainer([item("three")]))]

    def test_full_document_groups_other_subjects_under_one_heading_one(self):
        paras = paragraphs_of(render.render(make(main=[sample_subject()], others=self.others())))
        styles = [(p.style, p.text) for p in paras if p.style in ("Heading1", "Heading2", "DiarySubtopic")]
        self.assertEqual(styles, [("Heading1", "Arbitration"), ("Heading2", "A\tArbitrability"), ("DiarySubtopic", "1\tFraud"),
                                  ("Heading2", "B\tZeta"), ("Heading1", "Other Subjects"), ("Heading2", "Stamp Act"), ("DiarySubtopic", "1\tDuty"),
                                  ("Heading2", "Tender")])

    def test_other_subjects_document_lists_its_subjects_and_pages(self):
        data = render.render(make(part="Other Subjects", main=[], others=self.others()))
        archive = zipfile.ZipFile(io.BytesIO(data))
        headers = [archive.read(n).decode() for n in sorted(archive.namelist(), key=lambda n: (len(n), n)) if n.startswith("word/header")]
        self.assertEqual(len(headers), 4)  # front page, the group page, one page per Other Subject
        self.assertIn("Other Subjects: Stamp Act", headers[2])

    def test_a_single_other_subject_is_heading_one_alone(self):
        paras = paragraphs_of(render.render(make(main=[self.others()[0]], path=["Stamp Act"], part="Stamp Act")))
        self.assertEqual([p.text for p in paras if p.style.startswith("Heading")], ["Stamp Act"])
        self.assertEqual([p.style for p in paras if p.style.startswith("Heading")], ["Heading1"])

    def test_current_view_of_a_topic_keeps_its_letter_and_number(self):
        topic = m.XTopic("Arbitrability", 3, m.XContainer([item("Topic item")]),
                         [m.XSubtopic("Fraud", 1, m.XContainer([item("x")]))])
        paras = paragraphs_of(render.render(make(main=[], view_topic=topic, path=["Arbitration", "Arbitrability"])))
        self.assertEqual([(p.style, p.text) for p in paras if p.style.startswith("Heading")], [("Heading1", "C\tArbitrability")])
        self.assertIn("1\tFraud", [p.text for p in paras])  # the Sub-topics of the Topic are numbered 1, 2, ... as on screen
        self.assertTrue(any("On screen: Arbitration > Arbitrability" in p.text for p in paras))

    def test_current_view_of_a_subtopic_is_heading_one_with_its_number(self):
        sub = m.XSubtopic("Fraud", 4, m.XContainer([item("x", "(2020) 1 SCC 1")]))
        paras = paragraphs_of(render.render(make(main=[], view_subtopic=sub, path=["A", "B", "Fraud"])))
        self.assertEqual([(p.style, p.text) for p in paras if p.style.startswith("Heading")], [("Heading1", "4\tFraud")])
        self.assertIn("(1)\tx - (2020) 1 SCC 1", [p.text for p in paras])

    def test_count_items_counts_items_and_not_sections(self):
        self.assertEqual(m.count_items(sample_subject()), 7)


class NamingTests(unittest.TestCase):
    def test_illegal_characters_become_hyphens_and_spaces_tidy(self):
        self.assertEqual(naming.clean_part(' Madon: "Case"/Law?  *|<> '), "Madon- -Case--Law- ----")
        self.assertEqual(naming.clean_part("..a\x01b.."), "a-b")
        self.assertEqual(naming.replacements('a:b:c?'), ["':' was replaced with '-'", "'?' was replaced with '-'"])
        self.assertEqual(naming.replacements("fine"), [])

    def test_names_follow_the_pattern(self):
        self.assertEqual(naming.build_name("Case Law Diary Main", ["Full"], "2026-11-01", "docx"),
                         "Case Law Diary Main Full 2026-11-01.docx")
        self.assertEqual(naming.build_name("Case Law Diary Main", ["Full - by Subject"], "2026-11-01", "zip"),
                         "Case Law Diary Main Full - by Subject 2026-11-01.zip")
        self.assertEqual(naming.build_name("CLD", ["Arbitration", "Fraud"], "2026-11-01", "docx"),
                         "CLD Arbitration, Fraud 2026-11-01.docx")

    def test_date_formats(self):
        d = date(2026, 11, 1)
        self.assertEqual(naming.format_date(d, "YYYY-MM-DD"), "2026-11-01")
        self.assertEqual(naming.format_date(d, "DD-MM-YYYY"), "01-11-2026")
        self.assertEqual(naming.format_date(d, "D Month YYYY"), "1 November 2026")
        self.assertEqual(naming.format_date(d, "junk"), "2026-11-01")

    def test_the_date_is_the_date_in_india(self):
        late_utc = datetime(2026, 11, 1, 20, 0, tzinfo=timezone.utc)  # 01:30 on 2 November in India
        self.assertEqual(naming.today(late_utc, "Asia/Kolkata"), date(2026, 11, 2))
        self.assertEqual(naming.today(late_utc, "No/Such_Zone"), date(2026, 11, 2))  # unknown zone: IST

    def test_long_current_view_names_are_shortened_by_the_documented_rule(self):
        long_names = ["Arbitration and Conciliation Act 1996 Section 34", "Setting aside of arbitral awards generally",
                      "Patent illegality as a ground of challenge"]
        name = naming.build_name("Case Law Diary Main", long_names, "2026-11-01", "docx")
        stem = name[:-5]
        self.assertLessEqual(len(stem), 120)
        self.assertIn("Arbitration and Conciliation, Setting aside of arbitral, Patent illegality as a ground 2026", name)
        # Still too long after cutting each segment to 30, so the middle one is dropped for a single '-'.
        many = ["x" * 40, "y" * 40, "z" * 40, "w" * 40]
        short = naming.build_name("Case Law Diary Main", many, "2026-11-01", "docx")
        self.assertIn("x" * 30 + ", -, " + "w" * 30, short)
        self.assertNotIn("yyyy", short)

    def test_a_short_name_is_left_alone(self):
        self.assertEqual(naming.shorten(["Arbitration", "Fraud"], "CLD", "2026-11-01"), ["Arbitration", "Fraud"])

    def test_word_boundary_cut(self):
        cut = naming._cut("Setting aside of arbitral awards generally speaking")
        self.assertEqual(cut, "Setting aside of arbitral")  # the last space after the 15th character within 30

    def test_duplicates_in_one_zip_get_a_counter_before_the_date(self):
        taken = set()
        first = naming.build_name("CLD", ["Tort"], "2026-11-01", "docx", taken)
        second = naming.build_name("CLD", ["tort"], "2026-11-01", "docx", taken)
        third = naming.build_name("CLD", ["Tort"], "2026-11-01", "docx", taken)
        self.assertEqual((first, second, third),
                         ("CLD Tort 2026-11-01.docx", "CLD tort (2) 2026-11-01.docx", "CLD Tort (3) 2026-11-01.docx"))


class RoundTripTests(unittest.TestCase):
    def export(self, plan, **kw):
        main, other = tree_from_plan(plan)
        return render.render(make(main=main, others=other, **kw))

    def small(self):
        data = make_docx(SMALL)
        paragraphs, notes = read_docx(data)
        return data, build_plan(paragraphs, notes)

    @staticmethod
    def reference(main):
        """The Sub-topic 'Reference' of the small file (Arbitration > Scope)."""
        topic = next(t for t in main[0].topics if t.name == "Scope")
        return next(s for s in topic.subtopics if s.name == "Reference")

    def test_a_small_file_round_trips_with_no_unexpected_difference(self):
        data, plan = self.small()
        result = roundtrip.check(data, self.export(plan))
        self.assertTrue(result.ok, result.text)
        self.assertIn("RESULT: PASS", result.text)
        self.assertEqual(result.stats["items_original"], result.stats["items_export"])
        self.assertEqual(result.stats["sections_export"], 2)

    def test_a_missing_item_is_reported(self):
        data, plan = self.small()
        main, other = tree_from_plan(plan)
        self.reference(main).container.entries.pop(0)
        result = roundtrip.check(data, render.render(make(main=main, others=other)))
        self.assertFalse(result.ok)
        self.assertTrue(any("Clean proposition" in u for u in result.unexpected), result.text)
        self.assertIn("RESULT: FAIL", result.text)

    def test_a_duplicated_item_is_reported(self):
        data, plan = self.small()
        main, other = tree_from_plan(plan)
        entries = self.reference(main).container.entries
        entries.append(entries[0])
        result = roundtrip.check(data, render.render(make(main=main, others=other)))
        self.assertFalse(result.ok)

    def test_a_changed_word_is_reported(self):
        data, plan = self.small()
        main, other = tree_from_plan(plan)
        entry = self.reference(main).container.entries[0]
        entry.html = entry.html.replace("Clean", "Clear")
        self.assertFalse(roundtrip.check(data, render.render(make(main=main, others=other))).ok)

    def test_an_item_moved_to_the_wrong_heading_is_reported(self):
        data, plan = self.small()
        main, other = tree_from_plan(plan)
        entries = self.reference(main).container.entries
        main[0].topics[0].container.entries.append(entries.pop(0))
        self.assertFalse(roundtrip.check(data, render.render(make(main=main, others=other))).ok)

    def test_a_citation_that_lost_its_italics_is_reported(self):
        data, plan = self.small()
        main, other = tree_from_plan(plan)
        export = self.export(plan)
        archive = zipfile.ZipFile(io.BytesIO(export))
        document = archive.read("word/document.xml").decode().replace("<w:i/>", "")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as out:
            for name in archive.namelist():
                out.writestr(name, document if name == "word/document.xml" else archive.read(name))
        result = roundtrip.check(data, buffer.getvalue())
        self.assertFalse(result.ok)
        self.assertTrue(any("italics" in u for u in result.unexpected))

    def test_a_section_in_the_wrong_place_is_reported(self):
        data, plan = self.small()
        main, other = tree_from_plan(plan)
        subject = next(s for s in main if s.name == "Procedure")
        entries = subject.topics[0].subtopics[0].container.entries
        entries.insert(0, entries.pop(1))  # the second Section jumps above the first
        self.assertFalse(roundtrip.check(data, render.render(make(main=main, others=other))).ok)

    @unittest.skipUnless(REAL_FILE.exists(), "Case Law Diary.docx is not in the project folder")
    def test_the_real_file_round_trips_with_zero_unexpected_differences(self):
        data = REAL_FILE.read_bytes()
        paragraphs, notes = read_docx(data)
        plan = build_plan(paragraphs, notes)
        result = roundtrip.check(data, self.export(plan))
        self.assertEqual(result.unexpected, [], result.text)
        self.assertEqual(result.stats["items_export"], 950)
        self.assertEqual(result.stats["citations_checked"], 693)
        self.assertEqual(result.stats["citations_italic"], 693)
        self.assertEqual(result.stats["colons"], 19)


class PerformanceTests(unittest.TestCase):
    def test_five_thousand_items_render_in_seconds(self):
        topics = []
        for t in range(50):
            subs = [m.XSubtopic(f"Sub {s}", s + 1, m.XContainer([item(f"Item {t}-{s}-{i} with some text " * 3, f"(20{i % 25:02d}) {i} SCC {s}")
                                                                  for i in range(20)])) for s in range(5)]
            topics.append(m.XTopic(f"Topic {t}", t + 1, m.XContainer([]), subs))
        subjects = [m.XSubject(f"Subject {n}", m.XContainer([]), topics) for n in range(1)]
        data = make(main=subjects)
        self.assertEqual(m.count_items(data), 5000)
        started = time.monotonic()
        out = render.render(data)
        seconds = time.monotonic() - started
        print(f"\nrender of {m.count_items(data)} Items: {seconds:.2f} s, {len(out)} bytes")
        self.assertLess(seconds, 20)


if __name__ == "__main__":
    unittest.main()
