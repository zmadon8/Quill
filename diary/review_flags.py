""""For review" is merged into the Flags (round 16, docs/DESIGN.md D88).

Owner: "Merge 'For Review' into 'Flags'. Put the text of every item labelled 'For Review' into a Flag as 'Other'." With the
owner's choices (D88): an Item or Section marked For review

  * with no flag: gets the flag Other, its text the review note (or "For review" when there was no note);
  * that already has a flag (Pending, Overruled, Doubted, Other): keeps it, and " · For review: <note>" (or
    " · For review") is added after the flag text, so neither is lost.

Spaces and line breaks in the note are tidied to single spaces (a flag text is one line). The For review switch is then
cleared (the column stays, always False, as a LEGACY column with a check rule: see diary/models.py). A note left behind on
a record that was NOT marked For review (an old switch turned off without emptying the note) is not a flag: it is left in
the legacy note column, untouched, and counted.

Every changed record gets a "migrate" history row and a version bump; nothing is deleted; the counts are checked inside the
transaction and any mismatch rolls everything back. ``migrate_review`` is used by data migration
``diary.0021_review_into_flags``; ``upgrade_document`` maps an OLD backup file exactly the same way before it is restored;
``merge`` is also used by History restore and Undo of a version saved before the merge (services.core.apply_snapshot), and by
the Word import. Like the other mapping modules it imports no models and nothing from the service layer.
"""
import logging

from django.db import transaction

from . import legacy_merge as legacy

logger = logging.getLogger(__name__)

NONE, OTHER = "none", "other"
CHANGE_KIND = "migrate"
REVIEW = "For review"
SEP = " \u00b7 "
ITEM_FKS = frozenset({"profile", "created_by", "updated_by", "subject", "topic", "subtopic"})
MigrationVerificationError = legacy.MigrationVerificationError


def _tidy(text):
    return " ".join((text or "").split())


def merge(flag, flag_text, needs_review, review_note):
    """(flag, flag text) once a For review mark (with ``review_note``) is folded in; unchanged when not marked."""
    flag = flag or NONE
    if not needs_review:
        return flag, flag_text or ""
    note = _tidy(review_note)
    if flag == NONE:
        return OTHER, note or REVIEW
    mark = f"{REVIEW}: {note}" if note else REVIEW
    text = _tidy(flag_text)
    return flag, f"{text}{SEP}{mark}" if text else mark


def new_stats():
    return {"items": 0, "sections": 0, "kept_flag": 0, "notes_left": 0}


def describe(stats):
    if not (stats["items"] or stats["sections"]):
        return ""
    return (
        f"Older data format mapped: {stats['items']} Item(s) and {stats['sections']} Section(s) marked For review now carry "
        f"the review note as a Flag ({stats['kept_flag']} kept their own flag and got the note added)."
    )


# ------------------------------------------------------------------ live database (the migration)

def _counts(Item, Section):
    return {"items": Item._default_manager.count(), "sections": Section._default_manager.count()}


def migrate_review(apps):
    """Apply the merge to the database behind ``apps`` (historical or real models). Returns statistics. All or nothing."""
    Item = apps.get_model("diary", "Item")
    Section = apps.get_model("diary", "Section")
    History = apps.get_model("diary", "VersionHistory")
    stats = new_stats()
    with transaction.atomic():
        before = _counts(Item, Section)
        for Model, kind in ((Item, "item"), (Section, "section")):
            stats["notes_left"] += Model._default_manager.filter(needs_review=False).exclude(review_note="").count()
            for obj in list(Model._default_manager.filter(needs_review=True).order_by("pk")):
                if (obj.flag or NONE) != NONE:
                    stats["kept_flag"] += 1
                obj.flag, obj.flag_text = merge(obj.flag, obj.flag_text, True, obj.review_note)
                obj.needs_review, obj.review_note = False, ""
                obj.version += 1
                # A queryset update leaves updated_at and updated_by alone: this is a data move, not an edit.
                Model._default_manager.filter(pk=obj.pk).update(
                    flag=obj.flag, flag_text=obj.flag_text, needs_review=False, review_note="", version=obj.version
                )
                History.objects.create(
                    record_type=kind, record_id=obj.pk, version=obj.version, snapshot=legacy._snapshot(obj),
                    changed_by=None, profile_id=obj.profile_id, change_kind=CHANGE_KIND, group=None,
                )
                stats["items" if kind == "item" else "sections"] += 1
        problems = []
        if _counts(Item, Section) != before:
            problems.append("the number of Items or Sections changed")
        for Model, name in ((Item, "Item"), (Section, "Section")):
            left = Model._default_manager.filter(needs_review=True).count()
            if left:
                problems.append(f"{left} {name}(s) are still marked For review")
        if problems:
            raise MigrationVerificationError("The For review merge was stopped and rolled back: " + "; ".join(problems) + ".")
    if stats["items"] or stats["sections"]:
        logger.warning(describe(stats))
    return stats


# ------------------------------------------------------------------ backup files (the restore)

def upgrade_document(models_in_file, stamp):
    """Apply the same merge to a parsed backup ``models`` dict, in place. Returns statistics.

    History rows get primary keys above the file's highest. A file made after the merge has nothing marked, so it is not
    changed.
    """
    stats = new_stats()
    history = models_in_file.setdefault("diary.VersionHistory", [])
    next_history = legacy._next_pk(history)
    for label, kind in (("diary.Item", "item"), ("diary.Section", "section")):
        for record in models_in_file.get(label, []):
            fields = record["fields"]
            if not fields.get("needs_review"):
                if (fields.get("review_note") or "").strip():
                    stats["notes_left"] += 1
                continue
            if (fields.get("flag") or NONE) != NONE:
                stats["kept_flag"] += 1
            fields["flag"], fields["flag_text"] = merge(fields.get("flag"), fields.get("flag_text"), True,
                                                        fields.get("review_note"))
            fields["needs_review"], fields["review_note"] = False, ""
            fields["version"] = fields.get("version", 1) + 1
            history.append(legacy._history_record(
                next_history, kind, record["pk"], fields["version"],
                legacy._record_snapshot(record["pk"], fields, ITEM_FKS), fields.get("profile"), stamp,
            ))
            next_history += 1
            stats["items" if kind == "item" else "sections"] += 1
    return stats
