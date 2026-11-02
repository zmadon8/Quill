"""Create and edit records (docs/DESIGN.md sections 5.4 and 5.5). Moves are in moves.py, deletes in trash.py."""
from django.db import transaction

from ..models import CITATION_LAYOUT_CHOICES, FLAG_CHOICES
from ..richtext import sanitise_html
from .core import (
    MODELS,
    Ctx,
    check_version,
    clean_name,
    commit,
    create as create_row,
    get_record,
    make_result,
)
from . import housing
from .errors import Refused, ValidationFailed
from .moves import ALLOWED_PARENTS, NICE, check_move_allowed, parent_column
from .sequences import lock_sequence, make_room, normalize, place, sequence_key

EDITABLE = {
    "subject": ("name",),
    "topic": ("name",),
    "subtopic": ("name",),
    "section": ("name", "needs_review", "review_note"),
    "item": ("text", "citation", "citation_layout", "flag", "flag_text", "needs_review", "review_note"),
    "case": ("citation", "comment"),
    "note": ("text",),
}

CREATABLE = {
    "subject": ("name", "show_on_landing"),
    "topic": ("name",),
    "subtopic": ("name",),
    "section": ("name", "needs_review", "review_note"),
    "item": ("text", "citation", "citation_layout", "flag", "flag_text", "needs_review", "review_note"),
    "case": ("citation", "comment"),
    "note": ("text",),
}

RICH = {"text", "comment"}
NAMES = {"subject", "topic", "subtopic"}


def _normalise(kind, name, value):
    """The value as it would be stored, so a repeat of the same edit is recognised as no change."""
    if name in RICH:
        return sanitise_html(value or "")
    if name == "name" and kind in NAMES:
        return clean_name(value)
    if name == "flag" and value not in {c[0] for c in FLAG_CHOICES}:
        raise ValidationFailed(f"{value!r} is not a flag choice.")
    if name == "citation_layout" and value not in {c[0] for c in CITATION_LAYOUT_CHOICES}:
        raise ValidationFailed(f"{value!r} is not a way to show citations.")
    if name in ("needs_review", "show_on_landing"):
        return bool(value)
    return value if value is not None else ""


def edit(profile, user, kind, record_id, changes, expected_version=None):
    """Change content fields. Structure (parent, position, type) has its own functions.

    A stale ``expected_version`` raises Conflict (both versions attached). Saving the values the
    record already has changes nothing, so a repeated save is harmless.
    """
    if kind not in EDITABLE:
        raise Refused(f"A {NICE.get(kind, kind)} cannot be edited.")
    unknown = set(changes) - set(EDITABLE[kind])
    if unknown:
        raise Refused("These fields cannot be changed here: " + ", ".join(sorted(unknown)))
    ctx = Ctx(profile, user)
    with transaction.atomic():
        obj = get_record(ctx, kind, record_id)
        wanted = {name: _normalise(kind, name, value) for name, value in changes.items()}
        actual = {name: value for name, value in wanted.items() if getattr(obj, name) != value}
        if not actual:
            return make_result(ctx, obj)
        check_version(obj, expected_version, mine=actual)
        if kind == "item" and "citation" in actual:
            raise ValidationFailed("The citations of an Item are kept as Cases: edit the Case, not the Item.")
        for name, value in actual.items():
            setattr(obj, name, value)
        commit(ctx, obj, "edit")
        return make_result(ctx, obj)


def create(profile, user, record_type, parent=None, index=None, **fields):
    """Add a record. ``parent`` is (type, id); a Subject has none. It is placed at ``index`` (None = last)."""
    if record_type not in CREATABLE:
        raise Refused(f"A {NICE.get(record_type, record_type)} cannot be created here.")
    unknown = set(fields) - set(CREATABLE[record_type])
    if unknown:
        raise Refused("These fields cannot be set: " + ", ".join(sorted(unknown)))
    ctx = Ctx(profile, user)
    model = MODELS[record_type]
    values = {name: _normalise(record_type, name, value) for name, value in fields.items()}
    with transaction.atomic():
        if record_type == "subject":
            if parent is not None:
                raise Refused("A Subject has no parent.")
            columns = {}
        else:
            if parent is None:
                raise Refused(f"A {NICE[record_type]} needs a place to go.")
            if parent[0] not in ALLOWED_PARENTS[record_type]:
                raise Refused(f"A {NICE[record_type]} cannot be placed under a {NICE.get(parent[0], parent[0])}.")
            if record_type in housing.HOUSED:
                parent = housing.house_parent(ctx, parent)  # under a Subject: into its Topic "1" (D61)
            target = get_record(ctx, parent[0], parent[1])
            columns = {f"{parent_column(record_type, parent[0])}_id": target.pk}
            draft = model(profile_id=ctx.profile_id, **columns, **values)
            check_move_allowed(draft, parent[0], target)
        draft = model(profile_id=ctx.profile_id, **columns, **values)
        key = sequence_key(draft)
        lock_sequence(ctx, key)
        number = make_room(ctx, key, index)
        if record_type == "subject":
            position = {"landing_position" if draft.show_on_landing else "other_acts_position": number}
        else:
            position = {"position": number}
        # The citations of an Item are Cases (10d). A citation given with a new Item becomes its first Case.
        first_citation = ""
        if record_type == "item":
            first_citation = values.pop("citation", "") or ""
        obj = create_row(ctx, model, **columns, **values, **position)
        if first_citation:
            create_row(ctx, MODELS["case"], item=obj, citation=first_citation, position=1)
        return make_result(ctx, obj)


def set_landing(profile, user, subject_id, show, expected_version=None):
    """Show a Subject on the landing page (True) or list it under Other Subjects (False).

    It takes the next free stored number in the other list (it is shown alphabetically there) and the
    list it left is not renumbered. Repeating the same choice changes nothing.
    """
    ctx = Ctx(profile, user)
    show = bool(show)
    with transaction.atomic():
        obj = get_record(ctx, "subject", subject_id)
        if obj.show_on_landing == show:
            return make_result(ctx, obj)
        check_version(obj, expected_version)
        old_key = sequence_key(obj)
        lock_sequence(ctx, old_key)
        obj.show_on_landing = show
        place(ctx, obj, sequence_key(obj), None, "move")
        normalize(ctx, old_key)
        return make_result(ctx, obj)
