"""Reads one profile's live records into the export's neutral tree (docs/DESIGN.md section 12).

The whole profile is read in a fixed number of queries (about ten), whatever its size, and walked in Python, so a
Full export of thousands of Items costs the same few queries as a small one. Only records reachable from a live
Subject through live parents are included: Trash, and anything below something in Trash, is left out. Order is the
Diary's: Subjects, Topics and Sub-topics alphabetical (``diary.sorting``); Items and Sections by position.
"""
from dataclasses import dataclass, field

from ..models import Case, Item, Note, NoteLink, Section, Subject, Subtopic, Topic, flag_label
from ..sorting import sort_headings
from . import model as m


@dataclass
class Snapshot:
    main: list = field(default_factory=list)  # XSubject, alphabetical
    others: list = field(default_factory=list)  # XSubject (Other Subjects), alphabetical
    subjects: dict = field(default_factory=dict)  # Subject id -> XSubject
    topics: dict = field(default_factory=dict)  # Topic id -> (XTopic, XSubject)
    subtopics: dict = field(default_factory=dict)  # Sub-topic id -> (XSubtopic, Topic id or None, XSubject)


def _short(text, fallback):
    return (text or "").strip()[:40] or fallback


def _live(model, profile, *fields):
    queryset = model.objects.filter(profile=profile, deleted_at__isnull=True)
    return queryset.only(*fields) if fields else queryset


def _by(rows, columns):
    """Group rows by their first filled parent column: {(column, id): [rows]}."""
    grouped = {}
    for row in rows:
        for name in columns:
            value = getattr(row, f"{name}_id")
            if value is not None:
                grouped.setdefault((name, value), []).append(row)
                break
    return grouped


