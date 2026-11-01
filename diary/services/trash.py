"""Delete, Trash restore and permanent delete (docs/DESIGN.md sections 5.6 and 7).

Delete only sets ``deleted_at``. Deleting a record moves it and everything below it to Trash as one
batch (``delete_batch``); restoring a record restores exactly the part of that batch at or below it.
Permanent delete is the only place rows are removed, and it refuses while other Notes link to what
would be lost. The Admin-only rule for permanent delete is checked in the view layer.
"""
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Lower

from ..models import NoteLink, Topic, TrashBatch
from .core import (
    Ctx,
    ActionResult,
    ancestors,
    check_version,
    clean_name,
    commit,
    descendants,
    get_record,
    label,
    live_subject_name_taken,
    make_result,
    next_free_name,
    now,
    record_type,
)
from .errors import NameClash, ParentInTrash, PermanentDeleteRefused, Refused, ValidationFailed
from .moves import check_heading_mix
from .sequences import get_pos, ident, index_for_position, lock_sequence, normalize, place, sequence_key

LINK_TARGETS = ("subject", "topic", "subtopic", "section", "item")


def delete(profile, user, kind, record_id, expected_version=None):
    """Move a record and everything below it to Trash as one batch. Deleting twice is harmless."""
    ctx = Ctx(profile, user)
    with transaction.atomic():
        obj = get_record(ctx, kind, record_id, include_deleted=True)
        if obj.deleted_at is not None:
            return make_result(ctx, obj)
        check_version(obj, expected_version)
        batch, count = trash_subtree(ctx, obj)
        return make_result(ctx, obj, batch=batch, count=count)


def trash_subtree(ctx, obj, change_kind="delete"):
    """Put ``obj`` (live, locked) and its live descendants into one new Trash batch. Returns (batch id, count).

    The live siblings keep their positions (numbers come from the order, so gaps do not show); the
    records in the batch keep theirs so that Restore can put them back where they were.
    """
    key = sequence_key(obj)
    if key is not None:
        lock_sequence(ctx, key)
    below = descendants(obj, live_only=True, lock=True)
    batch = TrashBatch.objects.create(
        profile_id=ctx.profile_id,
        root_type=record_type(obj),
        root_id=obj.pk,
        label=label(obj)[:500],
        created_by=ctx.actor,
    )
    stamp = now()
    for rec in [obj] + below:
        rec.deleted_at = stamp
        rec.delete_batch = batch.id
        commit(ctx, rec, change_kind, check=False)
    return batch.id, 1 + len(below)


def _name_taken(rec, name):
    kind = record_type(rec)
    if kind == "subject":
        return live_subject_name_taken(rec.profile_id, name, rec.pk)
    if kind == "topic":
        return (
            Topic._base_manager.filter(profile_id=rec.profile_id, subject_id=rec.subject_id, deleted_at__isnull=True)
            .annotate(lowered=Lower("name"))
            .filter(lowered=name.lower())
            .exclude(pk=rec.pk)
            .exists()
        )
    return False


def _suggest(rec):
    if record_type(rec) == "subject":
        return next_free_name(type(rec), rec.profile_id, rec.name)
    return next_free_name(type(rec), rec.profile_id, rec.name, subject_id=rec.subject_id)


def _check_restorable(rec, targets):
    kind = record_type(rec)
    if kind == "case":
        parent = rec.item
        if parent.kind != "multi":
            raise Refused("This Case belonged to a Multi-Item that is no longer a Multi-Item, so it cannot be restored here.")
    if kind == "item" and rec.parent_item_id is not None and rec.parent_item.kind != "nested":
        raise Refused("This Item belonged to a Nested Item that is no longer a Nested Item, so it cannot be restored here.")
    if kind == "topic":
        check_heading_mix(rec.subject, "topic")
    if kind == "subtopic" and rec.subject_id is not None:
        check_heading_mix(rec.subject, "subtopic")


