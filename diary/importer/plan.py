"""Turns the paragraphs of the Word file into a plan of records (pure Python, no database).

Rules come from docs/DESIGN.md section 8 and docs/IMPORT_ANALYSIS.md. Nothing is rewritten: the
only deliberate change to wording is the removal of a trailing colon from Topic, Sub-topic and
Subject names (decision I8), and every such change is reported.
"""
import re
from collections import Counter
from dataclasses import dataclass, field
from html import escape

SUBJECT = "subject"
TOPIC = "topic"
SUBTOPIC = "subtopic"
SECTION = "section"
ITEM = "item"

MISC_NAME = "miscellaneous"
SECTION_REVIEW_NOTE = "imported from a small-letter (a)/(b) list; confirm these are Sections"
MAX_CITATION = 1000
NAME_LIMITS = {SUBJECT: 300, TOPIC: 300, SUBTOPIC: 300, SECTION: 500}

#: Reasons an Item line is imported whole (key -> wording used in review notes and reports).
REASONS = {
    "spaces": "leading or trailing spaces",
    "unbalanced": "brackets do not match",
    "bracketed": "whole line is a bracketed remark",
    "multi_marker": "several citations marked (i), (ii)",
    "no_dash": 'no " - " separator',
    "many_dash": 'more than one " - "',
    "empty_side": 'nothing on one side of the " - "',
    "flag": "contains a flag",
    "not_citation": "right side does not look like a citation",
    "double_space": "double spaces",
    "long_citation": f"right side is longer than {MAX_CITATION} characters",
}

#: The figures in docs/IMPORT_ANALYSIS.md, shown next to the real counts (information, not a gate).
EXPECTED = {
    "subjects": 41,
    "main_subjects": 10,
    "other_subjects": 31,
    "topics": 178,
    "subtopics": 323,
    "sections": 2,
    "items": 950,
    "items_clean": 693,
    "items_flagged": 257,
    "review_marked": 259,
    "text_paragraphs": 1495,
    "blank_paragraphs": 11,
    "colon_changes": 19,
}


def strip_colon(name):
    """Decision I8: a trailing colon is not stored in a Topic, Sub-topic or Subject name."""
    if name.rstrip().endswith(":"):
        return name.rstrip()[:-1].rstrip()
    return name


def classify_item(text):
    """Decide how one Item line is stored. Returns (reason_key, left, right).

    ``reason_key`` is None for a clean split (left is Text, right is the Citation); otherwise the
    whole line is Text with no Citation and the key says why. The first matching reason wins.
    """
    if text != text.strip():
        return "spaces", text, ""
    if text.count("[") != text.count("]") or text.count("(") != text.count(")"):
        return "unbalanced", text, ""
    if text.startswith("[") and text.endswith("]"):
        return "bracketed", text, ""
    if "(ii)" in text:
        return "multi_marker", text, ""
    if " - " not in text:
        return "no_dash", text, ""
    if text.count(" - ") > 1:
        return "many_dash", text, ""
    left, right = text.split(" - ")
    if not left.strip() or not right.strip():
        return "empty_side", text, ""
    if "NO LONGER GOOD LAW" in text.upper():
        return "flag", text, ""
    if "[" not in right and not re.search(r"\d{4}\)? ?\d* ?[A-Za-z]", right):
        return "not_citation", text, ""
    if "  " in text:
        return "double_space", text, ""
    if len(right) > MAX_CITATION:
        return "long_citation", text, ""
    return None, left, right


def runs_to_html(runs, start=0, end=None):
    """HTML (p, b, i, u only) for characters ``start:end`` of the paragraph, keeping run formatting."""
    total = sum(len(r.text) for r in runs)
    end = total if end is None else end
    parts = []
    pos = 0
    for run in runs:
        lo, hi = max(start, pos), min(end, pos + len(run.text))
        pos += len(run.text)
        if lo >= hi:
            continue
        piece = escape(run.text[lo - (pos - len(run.text)): hi - (pos - len(run.text))], quote=False)
        key = (run.bold, run.italic, run.underline)
        if parts and parts[-1][0] == key:
            parts[-1][1] += piece
        else:
            parts.append([key, piece])
    out = ""
    for (bold, italic, underline), piece in parts:
        for flag, tag in ((underline, "u"), (italic, "i"), (bold, "b")):
            if flag:
                piece = f"<{tag}>{piece}</{tag}>"
        out += piece
    return f"<p>{out}</p>"


