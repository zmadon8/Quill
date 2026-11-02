"""Builds the reading view for one Subject (docs/DESIGN.md sections 2, 4, 5.2, 5.3, 7, 11).

The whole Subject is loaded in a handful of queries and turned into a flat list
of blocks (headings, Items, Sections, Notes) so that numbering is always
computed against the real siblings, even when only one Topic or Sub-topic is shown.
"""
from django.db.models import Q
from django.urls import reverse
from django.utils.safestring import mark_safe

from . import numbering
from .models import Case, Item, Note, NoteLink, Section, Subtopic, Topic
from .richtext import sanitise_html
from .sorting import sort_headings

#: Stored format names (models.FORMAT_CHOICES) -> keys understood by diary.numbering.
FORMAT_KEYS = {
    "upper_alpha": "A",
    "lower_alpha": "a",
    "decimal": "1",
    "upper_roman": "I",
    "lower_roman": "i",
    "paren_upper_alpha": "(A)",
    "paren_lower_roman": "(i)",
    "paren_lower_alpha": "(a)",
    "paren_decimal": "(1)",
    "bullet": "bullet",
    "none": "none",
    "section_n": "Section 1",
}

DEFAULT_FORMATS = {
    "topic_format": "upper_alpha",
    "subtopic_format": "decimal",
    "section_format": "paren_lower_alpha",
    "item_format": "paren_decimal",
    "multi_citation_format": "paren_lower_alpha",
}

READ_URL_NAMES = {"subject": "read_subject", "topic": "read_topic", "subtopic": "read_subtopic"}


def formats_for(user):
    """The user's number formats as numbering keys (defaults if they have no settings yet)."""
    chosen = dict(DEFAULT_FORMATS)
    settings = getattr(user, "diary_settings", None) if user is not None else None
    if settings is not None:
        for name in chosen:
            chosen[name] = getattr(settings, name)
    return {name: FORMAT_KEYS[value] for name, value in chosen.items()}


def live(queryset):
    return queryset.filter(deleted_at__isnull=True)


def _html(value):
    # Stored HTML is already cleaned on save; clean again on the way out as a second guard.
    return mark_safe(sanitise_html(value))


class _Data:
    """Everything live under one Subject, grouped by parent."""

    def __init__(self, subject):
        self.subject = subject
        # Subjects, Topics and Sub-topics are always alphabetical (diary/sorting.py); stored positions are the kept Word order.
        self.topics = sort_headings(live(Topic.objects.filter(subject=subject)))
        topic_ids = [t.pk for t in self.topics]
        self.subtopics = sort_headings(
            live(Subtopic.objects.filter(Q(subject=subject) | Q(topic_id__in=topic_ids)))
        )
        subtopic_ids = [s.pk for s in self.subtopics]
        container = (
            Q(subject=subject) | Q(topic_id__in=topic_ids) | Q(subtopic_id__in=subtopic_ids)
        )
        all_items = list(live(Item.objects.filter(container)))
        sections = list(live(Section.objects.filter(container)))
        item_ids = [i.pk for i in all_items]
        section_ids = [s.pk for s in sections]
        cases = list(live(Case.objects.filter(item_id__in=item_ids)).order_by("position", "pk"))
        notes = list(
            live(
                Note.objects.filter(
                    container | Q(item_id__in=item_ids) | Q(section_id__in=section_ids)
                )
            ).order_by("position", "pk")
        )
        self.links = {}
        outgoing = live(NoteLink.objects.filter(note__in=notes)).select_related(*_link_paths()).order_by("position", "pk")
        for link in outgoing:
            self.links.setdefault(link.note_id, []).append(link)

        # Links INTO this Subject from live Notes anywhere (Linked from). A Note in Trash, or under something in Trash, shows nothing.
        self.incoming = {}
        targets = Q(subject=subject) | Q(topic_id__in=topic_ids) | Q(subtopic_id__in=subtopic_ids)
        targets |= Q(section_id__in=section_ids) | Q(item_id__in=item_ids)
        found = live(NoteLink.objects.filter(targets, note__deleted_at__isnull=True)).select_related(*_note_paths("note")).order_by("note_id", "pk")
        for link in found:
            if in_trash(link.note):
                continue
            kind = next(name for name in LINK_COLUMNS if getattr(link, f"{name}_id") is not None)
            path, url = note_place(link.note)
            entry = {"note_id": link.note_id, "path": " > ".join(path), "url": url}
            if entry not in self.incoming.setdefault((kind, getattr(link, f"{kind}_id")), []):
                self.incoming[(kind, getattr(link, f"{kind}_id"))].append(entry)

        self.subtopics_by = {}
        for sub in self.subtopics:
            key = ("topic", sub.topic_id) if sub.topic_id else ("subject", sub.subject_id)
            self.subtopics_by.setdefault(key, []).append(sub)
        self.items_by = {}
        for item in all_items:
            self.items_by.setdefault(self._key(item, ("subject", "topic", "subtopic")), []).append(item)
        self.sections_by = {}
        for section in sections:
            self.sections_by.setdefault(self._key(section, ("subject", "topic", "subtopic")), []).append(section)
        self.notes_by = {}
        for note in notes:
            self.notes_by.setdefault(self._key(note, ("subject", "topic", "subtopic", "item", "section")), []).append(note)
        self.cases_by_item = {}
        for case in cases:
            self.cases_by_item.setdefault(case.item_id, []).append(case)

    @staticmethod
    def _key(obj, fields):
        for name in fields:
            value = getattr(obj, f"{name}_id")
            if value is not None:
                return (name, value)
        raise ValueError("record has no parent")


