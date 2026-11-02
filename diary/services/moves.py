"""Move and reorder (docs/DESIGN.md section 5.4) and the numbering previews for Items and Sections.

Rules: same profile only, one level of nesting, a Subject holds Topics or direct Sub-topics but
not both, a heading cannot go inside itself. Items and Sections share one position
sequence per parent, kept as 1..n among the live siblings.
"""
import contextlib

from django.db import transaction
from django.db.models.functions import Lower

from ..models import Subtopic, Topic
from ..reading import formats_for
from .core import (
    Ctx,
    check_version,
    descendants,
    get_record,
    label,
    make_result,
    parent_of,
    record_type,
)
from . import core
from . import housing
from .errors import Refused
from ..sorting import sort_headings
from .sequences import ident, is_alphabetical, labels, lock_sequence, members, normalize, place, sequence_key

ALLOWED_PARENTS = {
    "topic": ("subject",),
    "subtopic": ("topic", "subject"),
    "section": ("subject", "topic", "subtopic"),
    "item": ("subject", "topic", "subtopic"),
    "note": ("subject", "topic", "subtopic", "item", "section"),
    "case": ("item",),
}

NICE = {
    "subject": "Subject", "topic": "Topic", "subtopic": "Sub-topic", "section": "Section",
    "item": "Item", "case": "Case", "note": "Note", "notelink": "Note link",
}

PARENT_COLUMNS = ("subject", "topic", "subtopic", "item", "section", "note")


def refuse_heading_reorder(obj):
    """Subjects, Topics and Sub-topics are always alphabetical: refuse to put one at a chosen place."""
    kind = record_type(obj)
    if kind in ("subject", "topic", "subtopic"):
        raise Refused(
            f"{NICE[kind]}s are always listed alphabetically, so they cannot be reordered. "
            "Rename it to change where it falls, or move it to another parent."
        )


def parent_column(child_kind, parent_kind):
    return parent_kind


def check_heading_mix(subject, wanted):
    """A Subject holds Topics or direct Sub-topics, not both (section 2.1)."""
    if wanted == "topic" and Subtopic._base_manager.filter(
        subject=subject, deleted_at__isnull=True, profile_id=subject.profile_id
    ).exists():
        raise Refused(
            f"{subject.name!r} holds Sub-topics directly, so it cannot also hold Topics. "
            "A Subject holds Topics or Sub-topics, not both."
        )
    if wanted == "subtopic" and Topic._base_manager.filter(
        subject=subject, deleted_at__isnull=True, profile_id=subject.profile_id
    ).exists():
        raise Refused(
            f"{subject.name!r} holds Topics, so it cannot also hold Sub-topics directly. "
            "A Subject holds Topics or Sub-topics, not both."
        )


def check_move_allowed(obj, parent_kind, parent):
    """Raise Refused (with the reason) unless ``obj`` may sit under ``parent``."""
    kind = record_type(obj)
    if kind not in ALLOWED_PARENTS:
        raise Refused(f"A {NICE[kind]} cannot be moved.")
    if parent_kind not in ALLOWED_PARENTS[kind]:
        raise Refused(f"A {NICE[kind]} cannot be placed under a {NICE.get(parent_kind, parent_kind)}.")
    if parent.deleted_at is not None:
        raise Refused("The new place is in the Trash.")
    if parent.profile_id != obj.profile_id:
        raise Refused("Records can only be moved inside their own profile.")
    if (parent_kind, parent.pk) == (kind, obj.pk):
        raise Refused(f"A {NICE[kind]} cannot be placed inside itself.")
    if obj.pk is not None and kind in ("topic", "subtopic", "item") and (parent_kind, parent.pk) in {
        ident(d) for d in descendants(obj)
    }:
        raise Refused(f"A {NICE[kind]} cannot be placed inside something that sits beneath it.")
    if kind == "topic":
        check_heading_mix(parent, "topic")
    if kind == "subtopic" and parent_kind == "subject":
        check_heading_mix(parent, "subtopic")


