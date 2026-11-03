"""Global Search over one profile (docs/DESIGN.md section 10).

The profile's live text is loaded in a fixed number of queries (three for the headings, then Sections, Items,
Cases and Notes), turned into in-memory records and matched with the pure rules of diary/searchtext.py. Nothing
is stored for search, so every way of changing data (editing, import, conversions, restore, Undo) stays correct
without extra work.

Trash is excluded: a deleted record, and anything below a deleted Subject, Topic or Sub-topic, a Case of a deleted Item, a Note on a deleted Item or Section. Where a record sits
in the Diary comes from diary/locate.py, the same code the Review list uses.
"""
from dataclasses import dataclass, field

from django.urls import reverse

from . import searchtext
from .locate import Tree
from .models import FLAG_CHOICES, FLAG_NONE, Case, Item, Note, Section

FIELD_LABELS = {
    "name": "Name",
    "section": "Section",
    "text": "Text",
    "citation": "Citation",
    "comment": "Comment",
    "flag": "Flag",
    "review_note": "Review note",
    "note": "Note",
}
KIND_LABELS = {"subject": "Subject", "topic": "Topic", "subtopic": "Sub-topic"}
_FLAG_NAMES = dict(FLAG_CHOICES)
_LABEL_LENGTH = 100


@dataclass
class SearchResult:
    kind: str  # Subject, Topic, Sub-topic, Section, Item or Note
    label: str  # the record's own name or a short form of its text
    path: list  # [(name, url or None)] of the headings above it (for a Note on an Item: the Item's label too)
    url: str  # read_subject url + "#" + anchor of the element
    segments: list  # [(text, highlighted)] excerpt of the first field that matched; the caller escapes it
    field_label: str  # which field the excerpt is from ("Citation", "Text", ...)
    flag_text: str = ""
    needs_review: bool = False
    review_note: str = ""
    text: str = ""  # the record's whole own text (an Item's plain text, a Section's name); the Review list shortens it
    subject_id: int = 0
    score: int = 0
    order: tuple = field(default_factory=tuple)


class _Record:
    """One searchable record, before matching."""

    __slots__ = ("kind", "label", "place", "extra_path", "anchor", "fields", "tail", "flag_text",
                 "needs_review", "review_note", "self_heading", "text")

    def __init__(self, kind, label, place, anchor, fields, tail, extra_path=(), flag_text="",
                 needs_review=False, review_note="", self_heading=None, text=""):
        self.kind = kind
        self.text = text
        self.label = label
        self.place = place
        self.anchor = anchor
        self.fields = [(key, text) for key, text in fields if text and text.strip()]
        self.tail = tail
        self.extra_path = list(extra_path)
        self.flag_text = flag_text
        self.needs_review = needs_review
        self.review_note = review_note
        self.self_heading = self_heading


def _short(text):
    text = " ".join((text or "").split())
    return text if len(text) <= _LABEL_LENGTH else text[: _LABEL_LENGTH - 1].rstrip() + "\u2026"


def _field_label(key):
    return FIELD_LABELS[key.split("#")[0]]


class _Urls:
    """reverse() once per heading."""

    def __init__(self):
        self._cache = {}

    def of(self, kind, pk):
        key = (kind, pk)
        if key not in self._cache:
            self._cache[key] = reverse("read_" + kind, args=[pk])
        return self._cache[key]


def _item_label(row, cases):
    return _short(row["text_plain"]) or next(
        (_short(c["citation"]) for c in cases if c["citation"]), "") or "Item"


def _heading_records(tree):
    for subject in tree.subjects.values():
        place = tree.place(subject.pk)
        if place is not None:
            yield _Record("subject", subject.name, place, "", [("name", subject.name)], (0, 0, 0, subject.pk),
                          self_heading=subject)
    for topic in tree.topics.values():
        place = tree.place(topic.subject_id, topic.pk)
        if place is not None:
            yield _Record("topic", topic.name, place, f"n-topic-{topic.pk}", [("name", topic.name)],
                          (0, 0, 0, topic.pk), self_heading=topic)
    for sub in tree.subtopics.values():
        place = tree.place(sub.subject_id, sub.topic_id, sub.pk)
        if place is not None:
            yield _Record("subtopic", sub.name, place, f"n-subtopic-{sub.pk}", [("name", sub.name)],
                          (0, 0, 0, sub.pk), self_heading=sub)


def _section_name_records(profile, tree, citations_only, review_only):
    if citations_only:
        return
    for row in Section.objects.filter(profile=profile, deleted_at__isnull=True).values(
            "pk", "subject_id", "topic_id", "subtopic_id", "name", "position", "needs_review", "review_note"):
        place = tree.place(row["subject_id"], row["topic_id"], row["subtopic_id"])
        if place is None or (review_only and not row["needs_review"]):
            continue
        label = _short(row["name"]) or "Section"
        yield _Record("section", label, place, f"n-section-{row['pk']}", [("section", row["name"])],
                      (1, row["position"], 0, row["pk"]), needs_review=row["needs_review"],
                      review_note=row["review_note"], text=row["name"])