LINK_COLUMNS = ("subject", "topic", "subtopic", "section", "item")


def _record_paths(prefix):
    """select_related paths for a record at ``prefix`` and the headings above it (Sub-topic > Topic > Subject)."""
    return [prefix, f"{prefix}__subject", f"{prefix}__topic__subject", f"{prefix}__subtopic__subject",
            f"{prefix}__subtopic__topic__subject"]


def _item_paths(prefix):
    return _record_paths(prefix)


def _link_paths():
    """Everything note_link_info and in_trash read from a link's target, loaded in the same query (no per-link queries)."""
    return ["subject", "topic__subject", "subtopic__subject", "subtopic__topic__subject"] + _record_paths("section") + _item_paths("item")


def _note_paths(prefix):
    """Everything note_place and in_trash read from a Note, loaded in the same query."""
    return _record_paths(prefix) + _record_paths(f"{prefix}__section") + _item_paths(f"{prefix}__item")


PARENT_COLUMNS = ("item", "section", "subtopic", "topic", "subject")


def _up(obj):
    """The record directly above ``obj`` (any kind), or None for a Subject."""
    for name in PARENT_COLUMNS:
        if getattr(obj, f"{name}_id", None) is not None:
            return getattr(obj, name)
    return None


def in_trash(obj):
    """True if ``obj`` or anything above it is in Trash (such a record is hidden from every page)."""
    while obj is not None:
        if obj.deleted_at is not None:
            return True
        obj = _up(obj)
    return False


def _subject_page(container):
    """The Subject (a record) whose whole-Subject page holds every anchor of ``container`` ('subject'|'topic'|'subtopic', record)."""
    kind, obj = container
    if kind == "subject":
        return obj
    if kind == "topic":
        return obj.subject
    return obj.subject if obj.subject_id else obj.topic.subject


def _anchor_url(container, anchor):
    return f"{reverse('read_subject', args=[_subject_page(container).pk])}#{anchor}"


def note_link_info(link):
    """{'path', 'url', 'deleted'} for one cross-reference link.

    ``url`` goes to the target in context (the whole-Subject page at the target's anchor). A target in Trash, or inside
    something in Trash, gives ``deleted`` True and no url; the link itself is kept and works again when the target is restored.
    """
    target = next(getattr(link, name) for name in LINK_COLUMNS if getattr(link, name) is not None)
    path, container, anchor = _locate(target)
    if in_trash(target):
        return {"path": " > ".join(path), "url": None, "deleted": True}
    return {"path": " > ".join(path), "url": _anchor_url(container, anchor), "deleted": False}


def note_target(link):
    """(path text, url or None) for one cross-reference link; a deleted target gives '... (target deleted)' and no url."""
    info = note_link_info(link)
    return (info["path"] + " (target deleted)" if info["deleted"] else info["path"]), info["url"]


