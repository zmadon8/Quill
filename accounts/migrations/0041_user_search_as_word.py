from django.db import migrations, models


class Migration(migrations.Migration):
    """Owner round 2026-11: a per-user choice to show the header's Search as a word on a button instead of the magnifier."""

    dependencies = [
        ("accounts", "0040_throttle_indexes"),
    ]

    operations = [
        migrations.AddField(model_name="user", name="search_as_word", field=models.BooleanField(default=False, verbose_name="Search as a word")),
    ]
