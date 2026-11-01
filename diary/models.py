"""Diary data model (docs/DESIGN.md sections 2, 3, 7, 9.1 and 11).

Numbers (A, 1, (i) and so on) are never stored: they are generated from
position. Parents are separate optional links with a database rule that exactly
one is filled (section 3.1). Nothing is removed by the system except through
"Delete permanently"; deleting sets ``deleted_at``.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from .constraints import exactly_one, not_blank
from .richtext import plain_text, sanitise_html

# Number formats (section 4). Sections get one more style, "Section 1, Section 2".
FORMAT_CHOICES = [
    ("upper_alpha", "A, B, C"),
    ("lower_alpha", "a, b, c"),
    ("decimal", "1, 2, 3"),
    ("upper_roman", "I, II, III"),
    ("lower_roman", "i, ii, iii"),
    ("paren_upper_alpha", "(A), (B), (C)"),
    ("paren_lower_roman", "(i), (ii), (iii)"),
    ("paren_lower_alpha", "(a), (b), (c)"),
    ("paren_decimal", "(1), (2), (3)"),
    ("bullet", "Bullet"),
    ("none", "None"),
]
SECTION_FORMAT_CHOICES = FORMAT_CHOICES + [("section_n", "Section 1, Section 2")]

KIND_PLAIN = "plain"
KIND_MULTI = "multi"
KIND_NESTED = "nested"
KIND_CHOICES = [
    (KIND_PLAIN, "Item"),
    (KIND_MULTI, "Multi-Item"),
    (KIND_NESTED, "Nested Item"),
]

FLAG_NONE = "none"
FLAG_CHOICES = [
    (FLAG_NONE, "None"),
    ("overruled", "Overruled"),
    ("doubted", "Doubted"),
    ("other", "Other"),
]

OPENING_PAGE_CHOICES = [
    ("home", "Home"),
    ("other_subjects", "Other Subjects"),
    ("search", "Global Search"),
    ("last", "Last page viewed"),
    ("subject", "A chosen Subject"),
]

DATE_FORMAT_CHOICES = [
    ("YYYY-MM-DD", "YYYY-MM-DD"),
    ("DD-MM-YYYY", "DD-MM-YYYY"),
    ("D Month YYYY", "D Month YYYY"),
]

CHANGE_KIND_CHOICES = [
    ("create", "Create"),
    ("edit", "Edit"),
    ("move", "Move"),
    ("reorder", "Reorder"),
    ("delete", "Delete"),
    ("restore", "Restore"),
    ("convert", "Convert"),
    ("import", "Import"),
]


class Record(models.Model):
    """Fields every diary record carries (section 3)."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        abstract = True

    @property
    def is_deleted(self):
        return self.deleted_at is not None


class RichTextMixin:
    """Keeps the sanitised HTML and its plain-text copy in step on save (section 3.3).

    ``rich_fields`` maps each rich field to the field holding its plain copy.
    """

    rich_fields = {}

    def save(self, *args, **kwargs):
        changed = set()
        for field, plain_field in self.rich_fields.items():
            clean = sanitise_html(getattr(self, field))
            setattr(self, field, clean)
            setattr(self, plain_field, plain_text(clean))
            changed.update((field, plain_field))
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | changed
        super().save(*args, **kwargs)


class Subject(Record):
    name = models.CharField(max_length=300)
    position = models.PositiveIntegerField(default=0)
    show_on_landing = models.BooleanField(default=True)
    landing_position = models.PositiveIntegerField(default=0)
    other_acts_position = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=not_blank("name"), name="subject_name_not_blank"),
            models.UniqueConstraint(
                Lower("name"),
                condition=Q(deleted_at__isnull=True),
                name="subject_name_unique_live",
            ),
        ]

    def __str__(self):
        return self.name


class Topic(Record):
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="topics")
    name = models.CharField(max_length=300)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=not_blank("name"), name="topic_name_not_blank"),
        ]

    def __str__(self):
        return self.name


