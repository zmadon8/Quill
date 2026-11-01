"""Version history: list the versions of a record and restore an earlier one (docs/DESIGN.md section 9.1).

Restoring a version never rewrites history: it saves a NEW version carrying the old content.
Only content fields come back (the same ones ``records.edit`` can change). Where a record sits
and what type of Item it is are not touched here: Undo reverses moves and conversions.
"""
from django.db import transaction

from ..models import VersionHistory
from .core import Ctx, check_version, commit, get_record, make_result
from .errors import NotFound, Refused
from .records import EDITABLE


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
        if kind == "item" and snap.get("kind", obj.kind) != obj.kind:
            raise Refused(
                "That version was a different type of Item. Use Undo or convert the Item back, "
                "then restore the version."
            )
        changes = {name: snap[name] for name in EDITABLE[kind] if name in snap and snap[name] != getattr(obj, name)}
        if not changes:
            return make_result(ctx, obj)
        check_version(obj, expected_version, mine=changes)
        for name, value in changes.items():
            setattr(obj, name, value)
        commit(ctx, obj, "restore")
        return make_result(ctx, obj)
