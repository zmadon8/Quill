"""Nested Items are gone: how an old Nested Item becomes an ordinary Item with several citations
(docs/DESIGN.md, Round 10, decisions D58 to D61).

Before round 10 a Nested Item was an Item (N) with its own citation C and, beneath it, a list of plain
Items (its children), each with a text and its own citation(s). Now N is a plain Item whose citations are
Cases, shown "on separate lines" (``citation_layout = "lines"``), and the TEXT of every child becomes
the COMMENT of that child's citation. Nothing is lost:

  1. N keeps its id, flag, review marker, Notes, Note links and history. Its text is unchanged and its own
     citation C becomes Case (a) (empty comment). N's ``citation`` column is emptied.
  2. For each child in order (position, then id): its live Cases move to N (same Case rows, so their
     history goes with them). The child's text is put in front of the FIRST of those Cases' comments,
     "<child text> - <comment>"; rich-text paragraphs are kept. A child with no citation gets a new Case with
     an empty citation and the text as its comment.
  3. A child's flag and For-review marker would otherwise disappear, so they are appended to its first
     Case's comment in square brackets, "[Overruled: reason]" and "[For review: note]".
  4. The child's Notes move to N (after N's own), and every Note link that pointed at the child now points
     at N.
  5. N is marked For review with a note saying what was folded, so the owner can look at each result.
  6. The children are not deleted: they go to Trash in one Trash batch labelled "Nested Item conversion",
     where they can still be read and restored by hand. A child that was already in Trash stays there.
  7. Every changed record gets a "migrate" history row.

The mapping is in ``plan_group`` (pure: plain dicts in, a plan out). It is used by

  * data migration ``diary.0015_convert_nested_items`` (``migrate_nested``),
  * the backup loader (``upgrade_document_nested``), so an OLD backup file with kind "nested" Items is
    mapped exactly the way the migration maps the live database,
  * History restore (``old_snapshot_citation`` and ``map_kind``), so an old version of a Nested Item can still
    be restored.

This module imports no models and nothing else from the app except the pure helpers it shares with
``legacy_merge``, so the frozen migration does not depend on the live service layer.
"""
import html
import logging
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from django.db import transaction

from . import legacy_merge as legacy
from .richtext import plain_text

logger = logging.getLogger(__name__)

KIND_PLAIN = "plain"
KIND_NESTED = "nested"
LAYOUT_INLINE = "inline"
LAYOUT_LINES = "lines"
CHANGE_KIND = "migrate"
BATCH_LABEL = "Nested Item conversion"
SEPARATOR = " - "

ITEM_FKS = frozenset({"profile", "created_by", "updated_by", "subject", "topic", "subtopic"})
CASE_FKS = frozenset({"profile", "created_by", "updated_by", "item"})
NOTE_FKS = frozenset({"profile", "created_by", "updated_by", "subject", "topic", "subtopic", "item", "section"})
LINK_FKS = frozenset({"profile", "created_by", "updated_by", "note", "subject", "topic", "subtopic", "section", "item"})
PARENT_COLUMNS = ("subject", "topic", "subtopic")

MigrationVerificationError = legacy.MigrationVerificationError


# ------------------------------------------------------------------ small pure helpers

def map_kind(kind):
    """The stored kind today: "multi" and "nested" are both plain Items now."""
    return KIND_PLAIN


def old_snapshot_citation(snapshot):
    """The old ``citation`` of a version-history snapshot that must become Case (a), else None.

    Before the merge (10d) and for Nested Items the citation lived in the Item; an empty value means
    "nothing to map", never "clear Case (a)".
    """
    citation = snapshot.get("citation") or ""
    return citation if citation != "" else None


def _paragraphs(markup):
    """(paragraph strings, whether the markup used <p> blocks). Empty and blank markup gives ([], False)."""
    if not markup or not markup.strip():
        return [], False
    block = "<p" in markup
    return [part for part in re.split(r"</?p>", markup) if part.strip()], block


