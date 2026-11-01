"""Turns the paragraphs of the Word file into a plan of records (pure Python, no database).

Rules come from docs/DESIGN.md section 8 and docs/IMPORT_ANALYSIS.md. Nothing is rewritten: the
only deliberate change to wording is the removal of a trailing colon from Topic, Sub-topic and
Subject names (decision I8), and every such change is reported.
"""
import re
from collections import Counter
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser

SUBJECT = "subject"
TOPIC = "topic"
SUBTOPIC = "subtopic"
SECTION = "section"
ITEM = "item"

MISC_NAME = "miscellaneous"
SECTION_REVIEW_NOTE = "imported from a small-letter (a)/(b) list; confirm these are Sections"
#: DEFAULT pending owner confirmation (docs/DESIGN.md decision D-a): a restarted Word list is flagged.
RESTART_NOTE = "Word list restarted here; the Diary numbers this group continuously."
#: DEFAULT pending owner confirmation (decision D-c): a plain Citation cannot hold bold or underline.
CITATION_FORMAT_NOTE = "Citation had bold/underline in Word that a plain Citation cannot hold."
CITATION_OTHER_FORMAT_NOTE = "Citation had other formatting in Word (colour, size and so on) that a plain Citation cannot hold."
NAME_FORMAT_NOTE = "Section name had italic/underline in Word that a plain name cannot hold."
DROPPED_NOTE = "This Word line contained parts that cannot be imported and were left out: "
#: Causes that flag a record without changing how it is split (a record can have several).
CAUSES = {
    "list_restart": "Word list restarted here",
    "citation_format": "bold/underline on the citation side",
    "citation_other": "other formatting on the citation side",
    "dropped": "parts of the Word line left out",
    "name_format": "italic/underline on a Section name",
}
MAX_CITATION = 1000
NAME_LIMITS = {SUBJECT: 300, TOPIC: 300, SUBTOPIC: 300, SECTION: 500}

