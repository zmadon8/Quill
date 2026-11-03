"""Promote and demote: change the level of a heading or Section (one step up or down the tree).

    promote:  Section -> Sub-topic -> Topic -> Subject
    demote:   Subject -> Topic -> Sub-topic -> Section

There is no "change type" in the data (each level is its own table), so a change of level makes the new record,
moves everything that was inside the old one into it and sends the old one to the Trash. All of it is ONE Undo step
(the same shape as ``moves.move_to_new_heading``) and all-or-nothing: any refusal rolls the whole change back.

What happens to what is inside (the rules the confirmation page shows):

* Section -> Sub-topic: the Items that follow the Section (up to the next Section) go into the new Sub-topic, which
  sits where the Section's own Topic or Sub-topic sits (a Section inside a Sub-topic makes a sibling Sub-topic).
* Sub-topic -> Topic: the new Topic is in the same Subject; Sections, Items and Notes go with it.
* Topic -> Subject: its Sub-topics become Topics of the new Subject; its own Items and Sections are housed in the new
  Subject's Topic "1" (docs/DESIGN.md D61).
* Sub-topic -> Section: the Section is added at the end of the list of the Topic (or Subject) the Sub-topic was in, and
  the Sub-topic's Items follow it. Its own Sections stay Sections beside it (a Section cannot hold a Section).
* Topic -> Sub-topic (the Editor chooses the Topic it goes under): its Sub-topics become Sections.
* Subject -> Topic (the Editor chooses the Subject it goes under): its Topics become Sub-topics and their Sub-topics
  become Sections. A Topic "1" (only a holder for loose Items) is dissolved into the new Topic instead.

Notes on the old record move to the new one, and links from other Notes are pointed at the new record. Section
"For review" marks cannot be kept by a Sub-topic (it has none); the confirmation page says so.
"""
import contextlib

from django.db import transaction

from ..models import NoteLink, Section, Subject, Topic
from . import core, housing
from .core import Ctx, descendants, get_record, label, record_type
from .errors import Refused
from .links import retarget_link
from .moves import NICE
from .records import create
from .sequences import members
from .trash import delete

PROMOTE_TO = {"section": "subtopic", "subtopic": "topic", "topic": "subject"}
DEMOTE_TO = {"subject": "topic", "topic": "subtopic", "subtopic": "section"}
#: Demoting these needs a place to go: the kind of record the Editor must choose.
NEEDS_TARGET = {"subject": "subject", "topic": "topic"}


def can_promote(kind):
    return kind in PROMOTE_TO


def can_demote(kind):
    return kind in DEMOTE_TO


# ------------------------------------------------------------------ small helpers

def _own_container(obj):
    """(column, id) of the Subject, Topic or Sub-topic a Section sits in."""
    for column in ("subtopic", "topic", "subject"):
        pk = getattr(obj, f"{column}_id", None)
        if pk:
            return column, pk
    raise Refused("That Section has no place.")


def _run(ctx, kind, obj):
    """The live Items and Sections directly inside a Subject, Topic or Sub-topic, in order."""
    return members(ctx.profile_id, ("run", kind, obj.pk))


def _notes(ctx, kind, obj):
    return members(ctx.profile_id, ("note", kind, obj.pk))


def _move_all(profile, user, records, parent):
    from .moves import move

    for rec in records:
        move(profile, user, record_type(rec), rec.pk, parent)


def _move_content(ctx, kind, old, parent, run=None):
    """Move the Items/Sections (``run``, default all of them) and the Notes of ``old`` into ``parent`` ((type, id))."""
    profile, user = ctx.profile, ctx.user
    _move_all(profile, user, run if run is not None else _run(ctx, kind, old), parent)
    _move_all(profile, user, _notes(ctx, kind, old), parent)


def _retarget(ctx, kind, old, new_kind, new):
    """Point every link (live or in Trash) that ends at ``old`` at ``new`` instead."""
    column = f"{kind}_id"
    for link in NoteLink._base_manager.filter(profile_id=ctx.profile_id, **{column: old.pk}):
        retarget_link(ctx.profile, ctx.user, link.pk, (new_kind, new.pk))


