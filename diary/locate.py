"""Where a record sits in the Diary: the ONE implementation shared by Search and the Review list.

``Tree.load(profile)`` reads the profile's Subjects, Topics and Sub-topics (deleted ones too, so that a record
below a Trash ancestor can be told from a live one) in three queries. ``Tree.place(subject_id, topic_id,
subtopic_id)`` then returns the ``Place`` of any record from its parent columns, or None when a heading above
it is deleted or missing.

``Place.order`` is the real position in the Diary: Subjects of the main list first (then Other Subjects),
alphabetically; inside a Subject the content directly under it, then its direct Sub-topics, then each Topic
with its own content and its Sub-topics. Callers append their own (position, pk) to it.
"""
from typing import NamedTuple

from .models import Subject, Subtopic, Topic
from .sorting import sort_key


class Heading(NamedTuple):
    kind: str  # "subject", "topic" or "subtopic"
    pk: int
    name: str
    deleted: bool
    key: tuple  # alphabetical sort key (diary/sorting.py)
    other: bool = False  # Subject only: listed under Other Subjects
    subject_id: int = None  # Topic, and a Sub-topic directly under a Subject
    topic_id: int = None  # Sub-topic under a Topic


class Place(NamedTuple):
    subject: Heading
    topic: Heading  # or None
    subtopic: Heading  # or None
    order: tuple

    @property
    def headings(self):
        return [h for h in (self.subject, self.topic, self.subtopic) if h is not None]

    @property
    def names(self):
        return [h.name for h in self.headings]


class Tree:
    def __init__(self, subjects, topics, subtopics):
        self.subjects = subjects
        self.topics = topics
        self.subtopics = subtopics
        self._places = {}

    @classmethod
    def load(cls, profile):
        subjects = {
            pk: Heading("subject", pk, name, deleted_at is not None, sort_key(name, pk), other=not show_on_landing)
            for pk, name, show_on_landing, deleted_at in Subject.objects.filter(profile=profile).values_list(
                "pk", "name", "show_on_landing", "deleted_at")
        }
        topics = {
            pk: Heading("topic", pk, name, deleted_at is not None, sort_key(name, pk), subject_id=subject_id)
            for pk, name, subject_id, deleted_at in Topic.objects.filter(profile=profile).values_list(
                "pk", "name", "subject_id", "deleted_at")
        }
        subtopics = {
            pk: Heading("subtopic", pk, name, deleted_at is not None, sort_key(name, pk),
                        subject_id=subject_id, topic_id=topic_id)
            for pk, name, subject_id, topic_id, deleted_at in Subtopic.objects.filter(profile=profile).values_list(
                "pk", "name", "subject_id", "topic_id", "deleted_at")
        }
        return cls(subjects, topics, subtopics)

    def place(self, subject_id=None, topic_id=None, subtopic_id=None):
        """The Place of a record whose parent columns are given, or None (deleted or missing heading above it)."""
        cache_key = (subject_id, topic_id, subtopic_id)
        if cache_key not in self._places:
            self._places[cache_key] = self._place(subject_id, topic_id, subtopic_id)
        return self._places[cache_key]

    def _place(self, subject_id, topic_id, subtopic_id):
        subtopic = topic = subject = None
        if subtopic_id is not None:
            subtopic = self.subtopics.get(subtopic_id)
            if subtopic is None:
                return None
            topic_id = topic_id or subtopic.topic_id
        if topic_id is not None:
            topic = self.topics.get(topic_id)
            if topic is None:
                return None
            subject_id = subject_id or topic.subject_id
        if subject_id is None and subtopic is not None:
            subject_id = subtopic.subject_id
        subject = self.subjects.get(subject_id)
        if subject is None or any(h.deleted for h in (subject, topic, subtopic) if h is not None):
            return None
        if topic is not None:
            place = (2, topic.key, subtopic.key if subtopic else ())
        elif subtopic is not None:
            place = (1, (), subtopic.key)
        else:
            place = (0, (), ())
        return Place(subject, topic, subtopic, (subject.other, subject.key, place))
