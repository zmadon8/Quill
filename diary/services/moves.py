"""Move and reorder (docs/DESIGN.md section 5.4) and the numbering previews for Items and Sections.

Rules: same profile only, one level of nesting, a Subject holds Topics or direct Sub-topics but
not both, a heading cannot go inside itself. Items and Sections share one position
sequence per parent, kept as 1..n among the live siblings.
"""
from django.db import transaction

from ..models import Subtopic, Topic
from ..reading import formats_for
from .core import (
    Ctx,
    check_version,
    descendants,
    get_record,
    label,
    make_result,
    record_type,
)
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