def _finish(ctx, kind, old, new_kind, new):
    _retarget(ctx, kind, old, new_kind, new)
    delete(ctx.profile, ctx.user, kind, old.pk)


def _actual_parent(obj):
    """("subject"|"topic"|"subtopic", id) of a Section just made (it may have been housed in a Topic "1")."""
    return _own_container(obj)


@contextlib.contextmanager
def _one_step():
    cm = contextlib.nullcontext() if core._shared_group.get() else core.action_group()
    with cm, transaction.atomic():
        yield


# ------------------------------------------------------------------ the single steps

def _promote_section(ctx, section):
    column, pk = _own_container(section)
    name = (section.name or "").strip()
    if not name:
        raise Refused("This Section has no name, so it cannot become a Sub-topic. Give it a name first.")
    container = get_record(ctx, column, pk)
    if column == "subtopic":
        parent = ("topic", container.topic_id) if container.topic_id else ("subject", container.subject_id)
    else:
        parent = (column, pk)
    ordered = _run(ctx, column, container)
    ids = [(record_type(m), m.pk) for m in ordered]
    start = ids.index(("section", section.pk))
    following = []
    for rec in ordered[start + 1:]:
        if isinstance(rec, Section):
            break
        following.append(rec)
    new = create(ctx.profile, ctx.user, "subtopic", parent=parent, name=name).record
    _move_all(ctx.profile, ctx.user, following, ("subtopic", new.pk))
    _move_all(ctx.profile, ctx.user, _notes(ctx, "section", section), ("subtopic", new.pk))
    _finish(ctx, "section", section, "subtopic", new)
    return "subtopic", new


def _promote_subtopic(ctx, sub, subject_id):
    """Make a Topic called like ``sub`` in the Subject ``subject_id`` and move everything into it."""
    new = create(ctx.profile, ctx.user, "topic", parent=("subject", subject_id), name=sub.name).record
    _move_content(ctx, "subtopic", sub, ("topic", new.pk))
    _finish(ctx, "subtopic", sub, "topic", new)
    return "topic", new


def _promote_topic(ctx, topic):
    old_subject = get_record(ctx, "subject", topic.subject_id, lock=False)
    new = create(ctx.profile, ctx.user, "subject", name=topic.name, show_on_landing=old_subject.show_on_landing).record
    for sub in members(ctx.profile_id, ("subtopic", "topic", topic.pk)):
        _promote_subtopic(ctx, sub, new.pk)
    # Loose Items and Sections: moving them under a Subject houses them in its Topic "1" (made when needed).
    _move_all(ctx.profile, ctx.user, _run(ctx, "topic", topic), ("subject", new.pk))
    _move_all(ctx.profile, ctx.user, _notes(ctx, "topic", topic), ("subject", new.pk))
    _finish(ctx, "topic", topic, "subject", new)
    return "subject", new


def _demote_subtopic(ctx, sub, container=None):
    """Make a Section called like ``sub`` at the end of ``container`` ((type, id); default: where ``sub`` sits)."""
    if container is None:
        container = ("topic", sub.topic_id) if sub.topic_id else ("subject", sub.subject_id)
    section = create(ctx.profile, ctx.user, "section", parent=container, name=sub.name).record
    where = _actual_parent(section)
    _move_all(ctx.profile, ctx.user, _run(ctx, "subtopic", sub), where)
    _move_all(ctx.profile, ctx.user, _notes(ctx, "subtopic", sub), ("section", section.pk))
    _finish(ctx, "subtopic", sub, "section", section)
    return "section", section


def _demote_topic(ctx, topic, parent_topic_id):
    """Make a Sub-topic called like ``topic`` under the Topic ``parent_topic_id``; its Sub-topics become Sections."""
    new = create(ctx.profile, ctx.user, "subtopic", parent=("topic", parent_topic_id), name=topic.name).record
    here = ("subtopic", new.pk)
    _move_all(ctx.profile, ctx.user, _run(ctx, "topic", topic), here)
    _move_all(ctx.profile, ctx.user, _notes(ctx, "topic", topic), here)
    for sub in members(ctx.profile_id, ("subtopic", "topic", topic.pk)):
        _demote_subtopic(ctx, sub, here)
    _finish(ctx, "topic", topic, "subtopic", new)
    return "subtopic", new