def _join(paragraphs, block):
    return "".join(f"<p>{p}</p>" for p in paragraphs) if block else " ".join(paragraphs)


def combine_comment(text, comment):
    """"<child text> - <comment>", keeping rich-text paragraphs; either part may be empty."""
    first, block_a = _paragraphs(text)
    second, block_b = _paragraphs(comment)
    if not first:
        return comment or ""
    if not second:
        return text
    merged = first[:-1] + [first[-1] + SEPARATOR + second[0]] + second[1:]
    return _join(merged, block_a or block_b or len(merged) > 1)


def append_suffix(markup, suffix):
    """Add ``suffix`` (plain text) after the last paragraph of ``markup``; the suffix alone if there is none."""
    if not suffix:
        return markup
    paragraphs, block = _paragraphs(markup)
    if not paragraphs:
        return f"<p>{suffix}</p>" if block else suffix
    paragraphs[-1] = paragraphs[-1] + " " + suffix
    return _join(paragraphs, block)


def flag_suffix(flag, flag_text, needs_review, review_note):
    """"[Overruled: reason] [For review: note]" for a child's flag and marker, or "" when it has neither."""
    parts = []
    if flag and flag != "none":
        name = flag.capitalize()
        text = (flag_text or "").strip()
        parts.append(f"[{name}: {html.escape(text, quote=False)}]" if text else f"[{name}]")
    if needs_review:
        note = (review_note or "").strip()
        parts.append(f"[For review: {html.escape(note, quote=False)}]" if note else "[For review]")
    return " ".join(parts)


# ------------------------------------------------------------------ the plan (pure)

@dataclass
class CaseSpec:
    #: Id of an existing Case that moves to N (and gets this comment), or None for a new Case.
    existing_id: object
    citation: str
    comment: str
    #: Id of the child it came from, or None (N's own citation).
    child_id: object = None


@dataclass
class GroupPlan:
    cases: list = field(default_factory=list)
    review_note: str = ""
    needs_review: bool = False
    layout: str = LAYOUT_INLINE
    folded: list = field(default_factory=list)  # child ids folded into N
    empty_children: list = field(default_factory=list)  # folded children that had nothing to carry over


def plan_group(parent, children):
    """The result of folding ``children`` into ``parent`` (dicts, see below). Pure; writes nothing.

    parent:   {citation, review_note, needs_review, cases: [{id, citation, comment}]}  (cases: normally none)
    children: [{id, text, flag, flag_text, needs_review, review_note, cases: [{id, citation, comment}],
                notes: int, links: int}] in display order; ``cases`` are the ones that move.
    """
    plan = GroupPlan()
    if parent.get("citation", "") != "":
        plan.cases.append(CaseSpec(None, parent["citation"], "", None))
    for case in parent.get("cases", []):
        plan.cases.append(CaseSpec(case["id"], case["citation"], case["comment"], None))
    notes = links = flagged = 0
    for child in children:
        plan.folded.append(child["id"])
        notes += child.get("notes", 0)
        links += child.get("links", 0)
        suffix = flag_suffix(child.get("flag"), child.get("flag_text"), child.get("needs_review"), child.get("review_note"))
        flagged += int(bool(suffix))
        text = child.get("text") or ""
        cases = child.get("cases", [])
        if cases:
            for number, case in enumerate(cases):
                comment = case["comment"] or ""
                if number == 0:
                    comment = append_suffix(combine_comment(text, comment), suffix)
                plan.cases.append(CaseSpec(case["id"], case["citation"], comment, child["id"]))
        else:
            comment = append_suffix(text, suffix)
            if _paragraphs(comment)[0]:
                plan.cases.append(CaseSpec(None, "", comment, child["id"]))
            else:
                plan.empty_children.append(child["id"])
    if plan.folded:
        plan.layout = LAYOUT_LINES
        plan.needs_review = True
        said = (
            f"Converted from a Nested Item: {len(plan.folded)} sub-item(s) were folded into citations "
            "(each sub-item's text is now the comment of its citation)."
        )
        if notes or links:
            said += f" {notes} Note(s) and {links} link(s) of the sub-items now belong to this Item."
        if flagged:
            said += f" {flagged} sub-item(s) had a flag or review marker, now written in square brackets in the comment."
        old = (parent.get("review_note") or "").strip()
        plan.review_note = f"{old}\n{said}" if old else said
    else:
        plan.review_note = parent.get("review_note") or ""
        plan.needs_review = bool(parent.get("needs_review"))
    return plan


