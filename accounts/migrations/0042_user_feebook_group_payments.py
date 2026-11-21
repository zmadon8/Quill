from django.db import migrations, models


class Migration(migrations.Migration):
    """Owner round 2026-11: a per-user choice to show memos paid together by one payment as a single Feebook line."""

    dependencies = [
        ("accounts", "0041_user_search_as_word"),
    ]

    operations = [
        migrations.AddField(model_name="user", name="feebook_group_payments", field=models.BooleanField(default=False, verbose_name="Feebook: memos paid together on one line")),
    ]