def restore(
    profile, user, kind, record_id, expected_version=None, new_name=None, new_names=None, restore_parents=False
):
    """Restore a record from Trash together with the part of its batch at or below it.

    * Parent (or an ancestor) in Trash: raises ParentInTrash unless ``restore_parents`` is True, which
      restores each ancestor on its own (not the rest of their batches).
    * A Subject or Topic whose name is now taken by a live one: raises NameClash (with a suggestion)
      unless a new name is given in ``new_name`` (for this record) or ``new_names`` ({(type, id): name}).
    * Restoring something that is not in Trash changes nothing.
    """
    ctx = Ctx(profile, user)
    with transaction.atomic():
        obj = get_record(ctx, kind, record_id, include_deleted=True)
        if obj.deleted_at is None:
            return make_result(ctx, obj)
        check_version(obj, expected_version)
        trashed = [(k, a) for k, a in ancestors(obj) if a.deleted_at is not None]
        if trashed and not restore_parents:
            raise ParentInTrash([(k, a.pk, label(a)) for k, a in trashed])
        chain = [get_record(ctx, k, a.pk, include_deleted=True) for k, a in trashed]
        batch = obj.delete_batch
        below = [
            d
            for d in descendants(obj, lock=True)
            if batch is not None and d.deleted_at is not None and d.delete_batch == batch
        ]
        names = dict(new_names or {})
        if new_name is not None:
            names[(kind, obj.pk)] = new_name
        targets = chain + [obj] + below
        for rec in targets:
            _check_restorable(rec, targets)
            wanted = names.get(ident(rec))
            if wanted is not None:
                wanted = clean_name(wanted)
                if _name_taken(rec, wanted):
                    raise ValidationFailed(f"The name {wanted!r} is already used. Choose another.")
                rec.name = wanted
            elif record_type(rec) in ("subject", "topic") and _name_taken(rec, rec.name):
                raise NameClash(record_type(rec), rec.pk, rec.name, _suggest(rec))
        anchored = chain + [obj]
        for rec in anchored:
            key = sequence_key(rec)
            rec.deleted_at = None
            rec.delete_batch = None
            if key is None:
                commit(ctx, rec, "restore", check=False)
            else:
                lock_sequence(ctx, key)
                place(ctx, rec, key, index_for_position(ctx, key, get_pos(rec)), "restore")
        for rec in below:
            rec.deleted_at = None
            rec.delete_batch = None
            commit(ctx, rec, "restore", check=False)
        for key in dict.fromkeys(sequence_key(rec) for rec in below):
            normalize(ctx, key)
        return make_result(ctx, obj, count=len(targets))


def incoming_links(ctx, members):
    """Note links from outside ``members`` that point at any of them (live or in Trash), as dicts."""
    by_type = {}
    for rec in members:
        by_type.setdefault(record_type(rec), []).append(rec.pk)
    condition = Q()
    for kind in LINK_TARGETS:
        if kind in by_type:
            condition |= Q(**{f"{kind}_id__in": by_type[kind]})
    if not condition:
        return []
    links = (
        NoteLink._base_manager.filter(condition, profile_id=ctx.profile_id)
        .exclude(note_id__in=by_type.get("note", []))
        .select_related("note")
        .order_by("pk")
    )
    names = {ident(rec): label(rec) for rec in members}
    result = []
    for link in links:
        for kind in LINK_TARGETS:
            target_id = getattr(link, f"{kind}_id")
            if target_id is not None:
                result.append(
                    {
                        "link_id": link.pk,
                        "note_id": link.note_id,
                        "note_label": label(link.note),
                        "live": link.deleted_at is None and link.note.deleted_at is None,
                        "target_type": kind,
                        "target_id": target_id,
                        "target_label": names.get((kind, target_id), ""),
                    }
                )
    return result


def permanent_delete(profile, user, kind, record_id):
    """Remove a record from Trash for good, with everything below it. Refused while other Notes link to it."""
    ctx = Ctx(profile, user)
    with transaction.atomic():
        obj = get_record(ctx, kind, record_id, include_deleted=True)
        if obj.deleted_at is None:
            raise Refused("Only records in the Trash can be deleted permanently.")
        below = descendants(obj, lock=True)
        if any(d.deleted_at is None for d in below):
            raise Refused("Something below this record is not in the Trash, so it cannot be deleted permanently.")
        members = [obj] + below
        links = incoming_links(ctx, members)
        if links:
            raise PermanentDeleteRefused(links)
        link_ids = [rec.pk for rec in members if record_type(rec) == "notelink"]
        NoteLink._base_manager.filter(pk__in=link_ids).delete()
        counts = {}
        for rec in members:
            counts[record_type(rec)] = counts.get(record_type(rec), 0) + 1
        obj.delete()
        TrashBatch.objects.filter(profile_id=ctx.profile_id, root_type=kind, root_id=record_id).delete()
        return ActionResult(record=None, changed=True, group=None, touched=[], info={"deleted": counts})
