"""Database side of the Word import: refuses unsafe states, imports in one transaction, reads back.

Everything works inside ONE profile. Parents are set from objects already held (no extra query per
save, docs/DESIGN.md P15).
"""
import re
from collections import Counter
from html import unescape

from django.db import transaction

from diary.models import Item, Section, Subject, Subtopic, Topic, VersionHistory
from diary.richtext import sanitise_html

from .plan import ITEM, SECTION, SUBJECT, SUBTOPIC, TOPIC

MODELS = {SUBJECT: Subject, TOPIC: Topic, SUBTOPIC: Subtopic, SECTION: Section, ITEM: Item}
STATE_FRESH = "fresh"
STATE_DONE = "already imported"
STATE_BLOCKED = "blocked"


class ImportRefused(Exception):
    """The import was not started, or was rolled back. Nothing in the database changed."""


def exact_text(html):
    """Item Text as typed: tags removed, entities decoded, spaces untouched (plain_text trims lines)."""
    return unescape(re.sub(r"<[^>]+>", "", sanitise_html(html)))


def _refs(profile):
    found = {}
    for kind, model in MODELS.items():
        for ref in model.objects.filter(profile=profile).exclude(import_ref="").values_list("import_ref", flat=True):
            found[ref] = kind
    return found


def check_state(plan, profile):
    """(state, messages): is it safe to import ``plan`` into ``profile``?"""
    if plan.problems:
        return STATE_BLOCKED, ["The file has problems (see the dry run); nothing can be imported."] + plan.problems
    planned = {n.ref for n in plan.nodes}
    present = set(_refs(profile))
    if present and present >= planned:
        return STATE_DONE, ["This file is already imported into this profile; nothing would change."]
    if present:
        return STATE_BLOCKED, [
            f"This profile already holds {len(present & planned)} records from a Word import and "
            f"{len(planned - present)} are missing. An incomplete earlier import needs the Admin to look at it; "
            "nothing was changed."
        ]
    names = {n.name.lower() for n in plan.of(SUBJECT)}
    clash = sorted(
        s for s in Subject.objects.filter(profile=profile, deleted_at__isnull=True).values_list("name", flat=True)
        if s.lower() in names
    )
    if clash:
        return STATE_BLOCKED, [
            "These Subjects already exist in this profile, so the import would clash with them: " + ", ".join(clash)
            + ". Remove the sample data (python manage.py remove_sample_data) or choose another profile."
        ]
    return STATE_FRESH, ["Ready to import."]


def _snapshot(obj):
    data = {}
    for field in obj._meta.concrete_fields:
        value = getattr(obj, field.attname)
        data[field.attname] = value if value is None or isinstance(value, (bool, int, str)) else str(value)
    return data


@transaction.atomic
def import_plan(plan, profile, user=None):
    """Create every record of ``plan`` in ``profile``, all or nothing. Returns the number created."""
    state, messages = check_state(plan, profile)
    if state != STATE_FRESH:
        raise ImportRefused(" ".join(messages))
    made = {}
    created = []
    common = {"profile": profile, "created_by": user, "updated_by": user}
    for node in plan.nodes:
        extra = {"original_line": node.original_line, "import_ref": node.ref, "position": node.position}
        parent = made.get(id(node.parent)) if node.parent is not None else None
        if node.kind == SUBJECT:
            if node.other_subject:
                extra.update(show_on_landing=False, other_acts_position=node.other_position,
                             position=plan_main_count(plan) + node.other_position)
            else:
                extra.update(landing_position=node.landing_position)
            obj = Subject(name=node.name, **extra, **common)
        elif node.kind == TOPIC:
            obj = Topic(subject=parent, name=node.name, **extra, **common)
        elif node.kind == SUBTOPIC:
            parent_field = "subject" if parent.__class__ is Subject else "topic"
            obj = Subtopic(name=node.name, **{parent_field: parent}, **extra, **common)
        else:
            parent_field = {Subject: "subject", Topic: "topic", Subtopic: "subtopic"}[parent.__class__]
            if node.kind == SECTION:
                obj = Section(name=node.name, needs_review=True, review_note=node.review_note,
                              **{parent_field: parent}, **extra, **common)
            else:
                obj = Item(text=node.text_html, citation=node.citation, needs_review=node.needs_review,
                           review_note=node.review_note, **{parent_field: parent}, **extra, **common)
        obj.save()
        made[id(node)] = obj
        created.append(obj)
    VersionHistory.objects.bulk_create(
        [
            VersionHistory(record_type=type(o).__name__.lower(), record_id=o.pk, version=o.version,
                           snapshot=_snapshot(o), changed_by=user, profile=profile, change_kind="import")
            for o in created
        ],
        batch_size=500,
    )
    return len(created)


def plan_main_count(plan):
    return sum(1 for n in plan.nodes if n.kind == SUBJECT and not n.other_subject)


def _subject_of(obj, topics, subtopics):
    """Id of the Subject that owns a Topic, Sub-topic, Section or Item (no further queries)."""
    if isinstance(obj, (Topic,)):
        return obj.subject_id
    if isinstance(obj, Subtopic):
        return obj.subject_id or topics[obj.topic_id].subject_id
    if obj.subtopic_id:
        return _subject_of(subtopics[obj.subtopic_id], topics, subtopics)
    if obj.topic_id:
        return topics[obj.topic_id].subject_id
    return obj.subject_id