class Subtopic(Record):
    topic = models.ForeignKey(Topic, null=True, blank=True, on_delete=models.CASCADE, related_name="subtopics")
    subject = models.ForeignKey(
        Subject, null=True, blank=True, on_delete=models.CASCADE, related_name="direct_subtopics"
    )
    name = models.CharField(max_length=300)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=not_blank("name"), name="subtopic_name_not_blank"),
            models.CheckConstraint(
                condition=exactly_one(["topic", "subject"]), name="subtopic_exactly_one_parent"
            ),
        ]

    def __str__(self):
        return self.name


class Section(Record):
    subject = models.ForeignKey(Subject, null=True, blank=True, on_delete=models.CASCADE, related_name="sections")
    topic = models.ForeignKey(Topic, null=True, blank=True, on_delete=models.CASCADE, related_name="sections")
    subtopic = models.ForeignKey(Subtopic, null=True, blank=True, on_delete=models.CASCADE, related_name="sections")
    name = models.CharField(max_length=500, blank=True)
    position = models.PositiveIntegerField(default=0)
    needs_review = models.BooleanField(default=False)
    review_note = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=exactly_one(["subject", "topic", "subtopic"]), name="section_exactly_one_parent"
            ),
        ]

    def __str__(self):
        return self.name


class Item(RichTextMixin, Record):
    rich_fields = {"text": "text_plain"}

    subject = models.ForeignKey(Subject, null=True, blank=True, on_delete=models.CASCADE, related_name="items")
    topic = models.ForeignKey(Topic, null=True, blank=True, on_delete=models.CASCADE, related_name="items")
    subtopic = models.ForeignKey(Subtopic, null=True, blank=True, on_delete=models.CASCADE, related_name="items")
    parent_item = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_PLAIN)
    text = models.TextField(blank=True)
    text_plain = models.TextField(blank=True, editable=False)
    citation = models.CharField(max_length=1000, blank=True)
    flag = models.CharField(max_length=10, choices=FLAG_CHOICES, default=FLAG_NONE)
    flag_text = models.CharField(max_length=300, blank=True)
    needs_review = models.BooleanField(default=False)
    review_note = models.TextField(blank=True)
    position = models.PositiveIntegerField(default=0)
    original_line = models.TextField(blank=True)
    import_ref = models.CharField(max_length=100, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=exactly_one(["subject", "topic", "subtopic", "parent_item"]),
                name="item_exactly_one_parent",
            ),
            # One level of nesting: the children of a Nested Item are plain Items (section 2.2).
            models.CheckConstraint(
                condition=Q(parent_item__isnull=True) | Q(kind=KIND_PLAIN),
                name="item_child_of_nested_is_plain",
            ),
            # A Multi-Item has no citation of its own; its Cases hold the citations (section 3.2).
            models.CheckConstraint(
                condition=~Q(kind=KIND_MULTI) | Q(citation=""),
                name="item_multi_has_no_citation",
            ),
        ]

    def clean(self):
        super().clean()
        if self.citation and ("\n" in self.citation or "\r" in self.citation):
            raise ValidationError({"citation": "A citation must be a single line."})
        if self.parent_item_id is not None and self.parent_item.kind != KIND_NESTED:
            raise ValidationError({"parent_item": "Items can only sit beneath a Nested Item."})

    def __str__(self):
        return self.text_plain[:60] or f"Item {self.pk}"


class Case(RichTextMixin, Record):
    """One citation of a Multi-Item, with an optional rich-text comment."""

    rich_fields = {"comment": "comment_plain"}

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="cases")
    citation = models.CharField(max_length=1000, blank=True)
    comment = models.TextField(blank=True)
    comment_plain = models.TextField(blank=True, editable=False)
    position = models.PositiveIntegerField(default=0)

    def clean(self):
        super().clean()
        if self.item_id is not None and self.item.kind != KIND_MULTI:
            raise ValidationError({"item": "Cases are only allowed under a Multi-Item."})
        if self.citation and ("\n" in self.citation or "\r" in self.citation):
            raise ValidationError({"citation": "A citation must be a single line."})

    def __str__(self):
        return self.citation


