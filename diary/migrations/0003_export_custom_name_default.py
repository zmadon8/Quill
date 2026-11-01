from django.db import migrations, models


def to_new_default(apps, schema_editor):
    """Change only rows that still hold the old default name."""
    UserSettings = apps.get_model("diary", "UserSettings")
    UserSettings.objects.filter(export_custom_name="Judgment Diary").update(export_custom_name="Case Law Diary")


def to_old_default(apps, schema_editor):
    UserSettings = apps.get_model("diary", "UserSettings")
    UserSettings.objects.filter(export_custom_name="Case Law Diary").update(export_custom_name="Judgment Diary")


class Migration(migrations.Migration):
    dependencies = [
        ("diary", "0002_new_default_formats"),
    ]

    operations = [
        migrations.AlterField(
            model_name="usersettings",
            name="export_custom_name",
            field=models.CharField(default="Case Law Diary", max_length=60),
        ),
        migrations.RunPython(to_new_default, to_old_default),
    ]