def load(profile):
    """Build the Snapshot of ``profile``'s live diary."""
    base = ("id", "profile", "deleted_at", "position")
    subjects = list(_live(Subject, profile, *base, "name", "show_on_landing"))
    live_subject_ids = {s.pk for s in subjects}
    topics = [t for t in _live(Topic, profile, *base, "subject", "name") if t.subject_id in live_subject_ids]
    topics_by_id = {t.pk: t for t in topics}
    subtopics = [
        s for s in _live(Subtopic, profile, *base, "subject", "topic", "name")
        if (s.topic_id in topics_by_id if s.topic_id else s.subject_id in live_subject_ids)
    ]
    subtopics_by_id = {s.pk: s for s in subtopics}

    def container_live(row):
        if row.subtopic_id:
            return row.subtopic_id in subtopics_by_id
        if row.topic_id:
            return row.topic_id in topics_by_id
        return row.subject_id in live_subject_ids

    item_fields = base + ("subject", "topic", "subtopic", "text", "text_plain", "citation_layout",
                          "flag", "flag_text")
    all_items = list(_live(Item, profile, *item_fields))
    items = [i for i in all_items if container_live(i)]
    item_ids = {i.pk for i in items}
    sections = [s for s in _live(Section, profile, *base, "subject", "topic", "subtopic", "name", "flag",
                                 "flag_text") if container_live(s)]
    section_ids = {s.pk for s in sections}
    cases = [c for c in _live(Case, profile, *base, "item", "citation", "comment") if c.item_id in item_ids]
    notes = [
        n for n in _live(Note, profile, *base, "subject", "topic", "subtopic", "item", "section", "text")
        if (n.item_id in item_ids if n.item_id else n.section_id in section_ids if n.section_id else container_live(n))
    ]
    note_ids = {n.pk for n in notes}
    links = [
        link for link in _live(NoteLink, profile).order_by("position", "pk") if link.note_id in note_ids
    ]

    items_by = _by(items, ("subtopic", "topic", "subject"))
    sections_by = _by(sections, ("subtopic", "topic", "subject"))
    notes_by = _by(notes, ("item", "section", "subtopic", "topic", "subject"))
    cases_by = {}
    for case in sorted(cases, key=lambda c: (c.position, c.pk)):
        cases_by.setdefault(case.item_id, []).append(case)
    links_by = {}
    for link in links:
        links_by.setdefault(link.note_id, []).append(link)

    # -- where a link points: the same "Subject > Topic > ..." text the reading page shows -------------------
    items_by_id = {i.pk: i for i in items}
    sections_by_id = {s.pk: s for s in sections}
    subjects_by_id = {s.pk: s for s in subjects}

    def heading_path(kind, row):
        if kind == "subject":
            return [row.name]
        if kind == "topic":
            return [subjects_by_id[row.subject_id].name, row.name]
        if row.topic_id:
            topic = topics_by_id[row.topic_id]
            return [subjects_by_id[topic.subject_id].name, topic.name, row.name]
        return [subjects_by_id[row.subject_id].name, row.name]

    def container_path(row):
        if row.subtopic_id:
            return heading_path("subtopic", subtopics_by_id[row.subtopic_id])
        if row.topic_id:
            return heading_path("topic", topics_by_id[row.topic_id])
        return heading_path("subject", subjects_by_id[row.subject_id])

    reachable = {"subject": subjects_by_id, "topic": topics_by_id, "subtopic": subtopics_by_id,
                 "section": sections_by_id, "item": items_by_id}

    def link_of(link):
        from ..reading import note_link_info  # a target in Trash: the reading page's own code finds its path

        for kind in ("subject", "topic", "subtopic", "section", "item"):
            target_id = getattr(link, f"{kind}_id")
            if target_id is None:
                continue
            row = reachable[kind].get(target_id)
            if row is None:
                info = note_link_info(link)
                return m.XLink(info["path"], True)
            if kind == "item":
                return m.XLink(" > ".join(container_path(row) + [_short(row.text_plain, "Item")]))
            if kind == "section":
                return m.XLink(" > ".join(container_path(row) + [row.name or "Section"]))
            return m.XLink(" > ".join(heading_path(kind, row)))
        return m.XLink("", True)

    # -- the tree ---------------------------------------------------------------------------------
    def x_notes(key):
        return [m.XNote(n.text, [link_of(link) for link in links_by.get(n.pk, [])]) for n in notes_by.get(key, [])]

    def x_item(item):
        item_cases = cases_by.get(item.pk, [])
        return m.XItem(
            html=item.text,
            cases=[m.XCase(c.citation, c.comment) for c in item_cases],
            layout=item.citation_layout if len(item_cases) > 1 else "inline",
            flag_label=flag_label(item.flag, item.flag_text), notes=x_notes(("item", item.pk)),
        )

    def x_container(kind, pk):
        key = (kind, pk)
        rows = [("item", i) for i in items_by.get(key, [])] + [("section", s) for s in sections_by.get(key, [])]
        rows.sort(key=lambda e: (e[1].position, 0 if e[0] == "section" else 1, e[1].pk))
        entries = []
        for what, row in rows:
            if what == "section":
                entries.append(m.XSection(row.name, flag_label(row.flag, row.flag_text), x_notes(("section", row.pk))))
            else:
                entries.append(x_item(row))
        return m.XContainer(entries, x_notes(key))

    snapshot = Snapshot()
    topics_of, direct_subtopics_of, subtopics_of = {}, {}, {}
    for topic in topics:
        topics_of.setdefault(topic.subject_id, []).append(topic)
    for sub in subtopics:
        if sub.topic_id:
            subtopics_of.setdefault(sub.topic_id, []).append(sub)
        else:
            direct_subtopics_of.setdefault(sub.subject_id, []).append(sub)

    def build_subject(subject):
        xs = m.XSubject(subject.name, x_container("subject", subject.pk))
        snapshot.subjects[subject.pk] = xs
        for index, topic in enumerate(sort_headings(topics_of.get(subject.pk, [])), 1):
            xt = m.XTopic(topic.name, index, x_container("topic", topic.pk))
            for sindex, sub in enumerate(sort_headings(subtopics_of.get(topic.pk, [])), 1):
                xsub = m.XSubtopic(sub.name, sindex, x_container("subtopic", sub.pk))
                xt.subtopics.append(xsub)
                snapshot.subtopics[sub.pk] = (xsub, topic.pk, xs)
            xs.topics.append(xt)
            snapshot.topics[topic.pk] = (xt, xs)
        for sindex, sub in enumerate(sort_headings(direct_subtopics_of.get(subject.pk, [])), 1):
            xsub = m.XSubtopic(sub.name, sindex, x_container("subtopic", sub.pk))
            xs.subtopics.append(xsub)
            snapshot.subtopics[sub.pk] = (xsub, None, xs)
        return xs

    for subject in sort_headings([s for s in subjects if s.show_on_landing]):
        snapshot.main.append(build_subject(subject))
    for subject in sort_headings([s for s in subjects if not s.show_on_landing]):
        snapshot.others.append(build_subject(subject))
    return snapshot