def _chain(obj):
    """(names, (kind, container)) for a Subject, Topic or Sub-topic."""
    if isinstance(obj, Topic):
        return [obj.subject.name, obj.name], ("topic", obj)
    if isinstance(obj, Subtopic):
        if obj.topic_id:
            return [obj.topic.subject.name, obj.topic.name, obj.name], ("subtopic", obj)
        return [obj.subject.name, obj.name], ("subtopic", obj)
    return [obj.name], ("subject", obj)


def _short(text, fallback):
    return text.strip()[:40] or fallback


def _locate(target):
    """(path names, (kind, heading container), anchor id) of any Subject, Topic, Sub-topic, Section or Item."""
    if isinstance(target, Subtopic):
        path, container = _chain(target)
        return path, container, f"n-subtopic-{target.pk}"
    if isinstance(target, Topic):
        path, container = _chain(target)
        return path, container, f"n-topic-{target.pk}"
    if not isinstance(target, (Item, Section)):
        path, container = _chain(target)
        return path, container, f"n-subject-{target.pk}"
    names = []
    top = target
    if isinstance(target, Item):
        names.insert(0, _short(top.text_plain, "Item"))
        anchor = f"n-item-{target.pk}"
    else:
        names.append(target.name or "Section")
        anchor = f"n-section-{target.pk}"
    parent = top.subtopic or top.topic or top.subject
    path, container = _chain(parent)
    return path + names, container, anchor


def note_place(note):
    """(path names, url) of a Note: where it sits, and the whole-Subject page at the Note's own anchor."""
    parent = next(getattr(note, name) for name in ("item", "section", "subtopic", "topic", "subject") if getattr(note, f"{name}_id"))
    path, container, _ = _locate(parent)
    return path, _anchor_url(container, f"n-note-{note.pk}")


def run_of(obj):
    """The key of the position run an Item or Section sits in (used by the edit mode drag script)."""
    for column in ("subtopic", "topic", "subject"):
        if getattr(obj, f"{column}_id"):
            return f"run-{column}-{getattr(obj, f'{column}_id')}"
    return ""


def _item_block(item, data, fmts, label, depth, under_section):
    cases = data.cases_by_item.get(item.pk, [])
    # One citation shows without a label; two or more are labelled with the Multi-Item citation format.
    case_labels = numbering.number_siblings(len(cases), fmts["multi_citation_format"]) if len(cases) > 1 else [""] * len(cases)
    return {
        "kind": "item",
        "id": item.pk,
        "version": item.version,
        "run": run_of(item),
        "anchor": f"n-item-{item.pk}",
        "label": label,
        "depth": depth,
        "indent": under_section,
        "is_multi": len(cases) > 1,
        # With several citations the owner chooses how they show: inline "(a) X; (b) Y" after the text, or each on its own line.
        "layout": item.citation_layout if len(cases) > 1 else "inline",
        "text": _html(item.text),
        "has_text": bool(item.text_plain.strip()),
        "cases": [
            {"label": lab, "citation": c.citation, "comment": _html(c.comment), "has_comment": bool(c.comment_plain.strip())}
            for lab, c in zip(case_labels, cases)
        ],
        "flag": item.flag if item.flag != "none" else "",
        "flag_label": item.flag_text or item.get_flag_display(),
        "needs_review": item.needs_review,
        "review_note": item.review_note,
        "notes": [_note_block(n, data) for n in data.notes_by.get(("item", item.pk), [])],
        "linked_from": data.incoming.get(("item", item.pk), []),
    }


def _note_block(note, data):
    links = [note_link_info(link) for link in data.links.get(note.pk, [])]
    return {"kind": "note", "id": note.pk, "version": note.version, "anchor": f"n-note-{note.pk}",
            "text": _html(note.text), "links": links, "linked_from": []}


