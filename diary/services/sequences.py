"""Position sequences: which siblings share one run, how they are kept contiguous, and their numbers.

Items, Nested Items and Sections of one parent share ONE sequence (docs/DESIGN.md section 2).
Positions are kept as 1..n among the live siblings; records in Trash keep their old position so
that Restore can put them back where they were.

Subjects, Topics and Sub-topics are the exception (docs/DESIGN.md, "Alphabetical headings"): they are
always shown in alphabetical order (diary/sorting.py), computed here on every read. Their stored
position columns (position, landing_position, other_acts_position) still hold the original Word order
and are never renumbered: a new or moved heading just gets the next free number (above every
sibling, trashed ones included, so Restore cannot duplicate a number), so the Word order
could be switched back on later. Nothing in this module reorders them by hand.
"""
from accounts.models import Profile

from .. import numbering
from ..sorting import sort_headings
from ..models import Case, Item, Note, Section, Subject, Subtopic, Topic
from .core import MODELS, commit, record_type

#: Sequence kinds that are always alphabetical and cannot be reordered by hand.
ALPHABETICAL = ("subject", "topic", "subtopic")


def is_alphabetical(key):
    return key is not None and key[0] in ALPHABETICAL


#: Which record type each parent column of a sequence key refers to.
COLUMN_TYPE = {
    "subject": "subject",
    "topic": "topic",
    "subtopic": "subtopic",
    "section": "section",
    "item": "item",
    "parent_item": "item",
}


def ident(obj):
    return (record_type(obj), obj.pk)


def sequence_key(obj):
    """The sequence ``obj`` sits in, or None for records without a position (Note links)."""
    kind = record_type(obj)
    if kind == "subject":
        return ("subject", "show", bool(obj.show_on_landing))
    if kind == "topic":
        return ("topic", "subject", obj.subject_id)
    if kind == "subtopic":
        column = "topic" if obj.topic_id else "subject"
        return ("subtopic", column, getattr(obj, f"{column}_id"))
    if kind in ("section", "item"):
        if kind == "item" and obj.parent_item_id:
            return ("kids", "parent_item", obj.parent_item_id)
        for column in ("subtopic", "topic", "subject"):
            if getattr(obj, f"{column}_id"):
                return ("run", column, getattr(obj, f"{column}_id"))
    if kind == "note":
        for column in ("item", "section", "subtopic", "topic", "subject"):
            if getattr(obj, f"{column}_id"):
                return ("note", column, getattr(obj, f"{column}_id"))
    if kind == "case":
        return ("case", "item", obj.item_id)
    return None


def pos_attr(obj):
    if record_type(obj) == "subject":
        return "landing_position" if obj.show_on_landing else "other_acts_position"
    return "position"


def get_pos(obj):
    return getattr(obj, pos_attr(obj))


def set_pos(obj, value):
    setattr(obj, pos_attr(obj), value)


def members(profile_id, key):
    """The LIVE records of one sequence in display order."""
    kind, column, value = key
    live = {"profile_id": profile_id, "deleted_at__isnull": True}
    if kind == "subject":
        rows = list(Subject._base_manager.filter(show_on_landing=value, **live))
        return sort_headings(rows)
    if kind == "topic":
        return sort_headings(Topic._base_manager.filter(subject_id=value, **live))
    if kind == "subtopic":
        return sort_headings(Subtopic._base_manager.filter(**{f"{column}_id": value}, **live))
    if kind == "kids":
        rows = Item._base_manager.filter(parent_item_id=value, **live)
    elif kind == "run":
        rows = list(Item._base_manager.filter(**{f"{column}_id": value}, **live)) + list(
            Section._base_manager.filter(**{f"{column}_id": value}, **live)
        )
        return sorted(rows, key=lambda o: (o.position, 0 if isinstance(o, Section) else 1, o.pk))
    elif kind == "note":
        rows = Note._base_manager.filter(**{f"{column}_id": value}, **live)
    elif kind == "case":
        rows = Case._base_manager.filter(item_id=value, **live)
    else:
        return []
    return sorted(rows, key=lambda o: (o.position, o.pk))


def next_stored_position(profile_id, key, exclude=None):
    """The next free stored (Word order) number of an alphabetical sequence.

    Counts ALL siblings, live and trashed, so a number held by a trashed heading is never reissued
    (restoring it later would otherwise duplicate the number). ``exclude`` is an ``ident`` to skip.
    """
    kind, column, value = key
    base = {"profile_id": profile_id}
    if kind == "subject":
        rows = Subject._base_manager.filter(show_on_landing=value, **base)
        field = "landing_position" if value else "other_acts_position"
    elif kind == "topic":
        rows = Topic._base_manager.filter(subject_id=value, **base)
        field = "position"
    else:
        rows = Subtopic._base_manager.filter(**{f"{column}_id": value}, **base)
        field = "position"
    numbers = [
        getattr(r, field) or 0 for r in rows if exclude is None or ident(r) != exclude
    ]
    return max(numbers, default=0) + 1


