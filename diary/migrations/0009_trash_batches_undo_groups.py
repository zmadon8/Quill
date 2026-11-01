import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Trash batches and Undo groups (Milestone 3a): see docs/DESIGN.md sections 5.6, 5.7 and 9.1."""

    dependencies = [
        ("accounts", "0009_profile_export_name"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("diary", "0008_import_ref_unique"),
    ]

    operations = [
        migrations.AddField(
            model_name="subject",
            name="delete_batch",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="topic",
            name="delete_batch",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="subtopic",
            name="delete_batch",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="section",
            name="delete_batch",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="item",
            name="delete_batch",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="case",
            name="delete_batch",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="note",
            name="delete_batch",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="notelink",
            name="delete_batch",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="versionhistory",
            name="group",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.CreateModel(
            name="TrashBatch",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("root_type", models.CharField(max_length=30)),
                ("root_id", models.BigIntegerField()),
                ("label", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, related_name="+", to="accounts.profile"
                    ),
                ),
            ],
            options={"verbose_name_plural": "trash batches"},
        ),
    ]