def new_stats():
    return {
        "nested_items": 0,
        "children_folded": 0,
        "children_left_in_trash": 0,
        "cases_created": 0,
        "cases_moved": 0,
        "notes_moved": 0,
        "links_retargeted": 0,
        "empty_children": 0,
    }


def describe(stats):
    """One plain sentence for a log or message; empty when nothing was converted."""
    if not stats.get("nested_items"):
        return ""
    parts = [
        f"{stats['nested_items']} Nested Item(s) became ordinary Items with citations on separate lines",
        f"{stats['children_folded']} sub-item(s) folded into citation comments (kept in Trash as '{BATCH_LABEL}')",
    ]
    if stats["notes_moved"] or stats["links_retargeted"]:
        parts.append(f"{stats['notes_moved']} Note(s) moved and {stats['links_retargeted']} link(s) retargeted")
    return "Older data format mapped: " + "; ".join(parts) + "."


def letters(number):
    """1 -> a, 2 -> b, ... 27 -> aa (for messages)."""
    out = ""
    while number > 0:
        number, rest = divmod(number - 1, 26)
        out = chr(97 + rest) + out
    return out


# ------------------------------------------------------------------ live database (the migration)

def conversion_order(parent_of, nested_ids):
    """Primary keys of the Items to convert, deepest first.

    ``parent_of`` maps every Item that sits beneath another Item to that parent's key. An Item is converted when it
    is a Nested Item or has any Item beneath it (the parent may be of ANY kind: older data and earlier bugs left
    children under plain Items, and those are folded the same way). Deepest first means an inner group is
    converted before the group that contains it, so each parent absorbs finished children. A cycle (bad data)
    cannot loop: its members get depth 0 and the final sweep detaches anything still attached.
    """
    def depth(pk):
        seen, count = {pk}, 0
        while parent_of.get(pk) is not None:
            pk = parent_of[pk]
            if pk in seen:
                return 0
            seen.add(pk)
            count += 1
        return count

    chosen = set(nested_ids) | {p for p in parent_of.values() if p is not None}
    return sorted(chosen, key=lambda pk: (-depth(pk), pk))


def _case_dict(case):
    return {"id": case.pk, "citation": case.citation, "comment": case.comment}


def _count_state(Item, Case, Note, NoteLink):
    return {
        "items": Item._default_manager.count(),
        "cases": Case._default_manager.count(),
        "notes": Note._default_manager.count(),
        "links": NoteLink._default_manager.count(),
        "nested": Item._default_manager.filter(kind=KIND_NESTED).count(),
        "with_parent_item": Item._default_manager.filter(parent_item__isnull=False).count(),
        "live_items": Item._default_manager.filter(deleted_at__isnull=True).count(),
    }


