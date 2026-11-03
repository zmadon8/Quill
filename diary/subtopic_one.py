"""Sub-topics live in a Topic: the one-off mapping for records already stored (docs/DESIGN.md, D82).

Owner (round 14): "for any sub-topic which sits directly under a Subject, automatically create a parent Topic for it called
'1'." This is the Sub-topic twin of ``diary/topic_one.py`` (which does the same for Items and Sections). New records are
housed by the service layer (``diary/services/housing.py``). This module houses the ones that exist already, and the ones in
an OLD backup file:

  * every Sub-topic whose parent is a SUBJECT moves into that Subject's Topic named "1" (an existing live Topic "1" is
    reused, otherwise one is made. It copies the Subject's trash state, so restoring a Subject from Trash brings it back);
  * one Topic "1" per Subject, not one per Sub-topic: it is the same Topic that loose Items and Sections are housed in;
  * a Subject whose direct Sub-topics are all in Trash is left alone (Restore houses them later);
  * the Sub-topics keep their order (the stored Word order continues after any Sub-topic already in Topic "1"; they are
    shown alphabetically anyway), their Items, Sections and Notes, and every id, so links and addresses keep working;
  * every changed record gets a "migrate" history row and a version bump, nothing is deleted, and the counts are checked
    inside the transaction (any mismatch rolls it all back).

It runs BEFORE ``topic_one`` wherever both run, so Items that sat loose under such a Subject (which ``topic_one`` leaves
alone while the Subject holds Sub-topics directly) are then housed in the same Topic "1".

Used by data migration ``diary.0018_house_direct_subtopics`` (``migrate_direct``), by ``manage.py house_loose_items`` and by
the backup loader (``house_document``), so an OLD backup file is mapped exactly as the live database is. Like the other
mapping modules it imports no models and nothing from the service layer, so the frozen migration does not depend on live code.
"""
import logging
from collections import defaultdict

from django.db import transaction

from . import legacy_merge as legacy
from .topic_one import CHANGE_KIND, TOPIC_FKS, TOPIC_NAME

logger = logging.getLogger(__name__)

SUBTOPIC_FKS = frozenset({"profile", "created_by", "updated_by", "subject", "topic"})
MigrationVerificationError = legacy.MigrationVerificationError


def new_stats():
    return {"subjects_housed": 0, "topics_made": 0, "topics_reused": 0, "subtopics_moved": 0}


def describe(stats):
    if not stats["subtopics_moved"]:
        return ""
    return (
        f"Older data format mapped: {stats['subtopics_moved']} Sub-topic(s) that sat directly under a Subject are now in a "
        f"Topic called \"{TOPIC_NAME}\" ({stats['topics_made']} Topic(s) made, {stats['topics_reused']} reused)."
    )


# ------------------------------------------------------------------ live database (the migration)

def _counts(Subtopic, Topic):
    return {"subtopics": Subtopic._default_manager.count(), "topics": Topic._default_manager.count()}


def migrate_direct(apps):
    """Apply the mapping to the database behind ``apps`` (historical or real models). Returns statistics.

    All or nothing: any error, including a failed count check, rolls every change back.
    """
    Subject = apps.get_model("diary", "Subject")
    Subtopic = apps.get_model("diary", "Subtopic")
    Topic = apps.get_model("diary", "Topic")
    History = apps.get_model("diary", "VersionHistory")
    stats = new_stats()

    def record(obj, kind_name):
        History.objects.create(
            record_type=kind_name, record_id=obj.pk, version=obj.version, snapshot=legacy._snapshot(obj),
            changed_by=None, profile_id=obj.profile_id, change_kind=CHANGE_KIND, group=None,
        )

    with transaction.atomic():
        before = _counts(Subtopic, Topic)
        holders = sorted(set(Subtopic._default_manager.filter(subject_id__isnull=False).values_list("subject_id", flat=True)))
        for subject in list(Subject._default_manager.filter(pk__in=holders).order_by("pk")):
            direct = list(Subtopic._default_manager.filter(subject_id=subject.pk).order_by("position", "pk"))
            if not any(sub.deleted_at is None for sub in direct):
                continue  # only trashed ones: Restore houses them if they ever come back
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
            there = Subtopic._default_manager.filter(topic_id=topic.pk).values_list("position", flat=True)
            next_position = 1 + max(there, default=0)
            for sub in direct:
                sub.position = next_position
                next_position += 1
                sub.subject_id, sub.topic_id = None, topic.pk
                sub.version += 1
                # A queryset update leaves updated_at and updated_by alone: this is a data move, not an edit.
                Subtopic._default_manager.filter(pk=sub.pk).update(
                    subject_id=None, topic_id=topic.pk, position=sub.position, version=sub.version
                )
                record(sub, "subtopic")
                stats["subtopics_moved"] += 1
            left = Subtopic._default_manager.filter(subject_id=subject.pk, deleted_at__isnull=True).count()
            if left:
                raise MigrationVerificationError(
                    f"The Sub-topic housing was stopped and rolled back: Subject {subject.pk} still has {left} direct Sub-topic(s)."
                )
        after = _counts(Subtopic, Topic)
        problems = []
        if after["subtopics"] != before["subtopics"]:
            problems.append(f"Sub-topic count changed from {before['subtopics']} to {after['subtopics']}")
        if after["topics"] != before["topics"] + stats["topics_made"]:
            problems.append(f"Topic count is {after['topics']}, expected {before['topics'] + stats['topics_made']}")
        if problems:
            raise MigrationVerificationError("The Sub-topic housing was stopped and rolled back: " + "; ".join(problems) + ".")
    if stats["subtopics_moved"]:
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
    history = models_in_file.setdefault("diary.VersionHistory", [])
    direct = defaultdict(list)
    for record in subtopics:
        subject = record["fields"].get("subject")
        if subject is not None:
            direct[subject].append(record)
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
        here = direct.get(subject["pk"], [])
        if not any(not r["fields"].get("deleted_at") for r in here):
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
        there = [r["fields"].get("position", 0) for r in subtopics if r["fields"].get("topic") == topic["pk"]]
        next_position = 1 + max(there, default=0)
        for record in sorted(here, key=lambda r: (r["fields"].get("position", 0), r["pk"])):
            fields = record["fields"]
            fields["position"] = next_position
            next_position += 1
            fields["subject"], fields["topic"] = None, topic["pk"]
            fields["version"] = fields.get("version", 1) + 1
            log("subtopic", record, SUBTOPIC_FKS)
            stats["subtopics_moved"] += 1
    return stats
