from django.db import migrations, models


def _fields():
    return [
        ("original_line", models.TextField(blank=True)),
        ("import_ref", models.CharField(blank=True, max_length=100)),
    ]


class Migration(migrations.Migration):
    """Word import (Milestone 2): the exact Word line and its source on every level, not only Items."""

    dependencies = [
        ("diary", "0006_profile_required"),
    ]

    operations = [
        migrations.AddField(model_name=model, name=name, field=field)
        for model in ("subject", "topic", "subtopic", "section")
        for name, field in _fields()
    ]