def verify_counts(before, after, stats, folded_live):
    problems = []
    if after["items"] != before["items"]:
        problems.append(f"Item count changed from {before['items']} to {after['items']}")
    if after["notes"] != before["notes"]:
        problems.append(f"Note count changed from {before['notes']} to {after['notes']}")
    if after["links"] != before["links"]:
        problems.append(f"Note link count changed from {before['links']} to {after['links']}")
    expected_cases = before["cases"] + stats["cases_created"]
    if after["cases"] != expected_cases:
        problems.append(f"Case count is {after['cases']}, expected {expected_cases}")
    if after["nested"]:
        problems.append(f"{after['nested']} Nested Items are left")
    if after["with_parent_item"]:
        problems.append(f"{after['with_parent_item']} Items still sit beneath another Item")
    if after["live_items"] != before["live_items"] - folded_live:
        problems.append(
            f"{after['live_items']} live Items now, expected {before['live_items'] - folded_live}"
        )
    if problems:
        raise MigrationVerificationError(
            "The Nested Item conversion was stopped and rolled back: " + "; ".join(problems) + "."
        )


def migrate_nested(apps):
    """Apply the mapping to the database behind ``apps`` (historical or real models). Returns statistics.

    All or nothing: any error, including a failed count check, rolls every change back.
    """
    Item = apps.get_model("diary", "Item")
    Case = apps.get_model("diary", "Case")
    Note = apps.get_model("diary", "Note")
    NoteLink = apps.get_model("diary", "NoteLink")
    Batch = apps.get_model("diary", "TrashBatch")
    History = apps.get_model("diary", "VersionHistory")
    from django.utils import timezone

    stats = new_stats()
    stamp = timezone.now()

    def record(obj, kind_name):
        History.objects.create(
            record_type=kind_name, record_id=obj.pk, version=obj.version, snapshot=legacy._snapshot(obj),
            changed_by=None, profile_id=obj.profile_id, change_kind=CHANGE_KIND, group=None,
        )

    def place_of(item):
        """The Item that holds the Subject/Topic/Sub-topic place: this one, or the nearest ancestor that has one
        (an inner group sits beneath another Item and has no place of its own)."""
        seen = set()
        while all(getattr(item, f"{c}_id") is None for c in PARENT_COLUMNS) and item.parent_item_id is not None:
            if item.pk in seen:
                break
            seen.add(item.pk)
            item = Item._default_manager.get(pk=item.parent_item_id)
        return item

    with transaction.atomic():
        before = _count_state(Item, Case, Note, NoteLink)
        folded_live = 0
        all_folded = []
        parent_of = dict(Item._default_manager.filter(parent_item__isnull=False).values_list("pk", "parent_item_id"))
        nested_ids = list(Item._default_manager.filter(kind=KIND_NESTED).values_list("pk", flat=True))
        for parent_pk in conversion_order(parent_of, nested_ids):
            # Read fresh: an earlier group may have moved or trashed this Item.
            nested = Item._default_manager.get(pk=parent_pk)
            stats["nested_items"] += 1
            deleted = nested.deleted_at is not None
            kids = list(Item._default_manager.filter(parent_item_id=nested.pk).order_by("position", "pk"))

            def with_nested(kid):
                return kid.deleted_at is None or (deleted and nested.delete_batch is not None
                                                  and kid.delete_batch == nested.delete_batch)

            def moves(case):
                return case.deleted_at is None or (deleted and nested.delete_batch is not None
                                                   and case.delete_batch == nested.delete_batch)

            folded = [k for k in kids if with_nested(k)]
            all_folded.extend(k.pk for k in folded)
            kid_cases = {
                k.pk: [c for c in Case._default_manager.filter(item_id=k.pk).order_by("position", "pk") if moves(c)]
                for k in folded
            }
            children = []
            for k in folded:
                children.append({
                    "id": k.pk, "text": k.text, "flag": k.flag, "flag_text": k.flag_text,
                    "needs_review": k.needs_review, "review_note": k.review_note,
                    "cases": [_case_dict(c) for c in kid_cases[k.pk]],
                    "notes": Note._default_manager.filter(item_id=k.pk).count(),
                    "links": NoteLink._default_manager.filter(item_id=k.pk).count(),
                })
            own_cases = [c for c in Case._default_manager.filter(item_id=nested.pk, deleted_at__isnull=True)
                         .order_by("position", "pk")]
            plan = plan_group(
                {"citation": nested.citation, "review_note": nested.review_note, "needs_review": nested.needs_review,
                 "cases": [_case_dict(c) for c in own_cases]},
                children,
            )
            cases_before = Case._default_manager.filter(item_id=nested.pk).count()
            moving_cases = {c.pk: c for cs in kid_cases.values() for c in cs}
            # 1. the Cases of N, in the planned order.
            made = moved = 0
            for number, spec in enumerate(plan.cases, start=1):
                comment_plain = plain_text(spec.comment)
                if spec.existing_id is None:
                    case = Case(
                        profile_id=nested.profile_id, item_id=nested.pk, citation=spec.citation,
                        comment=spec.comment, comment_plain=comment_plain, position=number,
                        deleted_at=nested.deleted_at, delete_batch=nested.delete_batch,
                        created_by_id=nested.created_by_id, updated_by_id=nested.updated_by_id, version=1,
                    )
                    case.save()
                    made += 1
                else:
                    case = moving_cases.get(spec.existing_id) or next(c for c in own_cases if c.pk == spec.existing_id)
                    case.item_id = nested.pk
                    case.comment = spec.comment
                    case.comment_plain = comment_plain
                    case.position = number
                    if case.pk in moving_cases and deleted:
                        case.deleted_at, case.delete_batch = nested.deleted_at, nested.delete_batch
                    case.version += 1
                    Case._default_manager.filter(pk=case.pk).update(
                        item_id=case.item_id, comment=case.comment, comment_plain=case.comment_plain,
                        position=case.position, deleted_at=case.deleted_at, delete_batch=case.delete_batch,
                        version=case.version,
                    )
                    moved += int(case.pk in moving_cases)
                record(case, "case")
            stats["cases_created"] += made
            stats["cases_moved"] += moved
            if Case._default_manager.filter(item_id=nested.pk).count() != cases_before + made + moved:
                raise MigrationVerificationError(
                    f"Nested Item {nested.pk} has the wrong number of citations after the conversion."
                )
            # 2. Notes and Note links of the folded children.
            batch = None
            if folded:
                batch = Batch.objects.create(
                    id=uuid.uuid4(), profile_id=nested.profile_id, root_type="item", root_id=folded[0].pk,
                    label=f"{BATCH_LABEL}: {plain_text(nested.text)[:60]}"[:500], created_by_id=None,
                )
            next_note = 1 + max(
                [n.position for n in Note._default_manager.filter(item_id=nested.pk, deleted_at__isnull=True)] or [0]
            )
            for k in folded:
                for note in Note._default_manager.filter(item_id=k.pk).order_by("position", "pk"):
                    note.item_id = nested.pk
                    if note.deleted_at is None:
                        note.position = next_note
                        next_note += 1
                    note.version += 1
                    Note._default_manager.filter(pk=note.pk).update(
                        item_id=note.item_id, position=note.position, version=note.version
                    )
                    record(note, "note")
                    stats["notes_moved"] += 1
                for link in NoteLink._default_manager.filter(item_id=k.pk).order_by("pk"):
                    link.item_id = nested.pk
                    link.version += 1
                    NoteLink._default_manager.filter(pk=link.pk).update(item_id=link.item_id, version=link.version)
                    record(link, "notelink")
                    stats["links_retargeted"] += 1
            # 3. N itself.
            nested.kind = KIND_PLAIN
            nested.citation = ""
            nested.citation_layout = plan.layout
            nested.needs_review = plan.needs_review
            nested.review_note = plan.review_note
            nested.version += 1
            # A queryset update leaves updated_at and updated_by alone: this is a data move, not an edit.
            Item._default_manager.filter(pk=nested.pk).update(
                kind=nested.kind, citation=nested.citation, citation_layout=nested.citation_layout,
                needs_review=nested.needs_review, review_note=nested.review_note, version=nested.version,
            )
            record(nested, "item")
            # 4. The children: out of the Nested Item (a parent of its own), folded ones into Trash.
            for k in kids:
                is_folded = k in folded
                place = place_of(nested)
                for column in PARENT_COLUMNS:
                    setattr(k, f"{column}_id", getattr(place, f"{column}_id"))
                k.parent_item_id = None
                k.position = nested.position
                if is_folded:
                    if k.deleted_at is None:
                        k.deleted_at = stamp
                        folded_live += 1
                    k.delete_batch = batch.id
                    stats["children_folded"] += 1
                else:
                    stats["children_left_in_trash"] += 1
                k.version += 1
                Item._default_manager.filter(pk=k.pk).update(
                    subject_id=k.subject_id, topic_id=k.topic_id, subtopic_id=k.subtopic_id, parent_item_id=None,
                    position=k.position, deleted_at=k.deleted_at, delete_batch=k.delete_batch, version=k.version,
                )
                record(k, "item")
            stats["empty_children"] += len(plan.empty_children)
        # Safety sweep (cycles, anything unforeseen): detach what is still attached, keeping its state, so no
        # Item is lost and the parent column can be dropped. Trashed Items stay in Trash.
        for left in list(Item._default_manager.filter(parent_item__isnull=False)):
            up = Item._default_manager.filter(pk=left.parent_item_id).first()
            if up is not None:
                up = place_of(up)
                for column in PARENT_COLUMNS:
                    setattr(left, f"{column}_id", getattr(up, f"{column}_id"))
            left.parent_item_id = None
            left.version += 1
            Item._default_manager.filter(pk=left.pk).update(
                subject_id=left.subject_id, topic_id=left.topic_id, subtopic_id=left.subtopic_id,
                parent_item_id=None, version=left.version,
            )
            record(left, "item")
            stats["children_left_in_trash"] += 1
        after = _count_state(Item, Case, Note, NoteLink)
        verify_counts(before, after, stats, folded_live)
        stuck_notes = Note._default_manager.filter(item_id__in=all_folded).count()
        stuck_links = NoteLink._default_manager.filter(item_id__in=all_folded).count()
        if stuck_notes or stuck_links:
            raise MigrationVerificationError(
                "The Nested Item conversion was stopped and rolled back: a folded sub-item still has "
                f"{stuck_notes} Note(s) and {stuck_links} link(s)."
            )
    if stats["nested_items"]:
        logger.warning(describe(stats))
    return stats


