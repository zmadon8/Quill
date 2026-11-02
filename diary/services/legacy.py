"""Mapping from the old Item shape to the merged one (docs/DESIGN.md, "Proposal for 10d" and its decision log).

Before 10d an Item was plain, multi or nested; a plain or nested Item held ONE citation in
``Item.citation`` and a multi Item held its citations as Cases. After 10d Case is the single store of
citations for every Item except a Nested Item (which cannot own Cases), ``kind`` is plain or nested
only, and ``Item.citation`` is empty for every non-nested Item.

This module is the ONE place that knows the mapping. It is used by

  * data migration ``diary.0010_merge_multi_into_item`` (``migrate_items``),
  * the backup loader (``upgrade_document_items``), so an OLD backup file is mapped exactly the way
    the migration maps the live database,
  * History restore (``legacy_snapshot_citation``), so an old version that predates the merge maps its
    ``citation`` into Case (a).

The rules, with nothing altered silently (every change below is reported in the returned statistics and
written to version history with change kind "migrate"):

  1. kind "multi" becomes "plain". Its Cases are kept exactly as they are.
  2. A non-nested Item whose ``citation`` is not the empty string gets a NEW first Case holding that
     citation verbatim (even if it is only spaces; those are counted as ``whitespace_only`` and are
     not trimmed or dropped), an empty comment, and the Item's own ``citation`` becomes "".
  3. A Nested Item keeps its own citation untouched: a Nested Item cannot own Cases. Those are counted
     as ``nested_with_citation_kept``.
  4. The new Case sits before any Case the Item already had. It gets position 1 when the Item had no
     Cases (the app keeps live positions at 1..n), else one less than the lowest existing position. If
     the lowest existing position is already 0 there is no free slot in front, and nothing is guessed:
     ``LegacyConflict`` is raised and the whole migration or restore stops.
  5. The new Case copies the Item's trash state (``deleted_at`` and ``delete_batch``), profile and
     created/updated-by, so restoring the Item from Trash brings its citation back with it.
  6. The Item's version goes up by one and both records get a "migrate" history row.

This module imports no models, so a migration can use it safely.
"""
import datetime
import uuid
from collections import defaultdict
from dataclasses import dataclass

from django.db import transaction

KIND_PLAIN = "plain"
KIND_MULTI = "multi"
KIND_NESTED = "nested"
CHANGE_KIND = "migrate"

#: Item and Case foreign key columns: backup files name them ``author``, snapshots ``author_id``.
_ITEM_FKS = frozenset({"profile", "created_by", "updated_by", "subject", "topic", "subtopic", "parent_item"})
_CASE_FKS = frozenset({"profile", "created_by", "updated_by", "item"})


class LegacyConflict(Exception):
    """Old data that cannot be mapped without guessing. Nothing is changed when this is raised."""


class MigrationVerificationError(Exception):
    """The record counts after the mapping are not what they must be. The change is rolled back."""


@dataclass(frozen=True)
class Conversion:
    new_kind: str
    new_citation: str
    #: Citation text of the Case to create, or None when no Case is needed.
    case_citation: object
    case_position: object
    whitespace_only: bool = False
    kind_changed: bool = False


def map_kind(kind):
    """The stored kind after the merge: "multi" is gone."""
    return KIND_PLAIN if kind == KIND_MULTI else kind


def new_case_position(case_positions):
    """Position of the Case made from an Item's own citation: before every existing Case."""
    positions = list(case_positions)
    if not positions:
        return 1
    lowest = min(positions)
    if lowest < 1:
        raise LegacyConflict(
            "An Item has its own citation and also Cases starting at position 0, so there is no free "
            "place in front of them for its citation. Nothing was changed."
        )
    return lowest - 1


def convert_item(kind, citation, case_positions=()):
    """What the mapping does to one Item, or None if the Item is already in the new shape."""
    citation = citation or ""
    new_kind = map_kind(kind)
    moves = kind != KIND_NESTED and citation != ""
    if not moves and new_kind == kind:
        return None
    return Conversion(
        new_kind=new_kind,
        new_citation="" if moves else citation,
        case_citation=citation if moves else None,
        case_position=new_case_position(case_positions) if moves else None,
        whitespace_only=moves and not citation.strip(),
        kind_changed=new_kind != kind,
    )


def legacy_snapshot_citation(snapshot, item_kind):
    """The old ``citation`` in a version-history snapshot that must become Case (a), else None.

    Snapshots written after the merge carry an empty ``citation`` for a non-nested Item, so an empty
    value means "nothing to map", never "clear Case (a)".
    """
    if item_kind == KIND_NESTED or snapshot.get("kind") == KIND_NESTED:
        return None
    citation = snapshot.get("citation") or ""
    return citation if citation != "" else None