#: Reasons an Item line is imported whole (key -> wording used in review notes and reports).
REASONS = {
    "spaces": "leading or trailing spaces",
    "line_break": "contains a line break",
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
    "items_clean": 691,
    "items_flagged": 259,
    "review_marked": 261,
    "text_paragraphs": 1495,
    "blank_paragraphs": 11,
    "colon_changes": 19,
    "paragraphs_total": 1506,
    "skipped_headings": 1,
    "problem_paragraphs": 0,
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
    if "\n" in text:
        return "line_break", text, ""
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


def runs_signature(runs, start=0, end=None):
    """Formatting fingerprint of characters ``start:end``: [(text, bold, italic, underline)], neighbours merged."""
    total = sum(len(r.text) for r in runs)
    end = total if end is None else end
    out = []
    pos = 0
    for run in runs:
        lo, hi = max(start, pos), min(end, pos + len(run.text))
        base = pos
        pos += len(run.text)
        if lo >= hi:
            continue
        piece = run.text[lo - base: hi - base]
        key = (run.bold, run.italic, run.underline)
        if out and out[-1][1:] == key:
            out[-1] = (out[-1][0] + piece,) + key
        else:
            out.append((piece,) + key)
    return out


class _SignatureParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = {"b": 0, "i": 0, "u": 0}
        self.out = []

    def handle_starttag(self, tag, attrs):
        if tag in self.depth:
            self.depth[tag] += 1

    def handle_endtag(self, tag):
        if tag in self.depth:
            self.depth[tag] = max(0, self.depth[tag] - 1)

    def handle_data(self, data):
        key = (self.depth["b"] > 0, self.depth["i"] > 0, self.depth["u"] > 0)
        if self.out and self.out[-1][1:] == key:
            self.out[-1] = (self.out[-1][0] + data,) + key
        else:
            self.out.append((data,) + key)


def html_signature(html):
    """The same fingerprint, read back from stored Text HTML (tags p, b, i, u)."""
    parser = _SignatureParser()
    parser.feed(html or "")
    parser.close()
    return [seg for seg in parser.out if seg[0]]


def citation_side_formatting(runs, start):
    """Formatting on characters from ``start`` on that a plain Citation cannot hold (italic is expected).

    Returns (bold_or_underline: bool, other: sorted list of property names).
    """
    pos = 0
    strong = False
    other = set()
    for run in runs:
        lo, hi = pos, pos + len(run.text)
        pos = hi
        if hi <= start or not run.text[max(start, lo) - lo:].strip():
            continue
        strong = strong or run.bold or run.underline
        other.update(run.other)
    return strong, sorted(other)


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
    signature: list = field(default_factory=list)  # Item: formatting fingerprint of the Text as Word has it
    citation_format: list = field(default_factory=list)  # Item: "bold/underline" and/or "other" on the citation side
    name_formatting: list = field(default_factory=list)  # names: formats Word had that a plain name cannot keep
    other_formatting: list = field(default_factory=list)
    list_restarted: bool = False
    dropped_parts: list = field(default_factory=list)  # parts of the Word line that are not in the text
    causes: list = field(default_factory=list)  # keys of every cause that flags this record (see CAUSES)
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
    total_paragraphs: int = 0  # every paragraph in the file, blank or not
    problem_paragraphs: int = 0  # paragraphs the plan could not place (each is also a problem)
    word_groups: list = field(default_factory=list)  # (ref, items after it, sorted list ids) read from Word's lists

    def of(self, kind):
        return [n for n in self.nodes if n.kind == kind]


def _flag(node, cause, note):
    """Mark a record for review for ``cause``; several causes add their notes together."""
    node.causes.append(cause)
    node.review_note = f"{node.review_note} {note}".strip()


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
        node.name_formatting = sorted(
            {"italic" for r in para.runs if r.italic} | {"underline" for r in para.runs if r.underline}
        ) if kind != ITEM else []
        plan.nodes.append(node)
        block_refs.setdefault(block, []).append(node.ref)
        return node

    def place(node, parent, category):
        counters[(id(parent), category)] += 1
        node.position = counters[(id(parent), category)]

    def stop(para, message):
        plan.problem_paragraphs += 1
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
                "these are kept in the text as typed."
            )
        if para.dropped_parts:
            plan.warnings.append(
                f"Paragraph {para.index + 1} contains {', '.join(sorted(set(para.dropped_parts)))} that cannot be "
                "imported; it is NOT in the stored text (an Item or Section with this is flagged for review)."
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
            if node.name_formatting:
                _flag(node, "name_format", NAME_FORMAT_NOTE + " (" + ", ".join(node.name_formatting) + ")")
            if para.dropped_parts:
                _flag(node, "dropped", DROPPED_NOTE + ", ".join(sorted(set(para.dropped_parts))) + ".")
                node.dropped_parts = sorted(set(para.dropped_parts))
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
            node.signature = runs_signature(para.runs, 0, len(left)) if reason is None else runs_signature(para.runs)
            node.formatted = any(r.bold or r.italic or r.underline for r in para.runs)
            node.other_formatting = list(para.other_formatting)
            node._num_id = para.num_id
            if reason:
                node.review_note = f"Imported whole as Text with no Citation: {REASONS[reason]}."
            else:
                strong, other = citation_side_formatting(para.runs, len(left) + 3)
                if strong:
                    _flag(node, "citation_format", CITATION_FORMAT_NOTE)
                if other:
                    _flag(node, "citation_other", CITATION_OTHER_FORMAT_NOTE + " (" + ", ".join(other) + ")")
            previous = last_content.get(id(container))
            if previous is not None and previous.kind == ITEM and previous._num_id != para.num_id:
                node.list_restarted = True
                _flag(node, "list_restart", RESTART_NOTE)
            if para.dropped_parts:
                node.dropped_parts = sorted(set(para.dropped_parts))
                _flag(node, "dropped", DROPPED_NOTE + ", ".join(node.dropped_parts) + ".")
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

    plan.total_paragraphs = len(paragraphs)
    for node in plan.nodes:
        if node.kind in (SUBJECT, TOPIC, SUBTOPIC) and not node.name.strip():
            plan.problems.append(
                f"{node.ref}: the {node.kind} name is empty (nothing is left after the trailing colon is removed): "
                f"{node.original_line!r}."
            )
    plan.word_groups = word_list_groups(paragraphs)
    wanted = [(ref, count) for ref, count, _ids in plan.word_groups]
    from_plan = [(ref, count) for ref, _name, count in section_item_counts(plan)]
    if wanted != from_plan:
        plan.problems.append(
            f"The Items under each Section differ between Word's own lists {wanted} and the plan {from_plan}."
        )
    done = completeness(plan)
    if not done["ok"]:
        plan.problems.append("Not every paragraph of the file is accounted for: " + done["equation"] + ".")

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


def section_item_counts(plan):
    """For each Section: (ref, name, Items after it up to the next Section), from the plan's positions."""
    groups = []
    for section in plan.of(SECTION):
        siblings = [n for n in plan.nodes if n.parent is section.parent and n.kind in (ITEM, SECTION)]
        siblings.sort(key=lambda n: n.position)
        count = 0
        for n in siblings:
            if n.position <= section.position:
                continue
            if n.kind == SECTION:
                break
            count += 1
        groups.append((section.ref, section.name, count))
    return groups


def word_list_groups(paragraphs):
    """Word's own grouping, read straight from the paragraphs (not from the plan).

    For every small-letter (a)/(b) Section line: (ref, Items that follow it before the next numbered line
    that is not an Item or the next heading, sorted list ids those Items belong to).
    """
    groups = []
    for i, para in enumerate(paragraphs):
        if _level(para) != SECTION:
            continue
        count = 0
        ids = set()
        for later in paragraphs[i + 1:]:
            level = _level(later)
            if level == "blank":
                continue
            if level != ITEM:
                break
            count += 1
            ids.add(later.num_id)
        groups.append((f"para-{para.index:04d}", count, sorted(ids)))
    return groups


def completeness(plan):
    """Every paragraph is a planned record, the skipped 'Miscellaneous' heading, blank, or a problem."""
    parts = (len(plan.nodes), len(plan.skipped_headings), len(plan.blank_paragraphs), plan.problem_paragraphs)
    total = plan.total_paragraphs
    equation = (f"{parts[0]} planned records + {parts[1]} skipped heading(s) + {parts[2]} blank + "
                f"{parts[3]} problem(s) = {sum(parts)}; paragraphs in the file = {total}")
    return {"ok": sum(parts) == total, "equation": equation, "parts": parts, "total": total}


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
        "paragraphs_total": plan.total_paragraphs,
        "skipped_headings": len(plan.skipped_headings),
        "problem_paragraphs": plan.problem_paragraphs,
    }