def _records(profile, tree, citations_only, review_only, headers_only=False):
    """Every live, locatable record the filters allow. ``headers_only`` limits it to the names of Subjects, Topics,
    Sub-topics and Sections (no Item, Case, Note, review note or flag text)."""
    with_notes_and_headings = not (citations_only or review_only)
    if with_notes_and_headings:
        yield from _heading_records(tree)
    if headers_only:
        yield from _section_name_records(profile, tree, citations_only, review_only)
        return

    sections = list(Section.objects.filter(profile=profile, deleted_at__isnull=True).values(
        "pk", "subject_id", "topic_id", "subtopic_id", "name", "position", "needs_review", "review_note"))
    items = {row["pk"]: row for row in Item.objects.filter(profile=profile, deleted_at__isnull=True).values(
        "pk", "subject_id", "topic_id", "subtopic_id", "text_plain", "flag",
        "flag_text", "needs_review", "review_note", "position")}
    cases = {}
    for row in Case.objects.filter(profile=profile, deleted_at__isnull=True).order_by("position", "pk").values(
            "item_id", "pk", "citation", "comment_plain"):
        cases.setdefault(row["item_id"], []).append(row)

    # Items first (a Note on an Item needs its place), then Sections.
    item_info = {}  # pk -> (place, tail, label)
    for pk, row in items.items():
        place = tree.place(row["subject_id"], row["topic_id"], row["subtopic_id"])
        tail = (1, row["position"], 1, pk)
        if place is None:
            continue
        item_cases = cases.get(pk, [])
        label = _item_label(row, item_cases)
        item_info[pk] = (place, tail, label)

        if review_only and not row["needs_review"]:
            continue
        fields = []
        if not citations_only:
            fields.append(("text", row["text_plain"]))
        for case in item_cases:
            fields.append((f"citation#{case['pk']}", case["citation"]))
            if not citations_only:
                fields.append((f"comment#{case['pk']}", case["comment_plain"]))
        if not citations_only:
            fields.append(("flag", row["flag_text"]))
            fields.append(("review_note", row["review_note"]))
        record = _Record(
            "item", label, place, f"n-item-{pk}", fields, tail,
            flag_text=row["flag_text"] or (_FLAG_NAMES[row["flag"]] if row["flag"] != FLAG_NONE else ""),
            needs_review=row["needs_review"], review_note=row["review_note"], text=row["text_plain"])
        if citations_only and not record.fields:
            continue
        yield record

    section_info = {}
    for row in sections:
        place = tree.place(row["subject_id"], row["topic_id"], row["subtopic_id"])
        if place is None:
            continue
        tail = (1, row["position"], 0, row["pk"])
        label = _short(row["name"]) or "Section"
        section_info[row["pk"]] = (place, tail, label)
        if citations_only or (review_only and not row["needs_review"]):
            continue
        yield _Record("section", label, place, f"n-section-{row['pk']}",
                      [("section", row["name"]), ("review_note", row["review_note"])], tail,
                      needs_review=row["needs_review"], review_note=row["review_note"], text=row["name"])

    if not with_notes_and_headings:
        return
    for row in Note.objects.filter(profile=profile, deleted_at__isnull=True).values(
            "pk", "subject_id", "topic_id", "subtopic_id", "item_id", "section_id", "text_plain", "position"):
        label = _short(row["text_plain"]) or "Note"
        own = (1, row["position"], row["pk"])
        if row["item_id"]:
            info = item_info.get(row["item_id"])
            if info is None:
                continue  # its Item is deleted
            place, tail, parent_label = info
            yield _Record("note", label, place, f"n-note-{row['pk']}", [("note", row["text_plain"])],
                          tail + own, extra_path=[(parent_label, None)])
        elif row["section_id"]:
            info = section_info.get(row["section_id"])
            if info is None:
                continue
            place, tail, parent_label = info
            yield _Record("note", label, place, f"n-note-{row['pk']}", [("note", row["text_plain"])],
                          tail + own, extra_path=[(parent_label, None)])
        else:
            place = tree.place(row["subject_id"], row["topic_id"], row["subtopic_id"])
            if place is None:
                continue
            yield _Record("note", label, place, f"n-note-{row['pk']}", [("note", row["text_plain"])], (2, row["position"], row["pk"]),
                          extra_path=[])


def run_search(profile, query, subject_id=None, citations_only=False, review_only=False, headers_only=False):
    """Every match of ``query`` in ``profile`` as a list of SearchResult, best first (unpaginated).

    Best first is: the whole query appearing together first, then the order of the Diary. An empty query
    lists everything the Citations only / For review only filters select; with neither filter it lists nothing.
    ``headers_only`` searches only the Subject, Topic, Sub-topic and Section names.
    """
    terms = searchtext.parse_query(query)
    if not terms and not (citations_only or review_only):
        return []
    tree = Tree.load(profile)
    urls = _Urls()
    results = []
    for rec in _records(profile, tree, citations_only, review_only, headers_only):
        place = rec.place
        if subject_id is not None and place.subject.pk != subject_id:
            continue
        matched = searchtext.match_fields(rec.fields, terms)
        if matched is None:
            continue
        score = 0
        if terms:
            score = 2 if len(terms) > 1 and searchtext.contains_whole_query(rec.fields, terms) else 1
        key, text = next(((k, t) for k, t in rec.fields if k in matched), rec.fields[0] if rec.fields else ("", ""))
        segments = searchtext.snippet(text, matched.get(key, []))
        headings = place.headings
        if rec.self_heading is not None:
            headings = headings[:-1]
        path = [(h.name, urls.of(h.kind, h.pk)) for h in headings] + rec.extra_path
        subject_url = urls.of("subject", place.subject.pk)
        results.append(SearchResult(
            kind=KIND_LABELS.get(rec.kind, rec.kind.capitalize()),
            label=rec.label,
            path=path,
            url=subject_url + (f"#{rec.anchor}" if rec.anchor else ""),
            segments=segments,
            field_label=_field_label(key) if key else "",
            flag_text=rec.flag_text,
            needs_review=rec.needs_review,
            review_note=rec.review_note,
            text=rec.text,
            subject_id=place.subject.pk,
            score=score,
            order=place.order + rec.tail,
        ))
    results.sort(key=lambda r: (-r.score, r.order))
    return results