def _container_blocks(key, depth, data, fmts):
    entries = [("item", i) for i in data.items_by.get(key, [])] + [("section", s) for s in data.sections_by.get(key, [])]
    entries.sort(key=lambda e: (e[1].position, 0 if e[0] == "section" else 1, e[1].pk))
    kinds = [numbering.SECTION if k == "section" else numbering.ITEM for k, o in entries]
    labels = numbering.number_children(kinds, fmts["item_format"], fmts["section_format"])
    blocks = []
    under_section = False
    for (kind, obj), label in zip(entries, labels):
        if kind == "section":
            under_section = True
            blocks.append({
                "kind": "section",
                "id": obj.pk,
                "version": obj.version,
                "run": run_of(obj),
                "anchor": f"n-section-{obj.pk}",
                "label": label,
                "name": obj.name,
                "depth": depth,
                "needs_review": obj.needs_review,
                "review_note": obj.review_note,
                "linked_from": data.incoming.get(("section", obj.pk), []),
            })
            blocks.extend(_note_block(n, data) | {"depth": depth, "indent": True}
                          for n in data.notes_by.get(("section", obj.pk), []))
        else:
            blocks.append(_item_block(obj, data, fmts, label, depth, under_section))
    blocks.extend(_note_block(n, data) | {"depth": depth, "indent": False} for n in data.notes_by.get(key, []))
    return blocks


def _heading(kind, obj, label, depth, data):
    # No "run": headings are alphabetical and have no drag or Up/Down controls.
    run = ""
    return {"kind": "heading", "level": kind, "id": obj.pk, "version": obj.version, "run": run,
            "anchor": f"n-{kind}-{obj.pk}", "label": label, "name": obj.name, "depth": depth,
            "linked_from": data.incoming.get((kind, obj.pk), [])}


def _subtopic_blocks(sub, label, data, fmts, depth):
    return [_heading("subtopic", sub, label, depth, data)] + _container_blocks(("subtopic", sub.pk), depth, data, fmts)


def _topic_blocks(topic, label, data, fmts, depth):
    blocks = [_heading("topic", topic, label, depth, data)] + _container_blocks(("topic", topic.pk), depth, data, fmts)
    subs = data.subtopics_by.get(("topic", topic.pk), [])
    for sub, sub_label in zip(subs, numbering.number_siblings(len(subs), fmts["subtopic_format"])):
        blocks.extend(_subtopic_blocks(sub, sub_label, data, fmts, depth + 1))
    return blocks


def build_reading(subject, user, scope="subject", target=None):
    """Return the context for the reading page.

    scope is "subject", "topic" or "subtopic"; target is the Topic or Sub-topic shown.
    """
    fmts = formats_for(user)
    data = _Data(subject)
    topic_labels = dict(zip((t.pk for t in data.topics), numbering.number_siblings(len(data.topics), fmts["topic_format"])))
    direct = data.subtopics_by.get(("subject", subject.pk), [])
    direct_labels = dict(zip((s.pk for s in direct), numbering.number_siblings(len(direct), fmts["subtopic_format"])))

    toc = []
    for topic in data.topics:
        subs = data.subtopics_by.get(("topic", topic.pk), [])
        toc.append({
            "topic": topic,
            "label": topic_labels[topic.pk],
            "subtopics": [
                {"subtopic": s, "label": lab}
                for s, lab in zip(subs, numbering.number_siblings(len(subs), fmts["subtopic_format"]))
            ],
        })
    direct_toc = [{"subtopic": s, "label": direct_labels[s.pk]} for s in direct]

    if scope == "subject":
        blocks = [_heading("subject", subject, "", 0, data)] + _container_blocks(("subject", subject.pk), 0, data, fmts)
        for topic in data.topics:
            blocks.extend(_topic_blocks(topic, topic_labels[topic.pk], data, fmts, 1))
        for sub in direct:
            blocks.extend(_subtopic_blocks(sub, direct_labels[sub.pk], data, fmts, 1))
    elif scope == "topic":
        blocks = _topic_blocks(target, topic_labels[target.pk], data, fmts, 1)
    else:
        if target.topic_id:
            siblings = data.subtopics_by.get(("topic", target.topic_id), [])
        else:
            siblings = direct
        labels = dict(zip((s.pk for s in siblings), numbering.number_siblings(len(siblings), fmts["subtopic_format"])))
        blocks = _subtopic_blocks(target, labels[target.pk], data, fmts, 1)
    return {"blocks": blocks, "toc": toc, "direct_toc": direct_toc}
