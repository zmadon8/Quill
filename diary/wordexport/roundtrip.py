"""Round-trip check (Milestone 6): the exported Word file against the original Word file. Pure Python, no Django.

Both files are read with the project's own reader (``diary.importer.docx_reader``) and the original is
classified by the importer's own plan (``diary.importer.plan.build_plan``), so the check uses the same rules the
import used. Every Item and Section line of the original must appear in the export, in the same Subject, Topic
and Sub-topic and in the same order, exactly once, with its citation in italics at the end of the line.

Deliberate differences (listed, not counted as problems): headings are alphabetical; numbers are literal text in
the chosen formats (the original has Word's automatic numbers); trailing colons are gone from names (import
decision I8); Sections are numbered; "Miscellaneous" is "Other Subjects"; a citation is in italics after " - ".
"""
import difflib
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from ..importer.docx_reader import read_docx
from ..importer.plan import ITEM, SECTION, SUBJECT, SUBTOPIC, TOPIC, build_plan
from .render import OTHER_SUBJECTS, S_CASE_LINE, S_H1, S_H2, S_H3, S_ITEM, S_SECTION, S_SUBTOPIC

BLANK = ""


@dataclass
class Line:
    kind: str  # "item" or "section"
    text: str
    paragraph: object = None  # the export's Paragraph (None for the original)
    citation: str = ""  # the original's citation, if its line was split
    ref: str = ""  # the original's "para-0123"


@dataclass
class Side:
    """One file seen as headings (in order) and the lines under each heading."""

    headings: dict = field(default_factory=lambda: defaultdict(list))  # parent key -> [(level, name)] in file order
    containers: dict = field(default_factory=dict)  # container id -> [Line]
    order: list = field(default_factory=list)  # container ids in file order


@dataclass
class RoundTrip:
    text: str = ""
    unexpected: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def ok(self):
        return not self.unexpected


def strip_label(text):
    """The text after the number and its tab ('(1)\\tTitle' -> 'Title'); a line without a tab is returned whole."""
    return text.split("\t", 1)[1] if "\t" in text else text


class _Builder:
    """Adds headings and lines to a Side, giving every heading a container id (path plus how many times that path came before)."""

    def __init__(self):
        self.side = Side()
        self.seen = Counter()
        self.current = None

    def open(self, subject, topic=BLANK, subtopic=BLANK):
        path = (subject, topic, subtopic)
        self.seen[path] += 1
        self.current = (path, self.seen[path])
        self.side.containers[self.current] = []
        self.side.order.append(self.current)
        if subtopic:
            self.side.headings[(subject, topic)].append((SUBTOPIC, subtopic))
        elif topic:
            self.side.headings[(subject,)].append((TOPIC, topic))
        return self.current

    def add(self, line):
        self.side.containers[self.current].append(line)


def read_original(data):
    """Plan nodes of the original file as a Side, plus the plan."""
    paragraphs, notes = read_docx(data)
    plan = build_plan(paragraphs, notes)
    builder = _Builder()
    subject = topic = subtopic = BLANK
    subjects = []
    for node in plan.nodes:
        if node.kind == SUBJECT:
            subject, topic, subtopic = node.name, BLANK, BLANK
            subjects.append((node.other_subject, node.name))
            builder.open(subject)
        elif node.kind == TOPIC:
            topic, subtopic = node.name, BLANK
            builder.open(subject, topic)
        elif node.kind == SUBTOPIC:
            subtopic = node.name
            builder.open(subject, topic, subtopic)
        elif node.kind == SECTION:
            builder.add(Line("section", node.original_line, ref=node.ref))
        elif node.kind == ITEM:
            builder.add(Line("item", node.original_line, citation=node.citation, ref=node.ref))
    builder.side.headings[()] = [(SUBJECT, name) for other, name in subjects if not other]
    builder.side.headings[("other",)] = [(SUBJECT, name) for other, name in subjects if other]
    return builder.side, plan


def read_export(data):
    """The export's paragraphs as a Side (by paragraph style; the front page and contents list are skipped)."""
    paragraphs, _notes = read_docx(data)
    builder = _Builder()
    subject = topic = BLANK
    in_other = False
    main, other = [], []
    for para in paragraphs:
        style, text = para.style, para.text
        if style == S_H1:
            topic = BLANK
            if text == OTHER_SUBJECTS and not main_has(main, text):
                in_other, subject = True, BLANK
                continue
            in_other, subject = False, text
            main.append((SUBJECT, text))
            builder.open(subject)
        elif style == S_H2:
            if in_other:
                subject, topic = text, BLANK
                other.append((SUBJECT, text))
                builder.open(subject)
            else:
                topic = strip_label(text)
                builder.open(subject, topic)
        elif style == S_H3:
            topic = strip_label(text)
            builder.open(subject, topic)
        elif style == S_SUBTOPIC:
            builder.open(subject, topic, strip_label(text))
        elif style == S_SECTION:
            builder.add(Line("section", strip_label(text), para))
        elif style == S_ITEM:
            builder.add(Line("item", strip_label(text), para))
        elif style == S_CASE_LINE:
            continue  # a citation on its own line (layout "On separate lines"): the original file has none
    builder.side.headings[()] = main
    builder.side.headings[("other",)] = other
    return builder.side


def main_has(main, text):
    return any(name == text for _kind, name in main)


def citation_in_italics(paragraph, citation):
    """True if the paragraph ends with ' - ' + citation and every character of the citation is italic."""
    text = paragraph.text
    tail = " - " + citation
    if not text.endswith(tail):
        return False
    start = len(text) - len(citation)
    pos = 0
    for run in paragraph.runs:
        lo, hi = pos, pos + len(run.text)
        pos = hi
        if hi > start and lo < len(text) and run.text and not run.italic:
            return False
    return True