def new_stats():
    return {
        "items_changed": 0,
        "cases_created": 0,
        "multi_to_plain": 0,
        "whitespace_only": 0,
        "nested_with_citation_kept": 0,
    }


# ------------------------------------------------------------------ live database (the migration)

def _snapshot(obj):
    """All columns of ``obj`` as JSON-friendly values (foreign keys as ids), like services.core.snapshot."""
    data = {}
    for fld in obj._meta.concrete_fields:
        value = fld.value_from_object(obj)
        if isinstance(value, (datetime.datetime, datetime.date)):
            value = value.isoformat()
        elif isinstance(value, uuid.UUID):
            value = str(value)
        data[fld.attname] = value
    return data


def _count_state(Item, Case):
    plain_items = Item._default_manager.exclude(kind=KIND_NESTED)
    return {
        "items": Item._default_manager.count(),
        "cases": Case._default_manager.count(),
        "multi": Item._default_manager.filter(kind=KIND_MULTI).count(),
        "to_move": plain_items.exclude(citation="").count(),
        "nested_with_citation": Item._default_manager.filter(kind=KIND_NESTED).exclude(citation="").count(),
    }


def verify_counts(before, after, stats):
    """Raise MigrationVerificationError unless ``after`` is exactly ``before`` plus the mapping."""
    problems = []
    if after["items"] != before["items"]:
        problems.append(f"Item count changed from {before['items']} to {after['items']}")
    expected_cases = before["cases"] + before["to_move"]
    if after["cases"] != expected_cases:
        problems.append(f"Case count is {after['cases']}, expected {expected_cases}")
    if stats["cases_created"] != before["to_move"]:
        problems.append(f"{stats['cases_created']} Cases created for {before['to_move']} citations")
    if after["to_move"] != 0:
        problems.append(f"{after['to_move']} non-nested Items still hold their own citation")
    if after["multi"] != 0:
        problems.append(f"{after['multi']} Items are still Multi-Items")
    if stats["multi_to_plain"] != before["multi"]:
        problems.append(f"{stats['multi_to_plain']} Multi-Items converted of {before['multi']}")
    if after["nested_with_citation"] != before["nested_with_citation"]:
        problems.append(
            f"Nested Items with a citation changed from {before['nested_with_citation']} "
            f"to {after['nested_with_citation']}"
        )
    if problems:
        raise MigrationVerificationError("The citation merge was stopped and rolled back: " + "; ".join(problems) + ".")


def migrate_items(apps):
    """Apply the mapping to the database behind ``apps`` (historical or real models). Returns statistics.

    All or nothing: any error, including a failed count check, rolls every change back.
    """
    Item = apps.get_model("diary", "Item")
    Case = apps.get_model("diary", "Case")
    History = apps.get_model("diary", "VersionHistory")
    stats = new_stats()
    with transaction.atomic():
        before = _count_state(Item, Case)
        positions = defaultdict(list)
        for item_id, position in Case._default_manager.values_list("item_id", "position"):
            positions[item_id].append(position)
        for item in Item._default_manager.order_by("pk"):
            conversion = convert_item(item.kind, item.citation, positions[item.pk])
            if item.kind == KIND_NESTED and item.citation != "":
                stats["nested_with_citation_kept"] += 1
            if conversion is None:
                continue
            if conversion.case_citation is not None:
                case = Case(
                    profile_id=item.profile_id,
                    item_id=item.pk,
                    citation=conversion.case_citation,
                    comment="",
                    comment_plain="",
                    position=conversion.case_position,
                    deleted_at=item.deleted_at,
                    delete_batch=item.delete_batch,
                    created_by_id=item.created_by_id,
                    updated_by_id=item.updated_by_id,
                    version=1,
                )
                case.save()
                History.objects.create(
                    record_type="case", record_id=case.pk, version=1, snapshot=_snapshot(case),
                    changed_by=None, profile_id=item.profile_id, change_kind=CHANGE_KIND, group=None,
                )
                stats["cases_created"] += 1
                stats["whitespace_only"] += int(conversion.whitespace_only)
            stats["multi_to_plain"] += int(conversion.kind_changed)
            stats["items_changed"] += 1
            item.kind = conversion.new_kind
            item.citation = conversion.new_citation
            item.version += 1
            # A queryset update leaves updated_at and updated_by alone: this is a data move, not an edit.
            Item._default_manager.filter(pk=item.pk).update(
                kind=item.kind, citation=item.citation, version=item.version
            )
            History.objects.create(
                record_type="item", record_id=item.pk, version=item.version, snapshot=_snapshot(item),
                changed_by=None, profile_id=item.profile_id, change_kind=CHANGE_KIND, group=None,
            )
        verify_counts(before, _count_state(Item, Case), stats)
    return stats


