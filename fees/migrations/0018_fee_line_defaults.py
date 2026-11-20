from django.db import migrations, models


def copy_single_switch(apps, schema_editor):
    FeesSettings = apps.get_model("fees", "FeesSettings")
    for row in FeesSettings.objects.all().only("pk", "default_lines_enabled"):
        on = row.default_lines_enabled
        FeesSettings.objects.filter(pk=row.pk).update(default_line_appearances=on, default_line_conferences=on, default_line_misc=on)


class Migration(migrations.Migration):
    """Owner round 2026-11: Settings > Memos has one "on in a new memo" switch per fee line (Appearances, Conferences, Drafts / Misc)
    instead of one for all; each starts as the old switch was."""

    dependencies = [
        ("fees", "0017_memo_list_index"),
    ]

    operations = [
        migrations.AddField(model_name="feessettings", name="default_line_appearances", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="feessettings", name="default_line_conferences", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="feessettings", name="default_line_misc", field=models.BooleanField(default=True)),
        migrations.RunPython(copy_single_switch, migrations.RunPython.noop),
    ]