@dataclass
class Node:
    kind: str
    ref: str  # "para-0123": the 0-based paragraph number in the file
    original_line: str
    name: str = ""  # Subject, Topic, Sub-topic and Section
    text_html: str = ""  # Item
    citation: str = ""  # Item
    review_note: str = ""
    reason: str = ""  # reason key when flagged
    parent: "Node | None" = None
    position: int = 0
    # Subject only
    other_subject: bool = False
    landing_position: int = 0
    other_position: int = 0
    # facts for the reports
    formatted: bool = False  # item line with bold/italic/underline runs
    other_formatting: list = field(default_factory=list)
    list_restarted: bool = False
    block: int = 0  # index of the Heading 1 block the paragraph sits in
    para_index: int = 0
    _num_id: str = ""

    @property
    def needs_review(self):
        return bool(self.review_note)

    @property
    def colon_removed(self):
        return self.kind in (SUBJECT, TOPIC, SUBTOPIC) and self.name != self.original_line


@dataclass
class Plan:
    nodes: list = field(default_factory=list)  # in the order the records are created (document order)
    blank_paragraphs: list = field(default_factory=list)  # (paragraph index, text of the previous line)
    text_paragraphs: int = 0
    problems: list = field(default_factory=list)  # anything that stops the import
    warnings: list = field(default_factory=list)  # reported, do not stop
    file_notes: dict = field(default_factory=dict)
    expected_order: list = field(default_factory=list)  # refs in the order the database will list them
    skipped_headings: list = field(default_factory=list)  # (ref, text): "Miscellaneous" is not stored

    def of(self, kind):
        return [n for n in self.nodes if n.kind == kind]


def _level(para):
    """What a paragraph is, from its style and list format (never from the indent depth)."""
    if not para.text.strip():
        return "blank"
    if para.style == "Heading1":
        return SUBJECT
    if para.style == "Heading2":
        return TOPIC
    return {"decimal": SUBTOPIC, "lowerRoman": ITEM, "lowerLetter": SECTION}.get(para.list_format, "unknown")