def _target(ctx, obj, parent, lock=True):
    """Resolve ``parent`` ((type, id) or None). Returns the parent record, or None meaning 'same parent'."""
    if parent is None:
        return None
    parent_kind, parent_id = parent
    target = get_record(ctx, parent_kind, parent_id, lock=lock)
    column = parent_column(record_type(obj), parent_kind)
    if getattr(obj, f"{column}_id", None) == target.pk and column in _own_columns(obj):
        return None
    return target


def _own_columns(obj):
    return [c for c in PARENT_COLUMNS if hasattr(obj, f"{c}_id") and getattr(obj, f"{c}_id") is not None]


def _plan_index(items, obj, index):
    """(current index, wanted index) of ``obj`` within its own sequence."""
    ids = [ident(m) for m in items]
    current = ids.index(ident(obj)) if ident(obj) in ids else None
    others = len(items) - (1 if current is not None else 0)
    wanted = others if index is None else max(0, min(int(index), others))
    return current, wanted


def move(profile, user, kind, record_id, parent=None, index=None, expected_version=None):
    """Move a record to ``parent`` ((type, id); None = keep its parent) at 0-based ``index`` (None = last).

    Repeating a move that is already done changes nothing. A move to a different parent is change
    kind 'move'; inside the same parent it is 'reorder'.
    """
    ctx = Ctx(profile, user)
    with transaction.atomic():
        obj = get_record(ctx, kind, record_id)
        if kind not in ALLOWED_PARENTS and kind != "subject":
            raise Refused(f"A {NICE.get(kind, kind)} cannot be moved.")
        if kind == "subject" and parent is not None:
            raise Refused("A Subject cannot be placed under anything.")
        old_key = sequence_key(obj)
        if kind in housing.HOUSED and parent is not None and (parent[0], int(parent[1])) != (
            "subject", getattr(obj, "subject_id", None)
        ):
            parent = housing.house_parent(ctx, parent)  # under a Subject: into its Topic "1" (D61)
        target = _target(ctx, obj, parent)
        if target is None:
            if parent is not None and is_alphabetical(old_key):
                return make_result(ctx, obj)  # "move" to the parent it already has: nothing to do
            refuse_heading_reorder(obj)
            lock_sequence(ctx, old_key)
            current, wanted = _plan_index(members(ctx.profile_id, old_key), obj, index)
            if current == wanted:
                return make_result(ctx, obj)
            check_version(obj, expected_version)
            place(ctx, obj, old_key, wanted, "reorder")
            return make_result(ctx, obj)
        check_version(obj, expected_version)
        check_move_allowed(obj, parent[0], target)
        for column in PARENT_COLUMNS:
            if hasattr(obj, f"{column}_id"):
                setattr(obj, f"{column}_id", None)
        setattr(obj, f"{parent_column(kind, parent[0])}_id", target.pk)
        new_key = sequence_key(obj)
        lock_sequence(ctx, old_key)
        lock_sequence(ctx, new_key)
        place(ctx, obj, new_key, index, "move")
        normalize(ctx, old_key)
        return make_result(ctx, obj)


def shift(profile, user, kind, record_id, delta, expected_version=None):
    """Move up (negative ``delta``) or down by that many places inside the same parent; clamps at the ends."""
    ctx = Ctx(profile, user)
    with transaction.atomic():
        obj = get_record(ctx, kind, record_id)
        refuse_heading_reorder(obj)
        key = sequence_key(obj)
        if key is None:
            raise Refused(f"A {NICE.get(kind, kind)} has no position.")
        lock_sequence(ctx, key)
        ordered = members(ctx.profile_id, key)
        current = [ident(m) for m in ordered].index(ident(obj))
        wanted = max(0, min(len(ordered) - 1, current + int(delta)))
        return move(profile, user, kind, record_id, None, wanted, expected_version)


# ------------------------------------------------------------------ numbering previews