# ------------------------------------------------------------------ backup files (the restore)

def _next_pk(records):
    return max((record["pk"] for record in records), default=0) + 1


def _record_snapshot(pk, fields, fks):
    snap = {"id": pk}
    for name, value in fields.items():
        snap[f"{name}_id" if name in fks else name] = value
    return snap


def upgrade_document_items(models_in_file, stamp):
    """Map the Items in a parsed backup ``models`` dict to the new shape, in place. Returns statistics.

    Same rules as ``migrate_items``. Cases and history rows are appended to the file's own
    ``diary.Case`` and ``diary.VersionHistory`` lists with new primary keys above the file's highest
    (the sequences are reset after a restore). A file that is already in the new shape is not changed.
    ``stamp`` is the ISO time written as the creation time of the new rows.
    """
    stats = new_stats()
    items = models_in_file.get("diary.Item", [])
    cases = models_in_file.setdefault("diary.Case", [])
    history = models_in_file.setdefault("diary.VersionHistory", [])
    positions = defaultdict(list)
    for case in cases:
        positions[case["fields"].get("item")].append(case["fields"].get("position", 0))
    next_case = _next_pk(cases)
    next_history = _next_pk(history)
    for record in sorted(items, key=lambda r: r["pk"]):
        fields = record["fields"]
        kind = fields.get("kind", KIND_PLAIN)
        citation = fields.get("citation", "") or ""
        if kind == KIND_NESTED and citation != "":
            stats["nested_with_citation_kept"] += 1
        conversion = convert_item(kind, citation, positions[record["pk"]])
        if conversion is None:
            continue
        profile = fields.get("profile")
        if conversion.case_citation is not None:
            case_fields = {
                "created_at": stamp,
                "updated_at": stamp,
                "deleted_at": fields.get("deleted_at"),
                "delete_batch": fields.get("delete_batch"),
                "version": 1,
                "created_by": fields.get("created_by"),
                "updated_by": fields.get("updated_by"),
                "profile": profile,
                "item": record["pk"],
                "citation": conversion.case_citation,
                "comment": "",
                "comment_plain": "",
                "position": conversion.case_position,
            }
            cases.append({"model": "diary.case", "pk": next_case, "fields": case_fields})
            history.append(_history_record(
                next_history, "case", next_case, 1, _record_snapshot(next_case, case_fields, _CASE_FKS), profile, stamp
            ))
            next_case += 1
            next_history += 1
            stats["cases_created"] += 1
            stats["whitespace_only"] += int(conversion.whitespace_only)
        stats["multi_to_plain"] += int(conversion.kind_changed)
        stats["items_changed"] += 1
        fields["kind"] = conversion.new_kind
        fields["citation"] = conversion.new_citation
        fields["version"] = fields.get("version", 1) + 1
        history.append(_history_record(
            next_history, "item", record["pk"], fields["version"], _record_snapshot(record["pk"], fields, _ITEM_FKS),
            profile, stamp,
        ))
        next_history += 1
    return stats


def _history_record(pk, record_type, record_id, version, snapshot, profile, stamp):
    return {
        "model": "diary.versionhistory",
        "pk": pk,
        "fields": {
            "record_type": record_type,
            "record_id": record_id,
            "version": version,
            "snapshot": snapshot,
            "changed_at": stamp,
            "changed_by": None,
            "profile": profile,
            "change_kind": CHANGE_KIND,
            "group": None,
        },
    }


def describe(stats):
    """One plain sentence for a log or message; empty when nothing was mapped."""
    if not stats["items_changed"]:
        return ""
    parts = [
        f"{stats['cases_created']} citation(s) moved into Case (a)",
        f"{stats['multi_to_plain']} Multi-Item(s) became ordinary Items",
    ]
    if stats["whitespace_only"]:
        parts.append(f"{stats['whitespace_only']} of the citations were only spaces and were kept as they were")
    if stats["nested_with_citation_kept"]:
        parts.append(f"{stats['nested_with_citation_kept']} Nested Item citation(s) left in place")
    return "Older data format mapped: " + "; ".join(parts) + "."
