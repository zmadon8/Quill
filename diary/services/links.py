"""Cross-reference links of a Note (docs/DESIGN.md section 7, decisions D33 onward).

A Note holds one or more links; each points at one Subject, Topic, Sub-topic, Section or Item of the SAME
profile (another profile's record is simply "not found"). The order of a Note's links is the stored
``position`` (1..n among its live links). A link is never removed by the system: removing one is an explicit
action (Delete, which goes to Trash and can be undone), and a link whose target is in Trash stays put and
shows "target deleted" until the target is restored.
"""
from django.db import transaction

from ..models import NoteLink
from .core import Ctx, check_version, commit, create as create_row, get_record, make_result
from .errors import Refused
from .trash import delete, permanent_delete
from .sequences import lock_sequence, make_room, members, place, sequence_key

TARGET_KINDS = ("subject", "topic", "subtopic", "section", "item")


def link_target(link):
    """(type, id) of the one record a link points at."""
    for kind in TARGET_KINDS:
        pk = getattr(link, f"{kind}_id")
        if pk is not None:
            return kind, pk
    return None


def _destination(ctx, target):
    if target is None or target[0] not in TARGET_KINDS:
        raise Refused("A Note can link to a Subject, Topic, Sub-topic, Section or Item.")
    return get_record(ctx, target[0], target[1])


def add_link(profile, user, note_id, target):
    """Link a Note to one target ((type, id)) in the same profile, after its other links.

    Adding the same link twice does nothing. A Subject, Topic, Sub-topic, Section or Item (a Nested
    Item and the Items inside it included) can be the target; a target in Trash or in another profile is refused.
    """
    ctx = Ctx(profile, user)
    with transaction.atomic():
        note = get_record(ctx, "note", note_id)
        destination = _destination(ctx, target)
        column = f"{target[0]}_id"
        existing = NoteLink._base_manager.filter(
            profile_id=ctx.profile_id, note=note, deleted_at__isnull=True, **{column: destination.pk}
        ).first()
        if existing is not None:
            return make_result(ctx, existing)
        key = ("link", "note", note.pk)
        lock_sequence(ctx, key)
        number = make_room(ctx, key, None)
        link = create_row(ctx, NoteLink, note=note, position=number, **{column: destination.pk})
        return make_result(ctx, link)


def retarget_link(profile, user, link_id, target, expected_version=None):
    """Point an existing link (live, or in Trash with its Note) at another record. The link keeps its place in the list.

    Used from the Note editor and from the permanent delete refusal screen. The new target must be live
    and in the same profile; pointing it where it already points changes nothing.
    """
    ctx = Ctx(profile, user)
    with transaction.atomic():
        link = get_record(ctx, "notelink", link_id, include_deleted=True)
        destination = _destination(ctx, target)
        if link_target(link) == (target[0], destination.pk):
            return make_result(ctx, link)
        check_version(link, expected_version)
        for kind in TARGET_KINDS:
            setattr(link, f"{kind}_id", None)
        setattr(link, f"{target[0]}_id", destination.pk)
        commit(ctx, link, "edit", check=False)
        return make_result(ctx, link)


def shift_link(profile, user, link_id, delta, expected_version=None):
    """Move a link up (negative ``delta``) or down among the live links of its Note; clamps at the ends."""
    ctx = Ctx(profile, user)
    with transaction.atomic():
        link = get_record(ctx, "notelink", link_id)
        key = sequence_key(link)
        lock_sequence(ctx, key)
        ordered = members(ctx.profile_id, key)
        current = [m.pk for m in ordered].index(link.pk)
        wanted = max(0, min(len(ordered) - 1, current + int(delta)))
        if wanted == current:
            return make_result(ctx, link)
        check_version(link, expected_version)
        place(ctx, link, key, wanted, "reorder")
        return make_result(ctx, link)


def purge_link(profile, user, link_id):
    """Remove one link for good (Admin only, checked by the view): to Trash first if it is live, then out of the table.

    Used from the permanent delete screen, where a link that points at the record being deleted has to go before
    the record can. The link's version history is kept.
    """
    ctx = Ctx(profile, user)
    with transaction.atomic():
        link = get_record(ctx, "notelink", link_id, include_deleted=True)
        if link.deleted_at is None:
            delete(profile, user, "notelink", link.pk)
        return permanent_delete(profile, user, "notelink", link.pk)