def _demote_subject(ctx, subject, target_subject_id):
    """Make a Topic called like ``subject`` in the Subject ``target_subject_id``; its Topics become Sub-topics."""
    new = create(ctx.profile, ctx.user, "topic", parent=("subject", target_subject_id), name=subject.name).record
    here = ("topic", new.pk)
    for topic in members(ctx.profile_id, ("topic", "subject", subject.pk)):
        if topic.name.strip().lower() == housing.TOPIC_ONE:
            # Topic "1" only holds loose Items: dissolve it into the new Topic.
            _move_all(ctx.profile, ctx.user, members(ctx.profile_id, ("subtopic", "topic", topic.pk)), here)
            _move_content(ctx, "topic", topic, here)
            _finish(ctx, "topic", topic, "topic", new)
        else:
            _demote_topic(ctx, topic, new.pk)
    _move_all(ctx.profile, ctx.user, members(ctx.profile_id, ("subtopic", "subject", subject.pk)), here)
    _move_content(ctx, "subject", subject, here)
    _finish(ctx, "subject", subject, "topic", new)
    return "topic", new


# ------------------------------------------------------------------ public entry points

def _load(ctx, kind, record_id, direction, lock=True):
    table = PROMOTE_TO if direction == "promote" else DEMOTE_TO
    if kind not in table:
        what = "promoted" if direction == "promote" else "demoted"
        raise Refused(f"A {NICE.get(kind, kind)} cannot be {what}.")
    return get_record(ctx, kind, record_id, lock=lock)


def targets(profile, user, kind, record_id):
    """For a demote that needs a place: the live records the Editor may choose from, as (id, label), A to Z. Else []."""
    wanted = NEEDS_TARGET.get(kind)
    if wanted is None:
        return []
    from ..sorting import sort_headings

    ctx = Ctx(profile, user)
    obj = get_record(ctx, kind, record_id, lock=False)
    live = {"profile": profile, "deleted_at__isnull": True}
    if wanted == "subject":
        rows = [s for s in sort_headings(Subject.objects.filter(**live)) if s.pk != obj.pk and housing.accepts_topics(ctx, s.pk)]
        return [(s.pk, s.name) for s in rows]
    subjects = {s.pk: s.name for s in Subject.objects.filter(**live)}
    rows = sort_headings(Topic.objects.filter(**live).exclude(pk=obj.pk))
    return [(t.pk, f"{t.name} ({subjects.get(t.subject_id, '')})") for t in rows if t.subject_id in subjects]


def _check_target(ctx, kind, target_id):
    wanted = NEEDS_TARGET[kind]
    if not target_id:
        raise Refused(f"Choose the {NICE[wanted]} it goes under.")
    found = get_record(ctx, wanted, target_id, lock=False)
    return found