def _sequence(lines):
    return [(line.kind, line.text) for line in lines]


def _describe(path, occurrence):
    subject, topic, subtopic = path
    where = " > ".join(x for x in (subject, topic, subtopic) if x) or "(top)"
    return where + (f" [#{occurrence}]" if occurrence > 1 else "")


def compare(original, export, plan):
    """Compare two Sides. Returns a RoundTrip (report text, the list of unexpected differences, figures)."""
    unexpected = []
    stats = {}

    # 1. Headings: the same headings must exist; only their order may differ.
    gone = [c for c in original.order if c not in export.containers]
    extra = [c for c in export.order if c not in original.containers]
    for c in gone:
        unexpected.append(f"Heading missing from the export: {_describe(*c)}")
    for c in extra:
        unexpected.append(f"Heading in the export that is not in the original: {_describe(*c)}")

    # 2. Lines under each heading: same lines, same order (Sections are lines too).
    items_original = items_export = sections_original = sections_export = 0
    citations_checked = citations_italic = 0
    for cid in original.order:
        want = original.containers[cid]
        have = export.containers.get(cid)
        items_original += sum(1 for ln in want if ln.kind == "item")
        sections_original += sum(1 for ln in want if ln.kind == "section")
        if have is None:
            continue
        items_export += sum(1 for ln in have if ln.kind == "item")
        sections_export += sum(1 for ln in have if ln.kind == "section")
        a, b = _sequence(want), _sequence(have)
        if a == b:
            for w, h in zip(want, have):
                if w.kind == "item" and w.citation:
                    citations_checked += 1
                    if citation_in_italics(h.paragraph, w.citation):
                        citations_italic += 1
                    else:
                        unexpected.append(f"{w.ref}: the citation is not in italics at the end of the line: {w.text[:100]!r}")
            continue
        where = _describe(*cid)
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag == "equal":
                continue
            for kind, text in a[i1:i2]:
                unexpected.append(f"{where}: {kind} in the original but not in the export: {text[:120]!r}")
            for kind, text in b[j1:j2]:
                unexpected.append(f"{where}: {kind} in the export but not in the original: {text[:120]!r}")
    for cid in extra:
        items_export += sum(1 for ln in export.containers[cid] if ln.kind == "item")

    # 3. The whole file: every line exactly as many times as in the original.
    count_o = Counter(_sequence([ln for c in original.order for ln in original.containers[c]]))
    count_e = Counter(_sequence([ln for c in export.order for ln in export.containers[c]]))
    for line, n in (count_o - count_e).items():
        unexpected.append(f"Appears {count_o[line]} time(s) in the original but {count_e[line]} in the export: {line[1][:120]!r}")
    for line, n in (count_e - count_o).items():
        unexpected.append(f"Appears {count_e[line]} time(s) in the export but {count_o[line]} in the original: {line[1][:120]!r}")
    unexpected = list(dict.fromkeys(unexpected))  # the same message once

    # 4. Deliberate differences, listed.
    reordered = {SUBJECT: 0, TOPIC: 0, SUBTOPIC: 0}
    for key, wanted in original.headings.items():
        got = export.headings.get(key, [])
        if wanted != got and Counter(wanted) == Counter(got):
            kind = wanted[0][0]
            reordered[kind] += 1
    colons = [n for n in plan.nodes if n.colon_removed]
    stats.update(
        items_original=items_original, items_export=items_export, sections_original=sections_original,
        sections_export=sections_export, headings=len(original.order), citations_checked=citations_checked,
        citations_italic=citations_italic, reordered=reordered, colons=len(colons),
    )
    lines = [
        "Round-trip check: the Word export against the original Word file",
        "=" * 64,
        f"Headings in the original (Subjects, Topics, Sub-topics): {len(original.order)}; in the export: {len(export.order)}",
        f"Item lines: {items_original} in the original, {items_export} in the export",
        f"Section lines: {sections_original} in the original, {sections_export} in the export",
        f"Citations checked (in italics, at the end of the line): {citations_italic} of {citations_checked}",
        "",
        "Deliberate differences (expected, not problems):",
        f"  - Alphabetical order (lists whose order changed): "
        f"{reordered[SUBJECT]} Subject list(s), {reordered[TOPIC]} Topic list(s), {reordered[SUBTOPIC]} Sub-topic list(s)",
        "  - Numbers are literal text in the chosen formats; the original has Word's automatic numbers",
        f"  - Trailing colons removed from {len(colons)} Subject, Topic and Sub-topic names (import decision I8)",
        f"  - Sections are numbered ({sections_export} Section line(s))",
        "  - 'Miscellaneous' is 'Other Subjects'; its Subjects are Heading 2",
        "  - A single citation is written in italics after ' - '; several would be labelled (a), (b)",
        "",
    ]
    if unexpected:
        lines.append(f"UNEXPECTED differences: {len(unexpected)}")
        lines.extend(f"  * {u}" for u in unexpected[:200])
        if len(unexpected) > 200:
            lines.append(f"  ... and {len(unexpected) - 200} more")
        lines.append("")
        lines.append("RESULT: FAIL")
    else:
        lines.append("UNEXPECTED differences: 0")
        lines.append("Every Item and Section line of the original appears exactly once in the export, under the same "
                     "Subject, Topic and Sub-topic, in the same order.")
        lines.append("")
        lines.append("RESULT: PASS")
    return RoundTrip("\n".join(lines) + "\n", unexpected, stats)


def check(original_bytes, export_bytes):
    """Read both files and compare. Returns a RoundTrip."""
    original, plan = read_original(original_bytes)
    return compare(original, read_export(export_bytes), plan)