# ------------------------------------------------------------------ backup files (the restore)

def upgrade_document_nested(models_in_file, stamp):
    """Map Nested Items in a parsed backup ``models`` dict to the current shape, in place. Returns statistics.

    Same rules as ``migrate_nested``. New rows get primary keys above the file's highest. The removed
    columns (``Item.parent_item``, ``UserSettings.nested_item_format``) are dropped from every record so the
    file loads into the current models. A file already in the current shape is not changed.
    """
    stats = new_stats()
    items = models_in_file.get("diary.Item", [])
    for record in models_in_file.get("diary.UserSettings", []):
        record["fields"].pop("nested_item_format", None)
    kids_of = defaultdict(list)
    parent_of = {}
    for record in items:
        parent = record["fields"].get("parent_item")
        if parent is not None:
            kids_of[parent].append(record)
            parent_of[record["pk"]] = parent
    by_key = {r["pk"]: r for r in items}
    order = conversion_order(
        parent_of, [r["pk"] for r in items if r["fields"].get("kind") == KIND_NESTED]
    )
    nested_records = [by_key[pk] for pk in order if pk in by_key]
    cases = models_in_file.setdefault("diary.Case", [])
    notes = models_in_file.setdefault("diary.Note", [])
    links = models_in_file.setdefault("diary.NoteLink", [])
    history = models_in_file.setdefault("diary.VersionHistory", [])
    cases_of, notes_of, links_of = defaultdict(list), defaultdict(list), defaultdict(list)
    for record in cases:
        cases_of[record["fields"].get("item")].append(record)
    for record in notes:
        notes_of[record["fields"].get("item")].append(record)
    for record in links:
        links_of[record["fields"].get("item")].append(record)
    by_pos = lambda r: (r["fields"].get("position", 0), r["pk"])  # noqa: E731
    next_case, next_history = legacy._next_pk(cases), legacy._next_pk(history)
    rows = {"case": next_case, "history": next_history}

    def log(record_type, record_id, fields, fks, profile):
        pk = rows["history"]
        rows["history"] += 1
        history.append(legacy._history_record(
            pk, record_type, record_id, fields.get("version", 1), legacy._record_snapshot(record_id, fields, fks),
            profile, stamp,
        ))

    def place_fields(record):
        seen = set()
        while all(record["fields"].get(c) is None for c in PARENT_COLUMNS):
            up = parent_of.get(record["pk"])
            if up is None or up in seen or up not in by_key:
                break
            seen.add(record["pk"])
            record = by_key[up]
        return record["fields"]

    for nested in nested_records:
        stats["nested_items"] += 1
        fields = nested["fields"]
        profile = fields.get("profile")
        deleted = bool(fields.get("deleted_at"))
        batch_of_n = fields.get("delete_batch")

        def same_batch(record):
            return deleted and batch_of_n is not None and record["fields"].get("delete_batch") == batch_of_n

        kids = sorted(kids_of.get(nested["pk"], []), key=by_pos)
        folded = [k for k in kids if not k["fields"].get("deleted_at") or same_batch(k)]
        kid_cases = {
            k["pk"]: sorted(
                (c for c in cases_of.get(k["pk"], []) if not c["fields"].get("deleted_at") or same_batch(c)), key=by_pos
            )
            for k in folded
        }
        children = [{
            "id": k["pk"], "text": k["fields"].get("text", ""), "flag": k["fields"].get("flag", "none"),
            "flag_text": k["fields"].get("flag_text", ""), "needs_review": k["fields"].get("needs_review", False),
            "review_note": k["fields"].get("review_note", ""),
            "cases": [{"id": c["pk"], "citation": c["fields"].get("citation", ""), "comment": c["fields"].get("comment", "")}
                      for c in kid_cases[k["pk"]]],
            "notes": len(notes_of.get(k["pk"], [])), "links": len(links_of.get(k["pk"], [])),
        } for k in folded]
        own = sorted((c for c in cases_of.get(nested["pk"], []) if not c["fields"].get("deleted_at")), key=by_pos)
        plan = plan_group(
            {"citation": fields.get("citation", "") or "", "review_note": fields.get("review_note", ""),
             "needs_review": fields.get("needs_review", False),
             "cases": [{"id": c["pk"], "citation": c["fields"].get("citation", ""), "comment": c["fields"].get("comment", "")}
                       for c in own]},
            children,
        )
        by_id = {c["pk"]: c for cs in kid_cases.values() for c in cs}
        by_id.update({c["pk"]: c for c in own})
        for number, spec in enumerate(plan.cases, start=1):
            comment_plain = plain_text(spec.comment)
            if spec.existing_id is None:
                case_fields = {
                    "created_at": stamp, "updated_at": stamp, "deleted_at": fields.get("deleted_at"),
                    "delete_batch": batch_of_n, "version": 1, "created_by": fields.get("created_by"),
                    "updated_by": fields.get("updated_by"), "profile": profile, "item": nested["pk"],
                    "citation": spec.citation, "comment": spec.comment, "comment_plain": comment_plain,
                    "position": number,
                }
                case_pk = rows["case"]
                rows["case"] += 1
                new_case = {"model": "diary.case", "pk": case_pk, "fields": case_fields}
                cases.append(new_case)
                cases_of[nested["pk"]].append(new_case)  # an outer group may fold this Item later
                stats["cases_created"] += 1
            else:
                case = by_id[spec.existing_id]
                case_pk, case_fields = case["pk"], case["fields"]
                if case_fields.get("item") != nested["pk"]:
                    stats["cases_moved"] += 1
                if case_fields.get("item") != nested["pk"]:
                    cases_of[case_fields.get("item")].remove(case)
                    cases_of[nested["pk"]].append(case)
                case_fields.update(item=nested["pk"], comment=spec.comment, comment_plain=comment_plain, position=number)
                if spec.existing_id in {c["pk"] for cs in kid_cases.values() for c in cs} and deleted:
                    case_fields.update(deleted_at=fields.get("deleted_at"), delete_batch=batch_of_n)
                case_fields["version"] = case_fields.get("version", 1) + 1
            log("case", case_pk, case_fields, CASE_FKS, profile)
        batch_pk = None
        if folded:
            batch_pk = str(uuid.uuid4())
            # Trash batches are optional in a backup file (an older file has none): the list is made only when needed.
            models_in_file.setdefault("diary.TrashBatch", []).append({
                "model": "diary.trashbatch", "pk": batch_pk,
                "fields": {
                    "profile": profile, "root_type": "item", "root_id": folded[0]["pk"],
                    "label": f"{BATCH_LABEL}: {plain_text(fields.get('text', ''))[:60]}"[:500],
                    "created_at": stamp, "created_by": None,
                },
            })
        live_notes = [n["fields"].get("position", 0) for n in notes_of.get(nested["pk"], [])
                      if not n["fields"].get("deleted_at")]
        next_note = 1 + max(live_notes or [0])
        for k in folded:
            for note in sorted(notes_of.get(k["pk"], []), key=by_pos):
                notes_of[nested["pk"]].append(note)
                note["fields"]["item"] = nested["pk"]
                if not note["fields"].get("deleted_at"):
                    note["fields"]["position"] = next_note
                    next_note += 1
                note["fields"]["version"] = note["fields"].get("version", 1) + 1
                log("note", note["pk"], note["fields"], NOTE_FKS, profile)
                stats["notes_moved"] += 1
            for link in sorted(links_of.get(k["pk"], []), key=lambda r: r["pk"]):
                links_of[nested["pk"]].append(link)
                link["fields"]["item"] = nested["pk"]
                link["fields"]["version"] = link["fields"].get("version", 1) + 1
                log("notelink", link["pk"], link["fields"], LINK_FKS, profile)
                stats["links_retargeted"] += 1
        fields["kind"] = KIND_PLAIN
        fields["citation"] = ""
        fields["citation_layout"] = plan.layout
        fields["needs_review"] = plan.needs_review
        fields["review_note"] = plan.review_note
        fields["version"] = fields.get("version", 1) + 1
        fields.pop("parent_item", None)
        log("item", nested["pk"], fields, ITEM_FKS, profile)
        for k in kids:
            kf = k["fields"]
            place = place_fields(nested)
            for column in PARENT_COLUMNS:
                kf[column] = place.get(column)
            kf["position"] = fields.get("position", 0)
            if k in folded:
                kf["deleted_at"] = kf.get("deleted_at") or stamp
                kf["delete_batch"] = batch_pk
                stats["children_folded"] += 1
            else:
                stats["children_left_in_trash"] += 1
            kf["version"] = kf.get("version", 1) + 1
            kf["parent_item"] = None
            log("item", k["pk"], {key: v for key, v in kf.items() if key != "parent_item"}, ITEM_FKS, profile)
        stats["empty_children"] += len(plan.empty_children)
    for record in items:
        record["fields"].pop("parent_item", None)
        if record["fields"].get("kind") not in (None, KIND_PLAIN):
            record["fields"]["kind"] = KIND_PLAIN
    return stats