def build_plan(paragraphs, file_notes=None):
    plan = Plan(file_notes=dict(file_notes or {}))
    heading1 = None  # the Heading 1 paragraph we are under
    in_misc = False
    subject = topic = subtopic = None
    previous_text = ""
    block = -1
    block_refs = {}  # block -> [refs in document order] (for the expected database order)
    block_is_misc = {}
    counters = Counter()  # (id(parent), category) -> last position used
    last_content = {}  # id(container) -> last Item/Section node placed in it
    main_count = other_count = 0

    def ref_of(para):
        return f"para-{para.index:04d}"

    def make(kind, para, parent, **kw):
        node = Node(kind=kind, ref=ref_of(para), original_line=para.text, parent=parent, para_index=para.index,
                    block=block, **kw)
        plan.nodes.append(node)
        block_refs.setdefault(block, []).append(node.ref)
        return node

    def place(node, parent, category):
        counters[(id(parent), category)] += 1
        node.position = counters[(id(parent), category)]

    def stop(para, message):
        plan.problems.append(f"Paragraph {para.index + 1}: {message} ({para.text[:80]!r})")

    for para in paragraphs:
        level = _level(para)
        if level == "blank":
            plan.blank_paragraphs.append((para.index, previous_text))
            if para.num_id:
                plan.warnings.append(f"Paragraph {para.index + 1} is an empty list entry; skipped.")
            continue
        plan.text_paragraphs += 1
        previous_text = para.text
        if para.odd_parts:
            plan.warnings.append(
                f"Paragraph {para.index + 1} contains {', '.join(sorted(set(para.odd_parts)))} inside the text; "
                "it is kept as it is."
            )

        if level == SUBJECT:
            block += 1
            heading1 = para
            in_misc = para.text.strip().lower() == MISC_NAME
            block_is_misc[block] = in_misc
            block_refs.setdefault(block, [])
            topic = subtopic = None
            if in_misc:
                subject = None
                plan.skipped_headings.append((ref_of(para), para.text))
                block_refs[block].append(ref_of(para))
            else:
                main_count += 1
                name = strip_colon(para.text)
                subject = make(SUBJECT, para, None, name=name)
                subject.position = subject.landing_position = main_count
            continue

        if heading1 is None:
            stop(para, "text before the first Heading 1")
            continue

        if level == TOPIC:
            topic = subtopic = None
            name = strip_colon(para.text)
            if in_misc:
                other_count += 1
                subject = make(SUBJECT, para, None, name=name, other_subject=True)
                subject.other_position = other_count
                subject.landing_position = 0
            else:
                topic = make(TOPIC, para, subject, name=name)
                place(topic, subject, TOPIC)
            continue

        # From here on the line must hang under a Topic (main Subject) or an Other Subject.
        if subject is None:
            stop(para, "this line sits directly under 'Miscellaneous', before any Topic")
            continue
        parent_of_sub = subject if subject.other_subject else topic
        if parent_of_sub is None:
            stop(para, "this line sits directly under a Subject, before any Topic")
            continue

        if level == SUBTOPIC:
            subtopic = make(SUBTOPIC, para, parent_of_sub, name=strip_colon(para.text))
            place(subtopic, parent_of_sub, SUBTOPIC)
            continue

        container = subtopic or parent_of_sub
        if level == SECTION:
            node = make(SECTION, para, container, name=para.text, review_note=SECTION_REVIEW_NOTE,
                        reason="section")
            place(node, container, "content")
            last_content[id(container)] = node
            continue

        if level == ITEM:
            reason, left, right = classify_item(para.text)
            node = make(ITEM, para, container, citation=right, reason=reason or "")
            if reason is None:
                node.text_html = runs_to_html(para.runs, 0, len(left))
            else:
                node.text_html = runs_to_html(para.runs)
            node.formatted = any(r.bold or r.italic or r.underline for r in para.runs)
            node.other_formatting = list(para.other_formatting)
            node._num_id = para.num_id
            if reason:
                node.review_note = f"Imported whole as Text with no Citation: {REASONS[reason]}."
            previous = last_content.get(id(container))
            if previous is not None and previous.kind == ITEM and previous._num_id != para.num_id:
                node.list_restarted = True
            place(node, container, "content")
            last_content[id(container)] = node
            continue

        stop(para, f"unrecognised line (style {para.style}, list format {para.list_format or 'none'})")

    for node in plan.nodes:
        limit = NAME_LIMITS.get(node.kind)
        if limit and len(node.name) > limit:
            plan.problems.append(f"{node.ref}: the {node.kind} name is longer than {limit} characters.")
    names = Counter(n.name.lower() for n in plan.of(SUBJECT))
    for name, count in names.items():
        if count > 1:
            plan.problems.append(f"Two Subjects would be called {name!r}; Subject names must be unique in a profile.")

    # The order the database lists things in: main Subjects as in the file, then the Other Subjects.
    order = []
    for b in sorted(block_refs):
        if not block_is_misc.get(b):
            order.extend(block_refs[b])
    for b in sorted(block_refs):
        if block_is_misc.get(b):
            order.extend(block_refs[b])
    plan.expected_order = order
    return plan


def summary_counts(plan):
    """Counts used by both reports."""
    items = plan.of(ITEM)
    flagged_items = [n for n in items if n.needs_review]
    sections = plan.of(SECTION)
    subjects = plan.of(SUBJECT)
    return {
        "subjects": len(subjects),
        "main_subjects": sum(1 for s in subjects if not s.other_subject),
        "other_subjects": sum(1 for s in subjects if s.other_subject),
        "topics": len(plan.of(TOPIC)),
        "subtopics": len(plan.of(SUBTOPIC)),
        "sections": len(sections),
        "items": len(items),
        "items_clean": len(items) - len(flagged_items),
        "items_flagged": len(flagged_items),
        "review_marked": len(flagged_items) + sum(1 for s in sections if s.needs_review),
        "text_paragraphs": plan.text_paragraphs,
        "blank_paragraphs": len(plan.blank_paragraphs),
        "colon_changes": sum(1 for n in plan.nodes if n.colon_removed),
    }
