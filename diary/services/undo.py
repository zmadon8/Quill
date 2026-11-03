"""Undo (docs/DESIGN.md section 5.7): reverse one action using the version history.

An action is the set of history rows that share a ``group``. The view layer keeps the group ids of
the current session; this module enforces the rules: only the user's own actions, a warning when a
record changed since, and a refusal when someone else changed it. Undo is itself an action with a
new group, so Undoing an Undo is a redo.
"""
from django.db import transaction

from ..models import VersionHistory
from .core import Ctx, apply_snapshot, commit, get_record, label, make_result, next_free_name, parent_of, record_type
from .errors import NameClash, NotFound, Refused, UndoWarning
from .trash import _name_taken, prune_batches, trash_subtree


def group_summary(profile, group):
    """What an action did, for the Undo button: change kinds and the records touched, in order."""
    rows = list(VersionHistory.objects.filter(profile=profile, group=group).order_by("id"))
    return {
        "kinds": list(dict.fromkeys(r.change_kind for r in rows)),
        "records": list(dict.fromkeys((r.record_type, r.record_id) for r in rows)),
        "count": len(rows),
    }


def _check_place_is_live(obj, in_action):
    """Refuse to bring something back under a parent that is in Trash (unless that parent is undone too)."""
    found = parent_of(obj)
    if found is None or found[1] is None or (found[0], found[1].pk) in in_action:
        return
    if obj.deleted_at is None and found[1].deleted_at is not None:
        raise Refused(
            f"The place this belongs to ({label(found[1])}) is in the Trash. Restore it from the Trash first."
        )


def undo_group(profile, user, group, force=False):
    """Reverse every change in ``group``. Raises UndoWarning if records changed since, unless ``force``."""
    ctx = Ctx(profile, user)
    with transaction.atomic():
        rows = list(VersionHistory.objects.filter(profile=profile, group=group).order_by("id"))
        if not rows:
            raise NotFound("There is nothing to undo.")
        actor = ctx.actor
        if actor is None or any(row.changed_by_id != actor.pk for row in rows):
            raise Refused("Undo only reverses your own changes.")
        first, last = {}, {}
        for row in rows:
            key = (row.record_type, row.record_id)
            first.setdefault(key, row)
            last[key] = row
        keys = sorted(last, key=lambda k: last[k].id, reverse=True)
        records, changed = {}, []
        for key in keys:
            try:
                obj = get_record(ctx, key[0], key[1], include_deleted=True)
            except NotFound:
                raise Refused("Something in this action has since been deleted permanently, so it cannot be undone.")
            records[key] = obj
            if obj.version != last[key].version:
                later = VersionHistory.objects.filter(
                    profile=profile, record_type=key[0], record_id=key[1], version__gt=last[key].version
                )
                if later.exclude(changed_by=actor).exists():
                    raise Refused(
                        f"{label(obj)!r} was changed by someone else after this action, so it cannot be undone."
                    )
                changed.append(
                    {
                        "type": key[0],
                        "id": key[1],
                        "label": label(obj),
                        "expected_version": last[key].version,
                        "current_version": obj.version,
                    }
                )
        if changed and not force:
            raise UndoWarning(changed)
        for key in keys:
            obj = records[key]
            obj.refresh_from_db()
            before = (
                VersionHistory.objects.filter(
                    profile=profile, record_type=key[0], record_id=key[1], version__lt=first[key].version
                )
                .order_by("-version", "-id")
                .first()
            )
            if before is None:
                # The action created it: undoing means taking it (and anything added below it since) out of view.
                if obj.deleted_at is None:
                    trash_subtree(ctx, obj)
                continue
            apply_snapshot(obj, before.snapshot)
            if obj.deleted_at is None and record_type(obj) in ("subject", "topic") and _name_taken(obj, obj.name):
                kind = record_type(obj)
                scope = {} if kind == "subject" else {"subject_id": obj.subject_id}
                raise NameClash(kind, obj.pk, obj.name, next_free_name(type(obj), obj.profile_id, obj.name, **scope))
            _check_place_is_live(obj, set(keys))
            commit(ctx, obj, "restore", check=False)
        prune_batches(ctx.profile_id)
        return make_result(ctx, None)
