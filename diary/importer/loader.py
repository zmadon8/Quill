"""Database side of the Word import: refuses unsafe states, imports in one transaction, reads back.

Everything works inside ONE profile. Parents are set from objects already held (no extra query per
save, docs/DESIGN.md P15).
"""
import re
from collections import Counter
from html import unescape

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction

from accounts.models import Profile
from diary.models import Case, Item, Note, NoteLink, Section, Subject, Subtopic, Topic, VersionHistory
from diary.richtext import sanitise_html

from .plan import ITEM, SECTION, SUBJECT, SUBTOPIC, TOPIC, html_signature

MODELS = {SUBJECT: Subject, TOPIC: Topic, SUBTOPIC: Subtopic, SECTION: Section, ITEM: Item}
STATE_FRESH = "fresh"
STATE_DONE = "already imported"
STATE_BLOCKED = "blocked"


class ImportRefused(Exception):
    """The import was not started, or was rolled back. Nothing in the database changed."""


def exact_text(html):
    """Item Text as typed: tags removed, entities decoded, spaces untouched (plain_text trims lines)."""
    return unescape(re.sub(r"<[^>]+>", "", sanitise_html(html)))


REMOVE_HINT = (
    "If these are the TEST SAMPLE Subjects, remove them with: python manage.py remove_sample_data --profile "
)
LIVE_MODELS = (
    ("Subjects", Subject), ("Topics", Topic), ("Sub-topics", Subtopic), ("Sections", Section),
    ("Items", Item), ("Cases", Case), ("Notes", Note), ("Note links", NoteLink),
)


def live_records(profile):
    """[(label, count)] of live (not deleted) diary records in ``profile``; they are in the way of an import."""
    found = []
    for label, model in LIVE_MODELS:
        count = model.objects.filter(profile=profile, deleted_at__isnull=True).count()
        if count:
            found.append((label, count))
    return found


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
    in_the_way = live_records(profile)
    if in_the_way:
        subjects = list(
            Subject.objects.filter(profile=profile, deleted_at__isnull=True).order_by("name").values_list("name", flat=True)[:8]
        )
        shown = (" Subjects include: " + ", ".join(subjects) + ".") if subjects else ""
        return STATE_BLOCKED, [
            f"Profile '{profile.name}' already holds live diary records that are not from an import of this file "
            "(" + ", ".join(f"{count} {label}" for label, count in in_the_way) + f").{shown} "
            "The import only runs into a profile with no live diary records, so nothing is merged. "
            + REMOVE_HINT + f"'{profile.name}'. Otherwise choose an empty profile. Nothing was changed."
        ]
    return STATE_FRESH, ["Ready to import."]


def _snapshot(obj):
    data = {}
    for field in obj._meta.concrete_fields:
        value = getattr(obj, field.attname)
        data[field.attname] = value if value is None or isinstance(value, (bool, int, str)) else str(value)
    return data


def import_plan(plan, profile, user=None):
    """Create every record of ``plan`` in ``profile``, all or nothing. Returns the number created.

    The Profile row is locked and the state is checked again inside the lock, so two imports at once
    cannot both pass. A database refusal late in the run is rolled back and reported as ImportRefused.
    """
    try:
        with transaction.atomic():
            Profile.objects.select_for_update().get(pk=profile.pk)
            state, messages = check_state(plan, profile)
            if state != STATE_FRESH:
                raise ImportRefused(" ".join(messages))
            return _create_all(plan, profile, user)
    except (DatabaseError, ValidationError) as exc:
        raise ImportRefused(
            f"The database refused part of the import, so everything was rolled back and nothing was saved. ({exc})"
        ) from exc


def _create_all(plan, profile, user):
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
                obj = Item(text=node.text_html, needs_review=node.needs_review,
                           review_note=node.review_note, **{parent_field: parent}, **extra, **common)
        obj.save()
        made[id(node)] = obj
        created.append(obj)
        if node.kind == ITEM and node.citation:
            # The citation of an Item is its first Case (10d). A line imported whole has no citation, so no Case.
            case = Case(item=obj, citation=node.citation, position=1, **common)
            case.save()
            created.append(case)
    VersionHistory.objects.bulk_create(
        [
            VersionHistory(record_type=type(o).__name__.lower(), record_id=o.pk, version=o.version,
                           snapshot=_snapshot(o), changed_by=user, profile=profile, change_kind="import")
            for o in created
        ],
        batch_size=500,
    )
    return len(made)  # the records of the Word file; the Cases made from split citations come on top


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
    """What the database now holds for the imported records of ``profile``.

    ``order`` follows the STORED positions (the kept Word order), not the alphabetical order the Diary
    shows headings in, so the check that the file's order was saved stays meaningful.

    Only live records are compared; imported records in the Trash are listed apart under ``deleted``.
    """
    def imported(model):
        return model.objects.filter(profile=profile).exclude(import_ref="")

    deleted = sorted(
        ref for model in MODELS.values()
        for ref in imported(model).filter(deleted_at__isnull=False).values_list("import_ref", flat=True)
    )
    # Parents are looked up among all imported records (a live child of a trashed parent must not crash);
    # only live records are compared.
    all_subjects = {s.pk: s for s in imported(Subject)}
    all_topics = {t.pk: t for t in imported(Topic)}
    all_subtopics = {s.pk: s for s in imported(Subtopic)}
    subjects = {k: v for k, v in all_subjects.items() if v.deleted_at is None}
    topics = {k: v for k, v in all_topics.items() if v.deleted_at is None}
    subtopics = {k: v for k, v in all_subtopics.items() if v.deleted_at is None}
    sections = list(imported(Section).filter(deleted_at__isnull=True))
    items = list(imported(Item).filter(deleted_at__isnull=True))
    citations = {}
    for case in Case.objects.filter(
        profile=profile, item__in=[i.pk for i in items], deleted_at__isnull=True
    ).order_by("position", "pk"):
        citations.setdefault(case.item_id, []).append(case.citation)

    rows = {}
    per_subject = {}

    def bump(subject_id, key):
        per_subject.setdefault(all_subjects[subject_id].import_ref, Counter())[key] += 1

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
        bump(_subject_of(s, all_topics, all_subtopics), "subtopics")
    for s in sections:
        rows[s.import_ref] = dict(kind=SECTION, rebuilt=s.name, original_line=s.original_line, name=s.name,
                                  needs_review=s.needs_review, review_note=s.review_note)
        bump(_subject_of(s, all_topics, all_subtopics), "sections")
    for i in items:
        # Item text + " - " + its citations (Cases in order), exactly as the Word line was written.
        joined = "; ".join(citations.get(i.pk, [])) or i.citation
        rebuilt = exact_text(i.text) + (f" - {joined}" if joined else "")
        rows[i.import_ref] = dict(kind=ITEM, rebuilt=rebuilt, original_line=i.original_line, name="",
                                  needs_review=i.needs_review, review_note=i.review_note,
                                  signature=html_signature(i.text))
        bump(_subject_of(i, all_topics, all_subtopics), "items")
        if i.needs_review:
            bump(_subject_of(i, all_topics, all_subtopics), "flagged")

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
        "citations": sum(len(v) for v in citations.values()),
        "review_marked": len(flagged),
    }
    counts["items_clean"] = counts["items"] - counts["items_flagged"]
    return {"rows": rows, "order": order, "groups": groups, "counts": counts, "per_subject": per_subject,
            "review_list": flagged, "deleted": deleted}


def _walk(subject, order, topics, subtopics, sections, items):
    """Append refs in the stored Word order (positions): Subject, then its Topics, Sub-topics and content."""
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
