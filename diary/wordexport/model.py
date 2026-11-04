"""The neutral tree the Word export is made from (pure Python, no Django).

``gather.py`` fills it from the database (live records only, already in Diary order); ``render.py`` turns it
into a .docx; the tests can build one by hand. Numbers are not stored here: the renderer numbers by position.
"""
from dataclasses import dataclass, field


@dataclass
class XLink:
    path: str  # "Subject > Topic > ..." as the reading page shows it
    deleted: bool = False  # the target is in Trash: "(target deleted)"


@dataclass
class XNote:
    html: str = ""
    links: list = field(default_factory=list)


@dataclass
class XCase:
    citation: str = ""
    comment_html: str = ""


@dataclass
class XItem:
    html: str = ""  # the Item's text, rich (p, br, b, i, u)
    cases: list = field(default_factory=list)  # XCase, in order
    layout: str = "inline"  # "lines": each citation on its own line, "(a) <comment> - <citation>"
    flag_label: str = ""  # "" when the Item has no flag (models.flag_label: "Pending: ask", the text of Other...)
    notes: list = field(default_factory=list)  # XNote


@dataclass
class XSection:
    name: str = ""
    flag_label: str = ""  # Sections have flags too (D88)
    notes: list = field(default_factory=list)


@dataclass
class XContainer:
    """What sits directly under a Subject, Topic, Sub-topic: Items and Sections in manual order, then Notes."""

    entries: list = field(default_factory=list)  # XItem and XSection
    notes: list = field(default_factory=list)


@dataclass
class XSubtopic:
    name: str = ""
    index: int = 1  # 1-based place among its (alphabetical) siblings; the number is made from it
    container: XContainer = field(default_factory=XContainer)


@dataclass
class XTopic:
    name: str = ""
    index: int = 1
    container: XContainer = field(default_factory=XContainer)
    subtopics: list = field(default_factory=list)


@dataclass
class XSubject:
    name: str = ""
    container: XContainer = field(default_factory=XContainer)
    topics: list = field(default_factory=list)
    subtopics: list = field(default_factory=list)  # directly under the Subject (Other Subjects)


@dataclass
class ExportInput:
    """Everything one .docx needs.

    ``main`` are Subjects at Heading 1 (one for a Current View of a Subject or a per-Subject file).
    ``others`` are the Other Subjects grouped under one "Other Subjects" Heading 1 (Heading 2 each).
    ``view_topic`` / ``view_subtopic`` are a Current View of a Topic or Sub-topic (then ``main`` and ``others`` are empty).
    """

    title: str  # the export name, e.g. "Case Law Diary Main"
    part: str  # "Full", a Subject name, "Other Subjects" or the on-screen path
    date_text: str
    fmts: dict
    include_review: bool = False  # include the Flags (the name dates from before For review was merged into them, D88)
    main: list = field(default_factory=list)
    others: list = field(default_factory=list)
    view_topic: XTopic | None = None
    view_subtopic: XSubtopic | None = None
    path: list = field(default_factory=list)  # a Current View: the on-screen path, printed in the page header and the front page
    created: str = "2000-01-01T00:00:00Z"


def count_items(thing):
    """Items in the tree: the figure the screens show as the Item count."""
    if isinstance(thing, XItem):
        return 1
    if isinstance(thing, XSection):
        return 0
    if isinstance(thing, XContainer):
        return sum(count_items(e) for e in thing.entries)
    if isinstance(thing, XSubtopic):
        return count_items(thing.container)
    if isinstance(thing, XTopic):
        return count_items(thing.container) + sum(count_items(s) for s in thing.subtopics)
    if isinstance(thing, XSubject):
        return (count_items(thing.container) + sum(count_items(t) for t in thing.topics)
                + sum(count_items(s) for s in thing.subtopics))
    if isinstance(thing, ExportInput):
        total = sum(count_items(s) for s in thing.main) + sum(count_items(s) for s in thing.others)
        for single in (thing.view_topic, thing.view_subtopic):
            if single is not None:
                total += count_items(single)
        return total
    raise TypeError(thing)
