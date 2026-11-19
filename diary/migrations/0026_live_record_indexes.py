from django.db import migrations, models


class Migration(migrations.Migration):
    """Indexes for the queries that always ask for live (not trashed) records in one place: reading, search and reordering."""

    dependencies = [
        ("diary", "0025_usersettings_multi_citation_lines_format"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="section",
            index=models.Index(
                fields=["subtopic", "position"],
                name="section_subtopic_live_idx",
                condition=models.Q(("deleted_at__isnull", True)),
            ),
        ),
        migrations.AddIndex(
            model_name="section",
            index=models.Index(
                fields=["topic", "position"],
                name="section_topic_live_idx",
                condition=models.Q(("deleted_at__isnull", True)),
            ),
        ),
        migrations.AddIndex(
            model_name="section",
            index=models.Index(
                fields=["subject", "position"],
                name="section_subject_live_idx",
                condition=models.Q(("deleted_at__isnull", True)),
            ),
        ),
        migrations.AddIndex(
            model_name="section",
            index=models.Index(
                fields=["profile"],
                name="section_profile_live_idx",
                condition=models.Q(("deleted_at__isnull", True)),
            ),
        ),
        migrations.AddIndex(
            model_name="item",
            index=models.Index(
                fields=["subtopic", "position"],
                name="item_subtopic_live_idx",
                condition=models.Q(("deleted_at__isnull", True)),
            ),
        ),
        migrations.AddIndex(
            model_name="item",
            index=models.Index(
                fields=["topic", "position"],
                name="item_topic_live_idx",
                condition=models.Q(("deleted_at__isnull", True)),
            ),
        ),
        migrations.AddIndex(
            model_name="item",
            index=models.Index(
                fields=["subject", "position"],
                name="item_subject_live_idx",
                condition=models.Q(("deleted_at__isnull", True)),
            ),
        ),
        migrations.AddIndex(
            model_name="item",
            index=models.Index(
                fields=["profile"],
                name="item_profile_live_idx",
                condition=models.Q(("deleted_at__isnull", True)),
            ),
        ),
        migrations.AddIndex(
            model_name="note",
            index=models.Index(
                fields=["subtopic", "position"],
                name="note_subtopic_live_idx",
                condition=models.Q(("deleted_at__isnull", True)),
            ),
        ),
        migrations.AddIndex(
            model_name="note",
            index=models.Index(
                fields=["topic", "position"],
                name="note_topic_live_idx",
                condition=models.Q(("deleted_at__isnull", True)),
            ),
        ),
        migrations.AddIndex(
            model_name="note",
            index=models.Index(
                fields=["subject", "position"],
                name="note_subject_live_idx",
                condition=models.Q(("deleted_at__isnull", True)),
            ),
        ),
        migrations.AddIndex(
            model_name="note",
            index=models.Index(
                fields=["item", "position"],
                name="note_item_live_idx",
                condition=models.Q(("deleted_at__isnull", True)),
            ),
        ),
        migrations.AddIndex(
            model_name="note",
            index=models.Index(
                fields=["section", "position"],
                name="note_section_live_idx",
                condition=models.Q(("deleted_at__isnull", True)),
            ),
        ),
        migrations.AddIndex(
            model_name="note",
            index=models.Index(
                fields=["profile"],
                name="note_profile_live_idx",
                condition=models.Q(("deleted_at__isnull", True)),
            ),
        ),
        migrations.AddIndex(
            model_name="case",
            index=models.Index(
                fields=["item", "position"],
                name="case_item_live_idx",
                condition=models.Q(("deleted_at__isnull", True)),
            ),
        ),
        migrations.AddIndex(
            model_name="case",
            index=models.Index(
                fields=["profile"],
                name="case_profile_live_idx",
                condition=models.Q(("deleted_at__isnull", True)),
            ),
        ),
        migrations.AddIndex(
            model_name="versionhistory",
            index=models.Index(fields=["profile", "changed_by", "changed_at"], name="versionhist_user_idx"),
        ),
    ]
