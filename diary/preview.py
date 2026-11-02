"""A small sample diary numbered with the chosen formats (My settings preview). Pure Python, no Django.

It uses the same numbering functions and the same full stop rule as the reading page, so what it shows
is what the reading page will show.
"""
from . import numbering

KEYS = ("topic", "subtopic", "section", "item", "nested_item", "multi_citation")

DEFAULTS = {
    "topic": "A",
    "subtopic": "1",
    "section": "(a)",
    "item": "(1)",
    "nested_item": "bullet",
    "multi_citation": "(a)",
}

TOPIC, SUBTOPIC, SECTION, ITEM, NESTED, CITATION, SUBJECT = (
    "topic", "subtopic", "section", "item", "nested", "citation", "subject",
)


def _row(indent, label, text, kind):
    return {"indent": indent, "label": label, "text": text, "kind": kind}


def build_preview(formats):
    """Rows for the sample. ``formats`` maps the names in ``KEYS`` to numbering keys; missing ones use the defaults."""
    fmt = {key: formats.get(key) or DEFAULTS[key] for key in KEYS}
    topics = numbering.number_siblings(2, fmt["topic"])
    subtopics = numbering.number_siblings(2, fmt["subtopic"])
    # Under the first Topic: a Section with two Items (the second has two citations), a Nested Item with
    # two children, then a second Section and an Item that restarts at the first number.
    kinds = [numbering.SECTION, numbering.ITEM, numbering.ITEM, numbering.NESTED, numbering.SECTION, numbering.ITEM]
    labels = numbering.number_children(kinds, fmt["item"], fmt["section"])
    citations = numbering.number_siblings(2, fmt["multi_citation"])
    children = numbering.number_siblings(2, fmt["nested_item"])
    shown = numbering.display_label

    rows = [_row(0, "", "Sample Subject", SUBJECT)]
    rows.append(_row(1, shown(topics[0]), "Sample Topic", TOPIC))
    for number, label in enumerate(subtopics, start=1):
        rows.append(_row(2, shown(label), f"Sample Sub-topic {number}", SUBTOPIC))
    rows.append(_row(2, shown(labels[0]), "Sample Section", SECTION))
    rows.append(_row(3, shown(labels[1]), "First Item", ITEM))
    rows.append(_row(3, shown(labels[2]), "Second Item, with two citations", ITEM))
    rows.append(_row(4, citations[0], "Sample v. Example (2020) 1 SCC 1", CITATION))
    rows.append(_row(4, citations[1], "Example v. Sample (2021) 2 SCC 2", CITATION))
    rows.append(_row(3, shown(labels[3]), "A Nested Item", NESTED))
    rows.append(_row(4, shown(children[0]), "First child", ITEM))
    rows.append(_row(4, shown(children[1]), "Second child", ITEM))
    rows.append(_row(2, shown(labels[4]), "Another Section", SECTION))
    rows.append(_row(3, shown(labels[5]), "First Item after the Section starts again", ITEM))
    rows.append(_row(1, shown(topics[1]), "Second Sample Topic", TOPIC))
    return rows
