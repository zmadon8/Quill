"""Items live in a Topic: the one-off mapping for records already stored (docs/DESIGN.md, D61).

Owner (round 10, item 6): "Any items which are not housed in a Topic will automatically be housed in a topic called
\u201c1\u201d". New records are housed by the service layer (``diary/services/housing.py``). This module houses the ones
that exist already:

  * every Item and Section whose parent is a SUBJECT that holds no Sub-topic directly moves into that Subject's Topic
    named "1" (an existing live Topic "1" is reused, otherwise one is made, placed after the Subject's other Topics'
    stored positions; Topics are always shown alphabetically anyway). The new Topic copies the Subject's trash state,
    so restoring a Subject from Trash brings its Topic "1" back with it;
  * a Subject that holds Sub-topics directly (an Other Subject) cannot also hold Topics (section 2.1), so its loose
    Items and Sections stay where they are, and are only counted;
  * Items and Sections keep their order; their positions follow any records already in Topic "1". A record that is in
    Trash moves too (when the Subject has a live loose record) and keeps its own trash state;
  * Notes are not moved: a Note on a Subject is a note about the Subject itself;
  * every changed record gets a "migrate" history row and a version bump, nothing is deleted, and the counts are
    checked inside the transaction (any mismatch rolls it all back).

It is used by data migration ``diary.0017_house_loose_in_topic_one`` (``migrate_loose``) and by the backup loader
(``house_document``), so an OLD backup file is mapped exactly as the live database is. Like the other mapping modules
it imports no models and nothing from the service layer, so the frozen migration does not depend on live code.
"""
import logging
from collections import defaultdict

from django.db import transaction

from . import legacy_merge as legacy

logger = logging.getLogger(__name__)

TOPIC_NAME = "1"
CHANGE_KIND = "migrate"
TOPIC_FKS = frozenset({"profile", "created_by", "updated_by", "subject"})
ITEM_FKS = frozenset({"profile", "created_by", "updated_by", "subject", "topic", "subtopic"})
MigrationVerificationError = legacy.MigrationVerificationError


def run_order(position, is_section, pk):
    """Display order of the Items and Sections of one parent: position, Sections first on a tie, then id."""
    return (position, 0 if is_section else 1, pk)


def new_stats():
    return {"subjects_housed": 0, "topics_made": 0, "topics_reused": 0, "items_moved": 0, "sections_moved": 0,
            "left_under_subjects_with_subtopics": 0}


def describe(stats):
    if not (stats["items_moved"] or stats["sections_moved"]):
        return ""
    return (
        f"Older data format mapped: {stats['items_moved']} Item(s) and {stats['sections_moved']} Section(s) that sat "
        f"directly under a Subject are now in a Topic called \"{TOPIC_NAME}\" ({stats['topics_made']} Topic(s) made, "
        f"{stats['topics_reused']} reused)."
    )


# ------------------------------------------------------------------ live database (the migration)

def _counts(Item, Section, Topic):
    return {
        "items": Item._default_manager.count(),
        "sections": Section._default_manager.count(),
        "topics": Topic._default_manager.count(),
    }


def migrate_loose(apps):
    """Apply the mapping to the database behind ``apps`` (historical or real models). Returns statistics.

    All or nothing: any error, including a failed count check, rolls every change back.
    """
    Subject = apps.get_model("diary", "Subject")
    Subtopic = apps.get_model("diary", "Subtopic")
    Topic = apps.get_model("diary", "Topic")
    Section = apps.get_model("diary", "Section")
    Item = apps.get_model("diary", "Item")
    History = apps.get_model("diary", "VersionHistory")
    stats = new_stats()

    def record(obj, kind_name):
        History.objects.create(
            record_type=kind_name, record_id=obj.pk, version=obj.version, snapshot=legacy._snapshot(obj),
            changed_by=None, profile_id=obj.profile_id, change_kind=CHANGE_KIND, group=None,
        )

    with transaction.atomic():
        before = _counts(Item, Section, Topic)
        for subject in list(Subject._default_manager.order_by("pk")):
            loose = [("item", i) for i in Item._default_manager.filter(subject_id=subject.pk)] + [
                ("section", s) for s in Section._default_manager.filter(subject_id=subject.pk)
            ]
            live = [pair for pair in loose if pair[1].deleted_at is None]
            if not live:
                continue
            if Subtopic._default_manager.filter(subject_id=subject.pk, deleted_at__isnull=True).exists():
                stats["left_under_subjects_with_subtopics"] += len(live)
                continue
            topic = (
                Topic._default_manager.filter(subject_id=subject.pk, deleted_at__isnull=True, name__iexact=TOPIC_NAME)
                .order_by("pk").first()
            )
            if topic is None:
                top = max(Topic._default_manager.filter(subject_id=subject.pk).values_list("position", flat=True),
                          default=0)
                topic = Topic(
                    profile_id=subject.profile_id, subject_id=subject.pk, name=TOPIC_NAME, position=top + 1,
                    deleted_at=subject.deleted_at, delete_batch=subject.delete_batch, version=1,
                    created_by_id=None, updated_by_id=None,
                )
                topic.save()
                record(topic, "topic")
                stats["topics_made"] += 1
            else:
                stats["topics_reused"] += 1
            stats["subjects_housed"] += 1
            there = [o.position for o in Item._default_manager.filter(topic_id=topic.pk, deleted_at__isnull=True)]
            there += [o.position for o in Section._default_manager.filter(topic_id=topic.pk, deleted_at__isnull=True)]
            next_position = 1 + max(there, default=0)
            loose.sort(key=lambda pair: run_order(pair[1].position, pair[0] == "section", pair[1].pk))
            for kind_name, obj in loose:
                if obj.deleted_at is None:
                    obj.position = next_position
                    next_position += 1
                obj.subject_id, obj.topic_id = None, topic.pk
                obj.version += 1
                # A queryset update leaves updated_at and updated_by alone: this is a data move, not an edit.
                type(obj)._default_manager.filter(pk=obj.pk).update(
                    subject_id=None, topic_id=topic.pk, position=obj.position, version=obj.version
                )
                record(obj, kind_name)
                stats["items_moved" if kind_name == "item" else "sections_moved"] += 1
            left = (Item._default_manager.filter(subject_id=subject.pk, deleted_at__isnull=True).count()
                    + Section._default_manager.filter(subject_id=subject.pk, deleted_at__isnull=True).count())
            if left:
                raise MigrationVerificationError(
                    f"The Topic \"{TOPIC_NAME}\" housing was stopped and rolled back: Subject {subject.pk} still has "
                    f"{left} loose record(s)."
                )
        after = _counts(Item, Section, Topic)
        problems = []
        if after["items"] != before["items"]:
            problems.append(f"Item count changed from {before['items']} to {after['items']}")
        if after["sections"] != before["sections"]:
            problems.append(f"Section count changed from {before['sections']} to {after['sections']}")
        if after["topics"] != before["topics"] + stats["topics_made"]:
            problems.append(f"Topic count is {after['topics']}, expected {before['topics'] + stats['topics_made']}")
        if problems:
            raise MigrationVerificationError(
                "The Topic \"1\" housing was stopped and rolled back: " + "; ".join(problems) + "."
            )
    if stats["items_moved"] or stats["sections_moved"]:
        logger.warning(describe(stats))
    return stats