def read_back(profile):
    """What the database now holds for the imported records of ``profile`` (live and deleted)."""
    subjects = {s.pk: s for s in Subject.objects.filter(profile=profile).exclude(import_ref="")}
    topics = {t.pk: t for t in Topic.objects.filter(profile=profile).exclude(import_ref="")}
    subtopics = {s.pk: s for s in Subtopic.objects.filter(profile=profile).exclude(import_ref="")}
    sections = list(Section.objects.filter(profile=profile).exclude(import_ref=""))
    items = list(Item.objects.filter(profile=profile).exclude(import_ref=""))

    rows = {}
    per_subject = {}

    def bump(subject_id, key):
        per_subject.setdefault(subjects[subject_id].import_ref, Counter())[key] += 1

    for s in subjects.values():
        rows[s.import_ref] = dict(kind=SUBJECT, rebuilt=s.name, original_line=s.original_line, name=s.name,
                                  needs_review=False, review_note="")
        per_subject.setdefault(s.import_ref, Counter())
    for t in topics.values():
        rows[t.import_ref] = dict(kind=TOPIC, rebuilt=t.name, original_line=t.original_line, name=t.name,
                                  needs_review=False, review_note="")
        bump(t.subject_id, "topics")
    for s in subtopics.values():
        rows[s.import_ref] = dict(kind=SUBTOPIC, rebuilt=s.name, original_line=s.original_line, name=s.name,
                                  needs_review=False, review_note="")
        bump(_subject_of(s, topics, subtopics), "subtopics")
    for s in sections:
        rows[s.import_ref] = dict(kind=SECTION, rebuilt=s.name, original_line=s.original_line, name=s.name,
                                  needs_review=s.needs_review, review_note=s.review_note)
        bump(_subject_of(s, topics, subtopics), "sections")
    for i in items:
        rebuilt = exact_text(i.text) + (f" - {i.citation}" if i.citation else "")
        rows[i.import_ref] = dict(kind=ITEM, rebuilt=rebuilt, original_line=i.original_line, name="",
                                  needs_review=i.needs_review, review_note=i.review_note)
        bump(_subject_of(i, topics, subtopics), "items")
        if i.needs_review:
            bump(_subject_of(i, topics, subtopics), "flagged")

    main = sorted((s for s in subjects.values() if s.show_on_landing), key=lambda s: (s.landing_position, s.pk))
    other = sorted((s for s in subjects.values() if not s.show_on_landing), key=lambda s: (s.other_acts_position, s.pk))
    order = []
    for subject in main + other:
        _walk(subject, order, topics, subtopics, sections, items)

    groups = []
    for section in sorted(sections, key=lambda s: (s.import_ref)):
        siblings = [
            (o.position, o.pk, o.__class__)
            for o in sections + items
            if (o.subject_id, o.topic_id, o.subtopic_id) == (section.subject_id, section.topic_id, section.subtopic_id)
        ]
        siblings.sort()
        count = 0
        for position, _pk, cls in siblings:
            if position <= section.position:
                continue
            if cls is Section:
                break
            count += 1
        groups.append((section.import_ref, section.name, count))

    flagged = [(r, v["kind"], v["review_note"]) for r, v in sorted(rows.items()) if v["needs_review"]]
    counts = {
        "subjects": len(subjects),
        "main_subjects": len(main),
        "other_subjects": len(other),
        "topics": len(topics),
        "subtopics": len(subtopics),
        "sections": len(sections),
        "items": len(items),
        "items_flagged": sum(1 for i in items if i.needs_review),
        "review_marked": len(flagged),
    }
    counts["items_clean"] = counts["items"] - counts["items_flagged"]
    return {"rows": rows, "order": order, "groups": groups, "counts": counts, "per_subject": per_subject,
            "review_list": flagged}


def _walk(subject, order, topics, subtopics, sections, items):
    """Append refs in the order the Diary lists them: Subject, then its Topics, Sub-topics and content."""
    order.append(subject.import_ref)

    def content(**parent):
        key = (parent.get("subject"), parent.get("topic"), parent.get("subtopic"))
        rows = [o for o in sections + items if (o.subject_id, o.topic_id, o.subtopic_id) == key]
        for o in sorted(rows, key=lambda o: (o.position, o.pk)):
            order.append(o.import_ref)

    def subs(**parent):
        match = [s for s in subtopics.values()
                 if (s.subject_id, s.topic_id) == (parent.get("subject"), parent.get("topic"))]
        for s in sorted(match, key=lambda s: (s.position, s.pk)):
            order.append(s.import_ref)
            content(subtopic=s.pk)

    content(subject=subject.pk)
    subs(subject=subject.pk)
    for t in sorted((t for t in topics.values() if t.subject_id == subject.pk), key=lambda t: (t.position, t.pk)):
        order.append(t.import_ref)
        content(topic=t.pk)
        subs(topic=t.pk)


__all__ = ["ImportRefused", "check_state", "import_plan", "read_back", "exact_text"]
