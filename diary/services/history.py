"""Version history: list the versions of a record and restore an earlier one (docs/DESIGN.md section 9.1).

Restoring a version never rewrites history: it saves a NEW version carrying the old content.
Only content fields come back (the same ones ``records.edit`` can change). Where a record sits
and what type of Item it is are not touched here: Undo reverses moves and conversions.
"""
from django.db import transaction

from .. import nested_conversion as legacy
from ..models import Case, VersionHistory
from .core import Ctx, check_version, commit, create, get_record, make_result
from .errors import NotFound, Refused
from .records import EDITABLE
from .sequences import make_room


def history_for(profile, kind, record_id):
    """All versions of one record in this profile, newest first."""
    return VersionHistory.objects.filter(profile=profile, record_type=kind, record_id=record_id).order_by(
        "-version", "-id"
    )


def restore_version(profile, user, kind, record_id, version, expected_version=None):
    """Make the content of an earlier version current again, as a new version."""
    if kind not in EDITABLE:
        raise Refused("History restore is not available for this kind of record.")
    ctx = Ctx(profile, user)
    with transaction.atomic():
        obj = get_record(ctx, kind, record_id)
        row = history_for(profile, kind, record_id).filter(version=version).first()
        if row is None:
            raise NotFound("That version does not exist for this record.")
        snap = row.snapshot
        # A version from before the Multi-Item merge (10d) or Nested Items (round 10) may say "multi" or
        # "nested": every Item is a plain Item now, so that is no obstacle.
        changes = {name: snap[name] for name in EDITABLE[kind] if name in snap and snap[name] != getattr(obj, name)}
        old_citation = None
        if kind == "item":
            # Citations of an Item live in its Cases; Item.citation stays empty. An old version's citation
            # (before 10d, or a Nested Item's) becomes Case (a).
            changes.pop("citation", None)
            old_citation = legacy.old_snapshot_citation(snap)
        if not changes and old_citation is None:
            return make_result(ctx, obj)
        check_version(obj, expected_version, mine=changes)
        if changes:
            for name, value in changes.items():
                setattr(obj, name, value)
            commit(ctx, obj, "restore")
        if old_citation is not None:
            _restore_first_citation(ctx, obj, old_citation)
        return make_result(ctx, obj)


def _restore_first_citation(ctx, item, citation):
    """An old version's single ``citation`` becomes Case (a): the first live Case is set to it, or made."""
    first = (
        Case._base_manager.select_for_update()
        .filter(item=item, profile_id=ctx.profile_id, deleted_at__isnull=True)
        .order_by("position", "pk")
        .first()
    )
    if first is None:
        position = make_room(ctx, ("case", "item", item.pk), 0)
        create(ctx, Case, "restore", item=item, citation=citation, position=position)
    elif first.citation != citation:
        first.citation = citation
        commit(ctx, first, "restore")
