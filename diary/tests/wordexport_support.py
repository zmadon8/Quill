"""Helpers for the Word export tests that need no database (standard library only).

``tree_from_plan`` turns the importer's plan of the real (or a small) Word file into the export's neutral tree the
way ``diary.wordexport.gather`` would from the database: alphabetical headings, Items and Sections by position,
a split line as an Item with one citation.
"""
from diary.importer.plan import ITEM, SECTION, SUBJECT, SUBTOPIC, TOPIC
from diary.sorting import sort_key
from diary.wordexport import model as m

DEFAULT_FMTS = {
    "topic_format": "A",
    "subtopic_format": "1",
    "section_format": "(a)",
    "item_format": "(1)",
    "multi_citation_format": "(a)",
}


def _container(plan, parent):
    entries = []
    kids = [n for n in plan.nodes if n.parent is parent and n.kind in (ITEM, SECTION)]
    for node in sorted(kids, key=lambda n: n.position):
        if node.kind == SECTION:
            entries.append(m.XSection(name=node.name, needs_review=node.needs_review, review_note=node.review_note))
        else:
            cases = [m.XCase(citation=node.citation)] if node.citation else []
            entries.append(m.XItem(html=node.text_html, cases=cases, needs_review=node.needs_review,
                                   review_note=node.review_note))
    return m.XContainer(entries)


def _sorted(nodes):
    return sorted(nodes, key=lambda n: sort_key(n.name, n.para_index))


def tree_from_plan(plan):
    """(main Subjects, other Subjects) as XSubject lists."""
    main, other = [], []
    for subject in _sorted(n for n in plan.nodes if n.kind == SUBJECT):
        xs = m.XSubject(name=subject.name, container=_container(plan, subject))
        for index, topic in enumerate(_sorted(n for n in plan.nodes if n.kind == TOPIC and n.parent is subject), 1):
            xt = m.XTopic(name=topic.name, index=index, container=_container(plan, topic))
            for sindex, sub in enumerate(_sorted(n for n in plan.nodes if n.kind == SUBTOPIC and n.parent is topic), 1):
                xt.subtopics.append(m.XSubtopic(name=sub.name, index=sindex, container=_container(plan, sub)))
            xs.topics.append(xt)
        for sindex, sub in enumerate(_sorted(n for n in plan.nodes if n.kind == SUBTOPIC and n.parent is subject), 1):
            xs.subtopics.append(m.XSubtopic(name=sub.name, index=sindex, container=_container(plan, sub)))
        (other if subject.other_subject else main).append(xs)
    return main, other