# ------------------------------------------------------------------ backup files (the restore)

def house_document(models_in_file, stamp):
    """Apply the same mapping to a parsed backup ``models`` dict, in place. Returns statistics.

    New Topics and history rows get primary keys above the file's highest. A file that is already housed is not changed.
    """
    stats = new_stats()
    subjects = models_in_file.get("diary.Subject", [])
    topics = models_in_file.setdefault("diary.Topic", [])
    subtopics = models_in_file.get("diary.Subtopic", [])
    items = models_in_file.get("diary.Item", [])
    sections = models_in_file.get("diary.Section", [])
    history = models_in_file.setdefault("diary.VersionHistory", [])
    direct = defaultdict(int)
    for record in subtopics:
        if record["fields"].get("subject") is not None and not record["fields"].get("deleted_at"):
            direct[record["fields"]["subject"]] += 1
    loose = defaultdict(list)
    for kind_name, records in (("item", items), ("section", sections)):
        for record in records:
            subject = record["fields"].get("subject")
            if subject is not None:
                loose[subject].append((kind_name, record))
    next_topic, next_history = legacy._next_pk(topics), legacy._next_pk(history)
    rows = {"history": next_history}

    def log(record_type, record, fks):
        pk = rows["history"]
        rows["history"] += 1
        fields = record["fields"]
        history.append(legacy._history_record(
            pk, record_type, record["pk"], fields.get("version", 1),
            legacy._record_snapshot(record["pk"], fields, fks), fields.get("profile"), stamp,
        ))

    for subject in sorted(subjects, key=lambda r: r["pk"]):
        rows_here = loose.get(subject["pk"], [])
        live = [pair for pair in rows_here if not pair[1]["fields"].get("deleted_at")]
        if not live:
            continue
        if direct.get(subject["pk"]):
            stats["left_under_subjects_with_subtopics"] += len(live)
            continue
        sf = subject["fields"]
        own_topics = [t for t in topics if t["fields"].get("subject") == subject["pk"]]
        topic = next((t for t in sorted(own_topics, key=lambda r: r["pk"])
                      if not t["fields"].get("deleted_at") and str(t["fields"].get("name", "")).lower() == TOPIC_NAME), None)
        if topic is None:
            topic = {"model": "diary.topic", "pk": next_topic, "fields": {
                "created_at": stamp, "updated_at": stamp, "deleted_at": sf.get("deleted_at"),
                "delete_batch": sf.get("delete_batch"), "version": 1, "created_by": None, "updated_by": None,
                "profile": sf.get("profile"), "subject": subject["pk"], "name": TOPIC_NAME,
                "position": 1 + max((t["fields"].get("position", 0) for t in own_topics), default=0),
                "original_line": "", "import_ref": "",
            }}
            next_topic += 1
            topics.append(topic)
            log("topic", topic, TOPIC_FKS)
            stats["topics_made"] += 1
        else:
            stats["topics_reused"] += 1
        stats["subjects_housed"] += 1
        there = [r["fields"].get("position", 0) for r in items + sections
                 if r["fields"].get("topic") == topic["pk"] and not r["fields"].get("deleted_at")]
        next_position = 1 + max(there, default=0)
        rows_here.sort(key=lambda pair: run_order(pair[1]["fields"].get("position", 0), pair[0] == "section", pair[1]["pk"]))
        for kind_name, record in rows_here:
            fields = record["fields"]
            if not fields.get("deleted_at"):
                fields["position"] = next_position
                next_position += 1
            fields["subject"], fields["topic"] = None, topic["pk"]
            fields["version"] = fields.get("version", 1) + 1
            log(kind_name, record, ITEM_FKS)
            stats["items_moved" if kind_name == "item" else "sections_moved"] += 1
    return stats