def lock_sequence(ctx, key):
    """Lock the parent row (or the profile row for Subjects) so two edits cannot interleave."""
    kind, column, value = key
    if kind == "subject":
        Profile.objects.select_for_update().get(pk=ctx.profile_id)
    else:
        MODELS[COLUMN_TYPE[column]]._base_manager.select_for_update().filter(pk=value, profile_id=ctx.profile_id).first()


def place(ctx, obj, key, index=None, kind="reorder"):
    """Put ``obj`` at 0-based ``index`` (None = last) of the live sequence ``key`` and save it.

    ``obj`` is saved with change kind ``kind`` (its parent columns may have been changed by the
    caller first). Siblings whose position changes are saved as 'reorder'. Returns the new index.

    In an alphabetical sequence ``index`` is ignored: the record is saved where the alphabet puts it
    (a record changing parent takes the next free stored position; no sibling is touched) and its
    index among the alphabetical siblings is returned.
    """
    if is_alphabetical(key):
        others = [m for m in members(ctx.profile_id, key) if ident(m) != ident(obj)]
        if kind == "move":
            set_pos(obj, next_stored_position(ctx.profile_id, key, exclude=ident(obj)))
        commit(ctx, obj, kind, check=False)
        return [ident(m) for m in sort_headings(others + [obj])].index(ident(obj))
    others = [m for m in members(ctx.profile_id, key) if ident(m) != ident(obj)]
    at = len(others) if index is None else max(0, min(int(index), len(others)))
    ordered = others[:at] + [obj] + others[at:]
    for number, member in enumerate(ordered, start=1):
        if member is obj:
            set_pos(obj, number)
            commit(ctx, obj, kind, check=False)
        elif get_pos(member) != number:
            set_pos(member, number)
            commit(ctx, member, "reorder", check=False)
    return at


def index_for_position(ctx, key, position):
    """Where a record that used to have ``position`` belongs among the live siblings now.

    Deleting leaves the live siblings' positions alone, so a record restored from Trash goes in front
    of the first live sibling whose position is not lower than its own.
    """
    if is_alphabetical(key):
        return 0  # not used: place() puts a heading where the alphabet says
    return sum(1 for m in members(ctx.profile_id, key) if get_pos(m) < position)


def make_room(ctx, key, index=None):
    """Shift the live siblings to leave a gap for a NEW record at 0-based ``index`` (None = last).

    Returns the position number (1-based) the new record must be saved with.
    """
    others = members(ctx.profile_id, key)
    if is_alphabetical(key):
        return next_stored_position(ctx.profile_id, key)  # next free stored (Word order) number; nothing shifts
    at = len(others) if index is None else max(0, min(int(index), len(others)))
    for i, member in enumerate(others):
        number = i + 1 if i < at else i + 2
        if get_pos(member) != number:
            set_pos(member, number)
            commit(ctx, member, "reorder", check=False)
    return at + 1


def normalize(ctx, key):
    """Make the live positions of one sequence exactly 1..n (history rows only for those that change)."""
    if key is None or is_alphabetical(key):
        return  # stored positions of headings are the kept Word order: never renumbered
    for number, member in enumerate(members(ctx.profile_id, key), start=1):
        if get_pos(member) != number:
            set_pos(member, number)
            commit(ctx, member, "reorder", check=False)


def labels(key, objs, fmts):
    """{(type, pk): generated number} for ``objs`` (the live members, in order) of sequence ``key``."""
    kind = key[0]
    if kind == "run":
        kinds = [
            numbering.SECTION if isinstance(o, Section) else (numbering.NESTED if o.kind == "nested" else numbering.ITEM)
            for o in objs
        ]
        values = numbering.number_children(kinds, fmts["item_format"], fmts["section_format"])
    elif kind == "kids":
        values = numbering.number_siblings(len(objs), fmts["nested_item_format"])
    elif kind == "topic":
        values = numbering.number_siblings(len(objs), fmts["topic_format"])
    elif kind == "subtopic":
        values = numbering.number_siblings(len(objs), fmts["subtopic_format"])
    elif kind == "case":
        values = numbering.number_siblings(len(objs), fmts["multi_citation_format"])
    else:
        values = [""] * len(objs)
    return {ident(o): value for o, value in zip(objs, values)}