def describe(profile, user, kind, record_id, direction, target_id=None):
    """Read-only: what the change would do, for the confirmation page. Raises Refused when it is not allowed.

    Returns {"new_kind", "lines": [...], "warnings": [...]}; nothing is changed.
    """
    ctx = Ctx(profile, user)
    obj = _load(ctx, kind, record_id, direction, lock=False)
    new_kind = (PROMOTE_TO if direction == "promote" else DEMOTE_TO)[kind]
    counts = {}
    for rec in descendants(obj, live_only=True):
        counts[record_type(rec)] = counts.get(record_type(rec), 0) + 1
    lines, warnings = [], []
    lines.append(f"The {NICE[kind]} \u201c{label(obj)}\u201d becomes a {NICE[new_kind]}.")
    if kind == "section":
        if direction == "promote":
            column, pk = _own_container(obj)
            ordered = _run(ctx, column, get_record(ctx, column, pk, lock=False))
            ids = [(record_type(m), m.pk) for m in ordered]
            start = ids.index(("section", obj.pk))
            n = 0
            for rec in ordered[start + 1:]:
                if isinstance(rec, Section):
                    break
                n += 1
            lines.append(f"The {n} Item{'s' if n != 1 else ''} after it (up to the next Section) go into the new Sub-topic.")
            if column == "subtopic":
                lines.append("It is made beside the Sub-topic it sits in now, not inside it.")
            if not (obj.name or "").strip():
                raise Refused("This Section has no name, so it cannot become a Sub-topic. Give it a name first.")
            if obj.needs_review:
                warnings.append("This Section is marked For review. A Sub-topic has no such mark, so the mark is not kept (it stays in the Trash copy and in History).")
    if kind == "subtopic":
        if direction == "promote":
            lines.append("It becomes a Topic in the same Subject. Its Sections, Items and Notes go with it.")
        else:
            lines.append("It becomes a Section at the end of the list in the Topic (or Subject) it is in now, with its Items after it.")
            if counts.get("section"):
                warnings.append("Its own Sections stay Sections, in a row beside the new one.")
    if kind == "topic":
        subs = counts.get("subtopic", 0)
        if direction == "promote":
            lines.append("It becomes a new Subject of its own. " + (f"Its {subs} Sub-topic{'s' if subs != 1 else ''} become Topics of that Subject. " if subs else "")
                         + "Loose Items and Sections go into a Topic called \u201c1\u201d in the new Subject.")
        else:
            lines.append("It goes under the Topic you choose, with its Items, Sections and Notes.")
            if subs:
                warnings.append(f"Its {subs} Sub-topic{'s' if subs != 1 else ''} become Sections (a Sub-topic cannot hold a Sub-topic).")
    if kind == "subject":
        lines.append("It goes into the Subject you choose as a Topic. Its Topics become Sub-topics.")
        if counts.get("subtopic"):
            warnings.append("Sub-topics inside those Topics become Sections (a Sub-topic cannot hold a Sub-topic).")
        lines.append("A Topic called \u201c1\u201d (only a holder for loose Items) is dissolved into the new Topic.")
    if direction == "demote" and kind in NEEDS_TARGET and target_id:
        target = _check_target(ctx, kind, target_id)
        lines.append(f"It goes under \u201c{label(target)}\u201d.")
    total = sum(counts.values())
    if total:
        parts = [f"{n} {NICE[k]}{'s' if n != 1 else ''}" for k, n in sorted(counts.items(), key=lambda kv: kv[0]) if k not in ("case", "notelink")]
        lines.append("Inside it now: " + ", ".join(parts) + ".")
    lines.append("Notes on it move with it, and links from other Notes are pointed at the new one. The old record goes to the Trash; Undo reverses the whole change.")
    return {"new_kind": new_kind, "lines": lines, "warnings": warnings}


def promote(profile, user, kind, record_id, expected_version=None):
    """One level up. Returns (new kind, new record). One Undo step; all or nothing."""
    ctx = Ctx(profile, user)
    with _one_step():
        obj = _load(ctx, kind, record_id, "promote")
        core.check_version(obj, expected_version)
        if kind == "section":
            return _promote_section(ctx, obj)
        if kind == "subtopic":
            subject_id = obj.subject_id or get_record(ctx, "topic", obj.topic_id, lock=False).subject_id
            return _promote_subtopic(ctx, obj, subject_id)
        return _promote_topic(ctx, obj)


def demote(profile, user, kind, record_id, target_id=None, expected_version=None):
    """One level down. Subjects and Topics need ``target_id`` (the Subject / Topic they go under). Returns (new kind, new record)."""
    ctx = Ctx(profile, user)
    with _one_step():
        obj = _load(ctx, kind, record_id, "demote")
        core.check_version(obj, expected_version)
        if kind == "subtopic":
            return _demote_subtopic(ctx, obj)
        target = _check_target(ctx, kind, target_id)
        if target.pk == obj.pk:
            raise Refused(f"A {NICE[kind]} cannot go under itself.")
        if kind == "topic":
            return _demote_topic(ctx, obj, target.pk)
        return _demote_subject(ctx, obj, target.pk)
