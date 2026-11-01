import django.db.models.deletion
import django.db.models.functions.text
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q

from diary.constraints import exactly_one, not_blank

FORMATS = [
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
SECTION_FORMATS = FORMATS + [("section_n", "Section 1, Section 2")]


def auto_id():
    return ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"))


def record_fields():
    """The fields every diary record carries (the abstract ``Record`` model)."""
    user = {
        "blank": True,
        "null": True,
        "on_delete": django.db.models.deletion.SET_NULL,
        "related_name": "+",
        "to": settings.AUTH_USER_MODEL,
    }
    return [
        ("created_at", models.DateTimeField(auto_now_add=True)),
        ("updated_at", models.DateTimeField(auto_now=True)),
        ("deleted_at", models.DateTimeField(blank=True, null=True)),
        ("version", models.PositiveIntegerField(default=1)),
        ("created_by", models.ForeignKey(**user)),
        ("updated_by", models.ForeignKey(**user)),
    ]


def link(model, related_name, on_delete=django.db.models.deletion.CASCADE, optional=True):
    options = {"on_delete": on_delete, "related_name": related_name, "to": f"diary.{model}"}
    if optional:
        options.update(blank=True, null=True)
    return models.ForeignKey(**options)


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Subject",
            fields=[
                auto_id(),
                *record_fields(),
                ("name", models.CharField(max_length=300)),
                ("position", models.PositiveIntegerField(default=0)),
                ("show_on_landing", models.BooleanField(default=True)),
                ("landing_position", models.PositiveIntegerField(default=0)),
                ("other_acts_position", models.PositiveIntegerField(default=0)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(condition=not_blank("name"), name="subject_name_not_blank"),
                    models.UniqueConstraint(
                        django.db.models.functions.text.Lower("name"),
                        condition=Q(deleted_at__isnull=True),
                        name="subject_name_unique_live",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="Topic",
            fields=[
                auto_id(),
                *record_fields(),
                ("subject", link("Subject", "topics", optional=False)),
                ("name", models.CharField(max_length=300)),
                ("position", models.PositiveIntegerField(default=0)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(condition=not_blank("name"), name="topic_name_not_blank"),
                ],
            },
        ),
        migrations.CreateModel(
            name="Subtopic",
            fields=[
                auto_id(),
                *record_fields(),
                ("topic", link("Topic", "subtopics")),
                ("subject", link("Subject", "direct_subtopics")),
                ("name", models.CharField(max_length=300)),
                ("position", models.PositiveIntegerField(default=0)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(condition=not_blank("name"), name="subtopic_name_not_blank"),
                    models.CheckConstraint(
                        condition=exactly_one(["topic", "subject"]), name="subtopic_exactly_one_parent"
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="Section",
            fields=[
                auto_id(),
                *record_fields(),
                ("subject", link("Subject", "sections")),
                ("topic", link("Topic", "sections")),
                ("subtopic", link("Subtopic", "sections")),
                ("name", models.CharField(blank=True, max_length=500)),
                ("position", models.PositiveIntegerField(default=0)),
                ("needs_review", models.BooleanField(default=False)),
                ("review_note", models.TextField(blank=True)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=exactly_one(["subject", "topic", "subtopic"]), name="section_exactly_one_parent"
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="Item",
            fields=[
                auto_id(),
                *record_fields(),
                ("subject", link("Subject", "items")),
                ("topic", link("Topic", "items")),
                ("subtopic", link("Subtopic", "items")),
                ("parent_item", link("Item", "children")),
                (
                    "kind",
                    models.CharField(
                        choices=[("plain", "Item"), ("multi", "Multi-Item"), ("nested", "Nested Item")],
                        default="plain",
                        max_length=10,
                    ),
                ),
                ("text", models.TextField(blank=True)),
                ("text_plain", models.TextField(blank=True, editable=False)),
                ("citation", models.CharField(blank=True, max_length=1000)),
                (
                    "flag",
                    models.CharField(
                        choices=[("none", "None"), ("overruled", "Overruled"), ("doubted", "Doubted"), ("other", "Other")],
                        default="none",
                        max_length=10,
                    ),
                ),
                ("flag_text", models.CharField(blank=True, max_length=300)),
                ("needs_review", models.BooleanField(default=False)),
                ("review_note", models.TextField(blank=True)),
                ("position", models.PositiveIntegerField(default=0)),
                ("original_line", models.TextField(blank=True)),
                ("import_ref", models.CharField(blank=True, max_length=100)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=exactly_one(["subject", "topic", "subtopic", "parent_item"]),
                        name="item_exactly_one_parent",
                    ),
                    models.CheckConstraint(
                        condition=Q(parent_item__isnull=True) | Q(kind="plain"),
                        name="item_child_of_nested_is_plain",
                    ),
                    models.CheckConstraint(
                        condition=~Q(kind="multi") | Q(citation=""),
                        name="item_multi_has_no_citation",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="Case",
            fields=[
                auto_id(),
                *record_fields(),
                ("item", link("Item", "cases", optional=False)),
                ("citation", models.CharField(blank=True, max_length=1000)),
                ("comment", models.TextField(blank=True)),
                ("comment_plain", models.TextField(blank=True, editable=False)),
                ("position", models.PositiveIntegerField(default=0)),
            ],
        ),
        migrations.CreateModel(
            name="Note",
            fields=[
                auto_id(),
                *record_fields(),
                ("subject", link("Subject", "notes")),
                ("topic", link("Topic", "notes")),
                ("subtopic", link("Subtopic", "notes")),
                ("item", link("Item", "notes")),
                ("section", link("Section", "notes")),
                ("text", models.TextField(blank=True)),
                ("text_plain", models.TextField(blank=True, editable=False)),
                ("position", models.PositiveIntegerField(default=0)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=exactly_one(["subject", "topic", "subtopic", "item", "section"]),
                        name="note_exactly_one_parent",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="NoteLink",
            fields=[
                auto_id(),
                *record_fields(),
                ("note", link("Note", "links", optional=False)),
                ("subject", link("Subject", "incoming_links", django.db.models.deletion.PROTECT)),
                ("topic", link("Topic", "incoming_links", django.db.models.deletion.PROTECT)),
                ("subtopic", link("Subtopic", "incoming_links", django.db.models.deletion.PROTECT)),
                ("section", link("Section", "incoming_links", django.db.models.deletion.PROTECT)),
                ("item", link("Item", "incoming_links", django.db.models.deletion.PROTECT)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=exactly_one(["subject", "topic", "subtopic", "section", "item"]),
                        name="notelink_exactly_one_target",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="UserSettings",
            fields=[
                auto_id(),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="diary_settings",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "opening_page",
                    models.CharField(
                        choices=[
                            ("home", "Home"),
                            ("other_subjects", "Other Subjects"),
                            ("search", "Global Search"),
                            ("last", "Last page viewed"),
                            ("subject", "A chosen Subject"),
                        ],
                        default="home",
                        max_length=20,
                    ),
                ),
                (
                    "opening_subject",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="diary.subject",
                    ),
                ),
                ("topic_format", models.CharField(choices=FORMATS, default="upper_alpha", max_length=20)),
                ("subtopic_format", models.CharField(choices=FORMATS, default="decimal", max_length=20)),
                (
                    "section_format",
                    models.CharField(choices=SECTION_FORMATS, default="paren_upper_alpha", max_length=20),
                ),
                ("item_format", models.CharField(choices=FORMATS, default="paren_lower_roman", max_length=20)),
                ("nested_item_format", models.CharField(choices=FORMATS, default="paren_lower_roman", max_length=20)),
                (
                    "multi_citation_format",
                    models.CharField(choices=FORMATS, default="paren_lower_alpha", max_length=20),
                ),
                ("export_custom_name", models.CharField(default="Judgment Diary", max_length=60)),
                (
                    "export_date_format",
                    models.CharField(
                        choices=[
                            ("YYYY-MM-DD", "YYYY-MM-DD"),
                            ("DD-MM-YYYY", "DD-MM-YYYY"),
                            ("D Month YYYY", "D Month YYYY"),
                        ],
                        default="YYYY-MM-DD",
                        max_length=20,
                    ),
                ),
                ("time_zone", models.CharField(default="Asia/Kolkata", max_length=64)),
            ],
            options={"verbose_name_plural": "user settings"},
        ),
        migrations.CreateModel(
            name="VersionHistory",
            fields=[
                auto_id(),
                ("record_type", models.CharField(max_length=30)),
                ("record_id", models.BigIntegerField()),
                ("version", models.PositiveIntegerField()),
                ("snapshot", models.JSONField(default=dict)),
                ("changed_at", models.DateTimeField(auto_now_add=True)),
                (
                    "changed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "change_kind",
                    models.CharField(
                        choices=[
                            ("create", "Create"),
                            ("edit", "Edit"),
                            ("move", "Move"),
                            ("reorder", "Reorder"),
                            ("delete", "Delete"),
                            ("restore", "Restore"),
                            ("convert", "Convert"),
                            ("import", "Import"),
                        ],
                        max_length=10,
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "version history",
                "indexes": [models.Index(fields=["record_type", "record_id", "version"], name="versionhist_record_idx")],
            },
        ),
    ]