def _changes(before, after, objs):
    rows = []
    for key, new in after.items():
        old = before.get(key)
        if old is not None and old != new:
            rows.append({"type": key[0], "id": key[1], "label": label(objs[key]), "before": old, "after": new})
    return rows


def preview_move(profile, user, kind, record_id, parent=None, index=None):
    """Read-only: the records whose generated numbers would change if this move were made.

    Returns ``{"changes": [{type, id, label, before, after}, ...]}``. Raises Refused when the move
    is not allowed, with the reason.
    """
    ctx = Ctx(profile, user)
    fmts = formats_for(user)
    obj = get_record(ctx, kind, record_id, lock=False)
    old_key = sequence_key(obj)
    if old_key is None:
        raise Refused(f"A {NICE.get(kind, kind)} has no position.")
    if kind in housing.HOUSED and parent is not None and (parent[0], int(parent[1])) != (
        "subject", getattr(obj, "subject_id", None)
    ):
        parent = housing.house_parent(ctx, parent, create=False)  # a preview never writes: Topic "1" only if it exists
    target = _target(ctx, obj, parent, lock=False)
    old_members = members(ctx.profile_id, old_key)
    objs = {ident(m): m for m in old_members}
    objs[ident(obj)] = obj
    before = labels(old_key, old_members, fmts)
    if target is None:
        if parent is not None and is_alphabetical(old_key):
            return {"changes": []}
        refuse_heading_reorder(obj)
        others = [m for m in old_members if ident(m) != ident(obj)]
        at = len(others) if index is None else max(0, min(int(index), len(others)))
        after = labels(old_key, others[:at] + [obj] + others[at:], fmts)
        return {"changes": _changes(before, after, objs)}
    check_move_allowed(obj, parent[0], target)
    moved = type(obj)(**{f.attname: getattr(obj, f.attname) for f in obj._meta.concrete_fields})
    for column in PARENT_COLUMNS:
        if hasattr(moved, f"{column}_id"):
            setattr(moved, f"{column}_id", None)
    setattr(moved, f"{parent_column(kind, parent[0])}_id", target.pk)
    new_key = sequence_key(moved)
    new_members = members(ctx.profile_id, new_key)
    objs.update({ident(m): m for m in new_members})
    before.update(labels(new_key, new_members, fmts))
    after = labels(old_key, [m for m in old_members if ident(m) != ident(obj)], fmts)
    at = len(new_members) if index is None else max(0, min(int(index), len(new_members)))
    if is_alphabetical(new_key):
        after.update(labels(new_key, sort_headings(new_members + [moved]), fmts))
    else:
        after.update(labels(new_key, new_members[:at] + [obj] + new_members[at:], fmts))
    return {"changes": _changes(before, after, objs)}


def preview_delete(profile, user, kind, record_id):
    """Read-only: what deleting a record would renumber, and how many records would go to Trash."""
    ctx = Ctx(profile, user)
    fmts = formats_for(user)
    obj = get_record(ctx, kind, record_id, lock=False)
    key = sequence_key(obj)
    below = descendants(obj, live_only=True)
    if key is None:
        return {"changes": [], "count": 1 + len(below)}
    current = members(ctx.profile_id, key)
    objs = {ident(m): m for m in current}
    before = labels(key, current, fmts)
    after = labels(key, [m for m in current if ident(m) != ident(obj)], fmts)
    return {"changes": _changes(before, after, objs), "count": 1 + len(below)}



# ------------------------------------------------------------------ move to a new heading (round 11)

#: Which kinds of record are offered "New Topic in this Subject" / "New Sub-topic in this Topic" in the Move to picker.
NEW_TOPIC_FOR = ("item", "section", "subtopic")
NEW_SUBTOPIC_FOR = ("item", "section")


def _place_of(obj):
    """(Subject, Topic or None) the record sits in now, found by walking up its parents."""
    subject = topic = None
    rec = obj
    while rec is not None:
        found = parent_of(rec)
        if found is None:
            break
        kind, rec = found
        if kind == "subject":
            subject = rec
        elif kind == "topic":
            topic = rec
    return subject, topic


