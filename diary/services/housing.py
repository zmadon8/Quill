"""Items live in a Topic (round 10, docs/DESIGN.md D61).

Owner: "Any items which are not housed in a Topic will automatically be housed in a topic called \u201c1\u201d". So an Item
or Section that is added to, or moved to, or restored under a Subject goes into that Subject's Topic named "1" instead
(made on demand, reused when it exists). A Subject that holds Sub-topics directly (the Other Subjects) cannot also hold
Topics (section 2.1), so there the Item stays directly under the Subject. Notes are not housed: a Note on a Subject is
a note about the Subject itself.
"""
from django.db.models.functions import Lower

from ..models import Subtopic, Topic

TOPIC_ONE = "1"
#: Record types that are housed in a Topic when their parent would be a Subject.
HOUSED = ("item", "section")


def accepts_topics(ctx, subject_id):
    """True if the Subject holds no live Sub-topic directly, so it may hold Topics (and Topic "1")."""
    return not Subtopic._base_manager.filter(
        profile_id=ctx.profile_id, subject_id=subject_id, deleted_at__isnull=True
    ).exists()


def find_topic_one(ctx, subject_id):
    return (
        Topic._base_manager.filter(profile_id=ctx.profile_id, subject_id=subject_id, deleted_at__isnull=True)
        .annotate(lowered=Lower("name"))
        .filter(lowered=TOPIC_ONE)
        .order_by("pk")
        .first()
    )


def house_parent(ctx, parent, create=True):
    """The parent an Item or Section really gets: ("topic", id of Topic "1") for a Subject that takes Topics, else ``parent``.

    ``create=False`` (for previews) uses Topic "1" only if it already exists and otherwise returns ``parent`` unchanged.
    """
    if parent is None or parent[0] != "subject" or not accepts_topics(ctx, parent[1]):
        return parent
    topic = find_topic_one(ctx, parent[1])
    if topic is None:
        if not create:
            return parent
        from . import core
        from .records import create as create_record

        # The Topic is part of the same action as the Item, so it joins the same Undo group.
        token = core._shared_group.set(ctx.group)
        try:
            topic = create_record(ctx.profile, ctx.user, "topic", parent=("subject", parent[1]), name=TOPIC_ONE).record
        finally:
            core._shared_group.reset(token)
    return ("topic", topic.pk)
