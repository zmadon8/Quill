"""Turn every Sub-topic that sits directly under a Subject (no Topic above it) into a Topic (docs/DESIGN.md D81).

Before D81 the Subjects listed under "Other Subjects" held Sub-topics straight under the Subject, one level shallower than
the regular Subjects (Subject > Topic > Sub-topic). Each such Sub-topic becomes a Topic of the same Subject, with the same
name; its Items, Sections and Notes go with it in the same order, links from other Notes are pointed at the new Topic, and the
old Sub-topic goes to the Trash. That is exactly what **Promote** does for one Sub-topic (``levels.promote``), done for all of
them at once, in ONE Undo group and all or nothing: the counts of Items, Sections, Cases, Notes and links are checked at the
end and any mismatch rolls everything back.

Used by ``manage.py convert_direct_subtopics``. Running it again finds nothing to do.
"""
from django.db import transaction

from ..models import Case, Item, Note, NoteLink, Section, Subtopic, Topic
from . import levels
from .core import action_group


class ConversionMismatch(Exception):
    """A count changed that must not change; everything was rolled back."""


def direct_subtopics(profile):
    """The live Sub-topics of live Subjects with no Topic above them, A to Z by Subject then name."""
    return list(
        Subtopic.objects.filter(
            profile=profile, deleted_at__isnull=True, topic__isnull=True,
            subject__isnull=False, subject__deleted_at__isnull=True,
        ).select_related("subject").order_by("subject__name", "name", "pk")
    )


def plan(profile):
    """[(Subject name, [(Sub-topic name, live Items directly in it)])] for the dry run."""
    rows = {}
    for sub in direct_subtopics(profile):
        items = Item.objects.filter(profile=profile, subtopic_id=sub.pk, deleted_at__isnull=True).count()
        rows.setdefault(sub.subject.name, []).append((sub.name, items))
    return list(rows.items())


def _counts(profile):
    live = {"profile": profile, "deleted_at__isnull": True}
    return {
        "items": Item.objects.filter(**live).count(),
        "sections": Section.objects.filter(**live).count(),
        "cases": Case.objects.filter(**live).count(),
        "notes": Note.objects.filter(**live).count(),
        "links": NoteLink.objects.filter(**live).count(),
    }


def convert(profile, user):
    """Convert every direct Sub-topic of ``profile`` to a Topic. Returns {"converted": n, "topics_after": n}.

    Raises ConversionMismatch (after rolling back) if any count that must stay the same changed.
    """
    with transaction.atomic(), action_group():
        subs = direct_subtopics(profile)
        if not subs:
            return {"converted": 0, "topics_after": Topic.objects.filter(profile=profile, deleted_at__isnull=True).count()}
        before = _counts(profile)
        topics_before = Topic.objects.filter(profile=profile, deleted_at__isnull=True).count()
        ids = [s.pk for s in subs]
        for sub in subs:
            levels.promote(profile, user, "subtopic", sub.pk)
        after = _counts(profile)
        if after != before:
            raise ConversionMismatch(f"counts changed: before {before}, after {after}")
        topics_after = Topic.objects.filter(profile=profile, deleted_at__isnull=True).count()
        if topics_after != topics_before + len(subs):
            raise ConversionMismatch(f"expected {topics_before + len(subs)} Topics, found {topics_after}")
        if direct_subtopics(profile):
            raise ConversionMismatch("some direct Sub-topics are still there")
        dangling = NoteLink.objects.filter(
            profile=profile, deleted_at__isnull=True, subtopic_id__in=ids, subtopic__deleted_at__isnull=False
        ).count()
        if dangling:
            raise ConversionMismatch(f"{dangling} link(s) still point at an old Sub-topic")
        return {"converted": len(subs), "topics_after": topics_after}