def new_heading_options(profile, user, obj):
    """The new headings the Move to picker offers for ``obj``: a list of dicts {kind, parent_kind, parent, label}.

    "New Topic in this Subject" (Items, Sections and Sub-topics inside a Topic) is not offered when the Subject holds
    Sub-topics directly (a Subject holds Topics or Sub-topics, not both). "New Sub-topic in this Topic" (Items and
    Sections only) is offered only when the record sits in a Topic (directly or through a Sub-topic). Topics get neither.
    """
    kind = record_type(obj)
    subject, topic = _place_of(obj)
    ctx = Ctx(profile, user)
    options = []
    if kind in NEW_TOPIC_FOR and subject is not None and housing.accepts_topics(ctx, subject.pk):
        options.append({"kind": "topic", "parent_kind": "subject", "parent": subject, "label": "New Topic in this Subject"})
    if kind in NEW_SUBTOPIC_FOR and topic is not None:
        options.append({"kind": "subtopic", "parent_kind": "topic", "parent": topic, "label": "New Sub-topic in this Topic"})
    return options


def _new_heading(ctx, obj, new_kind, name):
    """Create the heading (name checked) in the right place; returns it. Raises Refused or ValidationFailed."""
    from .errors import ValidationFailed
    from .records import create

    wanted = {o["kind"]: o for o in new_heading_options(ctx.profile, ctx.user, obj)}
    if new_kind not in wanted:
        raise Refused(f"A new {NICE.get(new_kind, new_kind)} is not offered for this {NICE[record_type(obj)]}.")
    option = wanted[new_kind]
    name = core.clean_name(name)
    model = Topic if new_kind == "topic" else Subtopic
    column = f"{option['parent_kind']}_id"
    clash = (
        model._base_manager.filter(profile_id=ctx.profile_id, deleted_at__isnull=True, **{column: option["parent"].pk})
        .annotate(lowered=Lower("name"))
        .filter(lowered=name.lower())
        .exists()
    )
    if clash:
        raise ValidationFailed(f"A {NICE[new_kind]} called {name!r} already exists in {option['parent'].name!r}.")
    return create(ctx.profile, ctx.user, new_kind, parent=(option["parent_kind"], option["parent"].pk), name=name).record


def move_to_new_heading(profile, user, kind, record_id, new_kind, name, expected_version=None):
    """Make a new Topic (in the record's Subject) or Sub-topic (in its Topic) and move the record into it, as ONE Undo step."""
    cm = contextlib.nullcontext() if core._shared_group.get() else core.action_group()
    with cm, transaction.atomic():
        ctx = Ctx(profile, user)
        obj = get_record(ctx, kind, record_id)
        check_version(obj, expected_version)
        heading = _new_heading(ctx, obj, new_kind, name)
        result = move(profile, user, kind, record_id, (new_kind, heading.pk), None, expected_version)
        result.info["heading"] = heading
        return result


def preview_move_to_new_heading(profile, user, kind, record_id, new_kind, name):
    """Read-only: the numbers that change if the record moved into a new heading of this name (nothing is kept)."""
    ctx = Ctx(profile, user)
    fmts = formats_for(user)
    # NOTE: this really creates the heading and rolls it back, so ``create`` must only have
    # side effects that a database rollback undoes (no files, caches or signals).
    with transaction.atomic():
        savepoint = transaction.savepoint()
        try:
            obj = get_record(ctx, kind, record_id, lock=False)
            heading = _new_heading(ctx, obj, new_kind, name)
            key = sequence_key(heading)
            current = members(ctx.profile_id, key)
            others = [m for m in current if ident(m) != ident(heading)]
            objs = {ident(m): m for m in current}
            changes = _changes(labels(key, others, fmts), labels(key, current, fmts), objs)
            changes += preview_move(profile, user, kind, record_id, (new_kind, heading.pk))["changes"]
            return {"changes": changes, "heading": heading.name}
        finally:
            transaction.savepoint_rollback(savepoint)
