from django.db import migrations, models


class Migration(migrations.Migration):
    """Round 10: how an Item with several citations shows them (inline, or on separate lines)."""

    dependencies = [
        ("diary", "0013_notelink_position"),
    ]

    operations = [
        migrations.AddField(
            model_name="item",
            name="citation_layout",
            field=models.CharField(
                choices=[("inline", "Inline"), ("lines", "On separate lines")], default="inline", max_length=10
            ),
        ),
    ]