class Note(RichTextMixin, Record):
    rich_fields = {"text": "text_plain"}

    subject = models.ForeignKey(Subject, null=True, blank=True, on_delete=models.CASCADE, related_name="notes")
    topic = models.ForeignKey(Topic, null=True, blank=True, on_delete=models.CASCADE, related_name="notes")
    subtopic = models.ForeignKey(Subtopic, null=True, blank=True, on_delete=models.CASCADE, related_name="notes")
    item = models.ForeignKey(Item, null=True, blank=True, on_delete=models.CASCADE, related_name="notes")
    section = models.ForeignKey(Section, null=True, blank=True, on_delete=models.CASCADE, related_name="notes")
    text = models.TextField(blank=True)
    text_plain = models.TextField(blank=True, editable=False)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=exactly_one(["subject", "topic", "subtopic", "item", "section"]),
                name="note_exactly_one_parent",
            ),
        ]

    def __str__(self):
        return self.text_plain[:60] or f"Note {self.pk}"


class NoteLink(Record):
    """A cross-reference from a Note to one target. Never removed by the system (section 7)."""

    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="links")
    subject = models.ForeignKey(
        Subject, null=True, blank=True, on_delete=models.PROTECT, related_name="incoming_links"
    )
    topic = models.ForeignKey(Topic, null=True, blank=True, on_delete=models.PROTECT, related_name="incoming_links")
    subtopic = models.ForeignKey(
        Subtopic, null=True, blank=True, on_delete=models.PROTECT, related_name="incoming_links"
    )
    section = models.ForeignKey(
        Section, null=True, blank=True, on_delete=models.PROTECT, related_name="incoming_links"
    )
    item = models.ForeignKey(Item, null=True, blank=True, on_delete=models.PROTECT, related_name="incoming_links")

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=exactly_one(["subject", "topic", "subtopic", "section", "item"]),
                name="notelink_exactly_one_target",
            ),
        ]


class UserSettings(models.Model):
    """Per-user settings (section 5.11)."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="diary_settings")
    opening_page = models.CharField(max_length=20, choices=OPENING_PAGE_CHOICES, default="home")
    opening_subject = models.ForeignKey(Subject, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    topic_format = models.CharField(max_length=20, choices=FORMAT_CHOICES, default="upper_alpha")
    subtopic_format = models.CharField(max_length=20, choices=FORMAT_CHOICES, default="decimal")
    section_format = models.CharField(max_length=20, choices=SECTION_FORMAT_CHOICES, default="paren_lower_alpha")
    item_format = models.CharField(max_length=20, choices=FORMAT_CHOICES, default="paren_decimal")
    nested_item_format = models.CharField(max_length=20, choices=FORMAT_CHOICES, default="paren_decimal")
    multi_citation_format = models.CharField(max_length=20, choices=FORMAT_CHOICES, default="paren_lower_alpha")
    export_custom_name = models.CharField(max_length=60, default="Judgment Diary")
    export_date_format = models.CharField(max_length=20, choices=DATE_FORMAT_CHOICES, default="YYYY-MM-DD")
    time_zone = models.CharField(max_length=64, default="Asia/Kolkata")

    class Meta:
        verbose_name_plural = "user settings"

    def __str__(self):
        return f"Settings for {self.user_id}"


class VersionHistory(models.Model):
    """One full snapshot of one record at one version (section 9.1)."""

    record_type = models.CharField(max_length=30)
    record_id = models.BigIntegerField()
    version = models.PositiveIntegerField()
    snapshot = models.JSONField(default=dict)
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    change_kind = models.CharField(max_length=10, choices=CHANGE_KIND_CHOICES)

    class Meta:
        verbose_name_plural = "version history"
        indexes = [models.Index(fields=["record_type", "record_id", "version"], name="versionhist_record_idx")]

    def __str__(self):
        return f"{self.record_type} {self.record_id} v{self.version}"
