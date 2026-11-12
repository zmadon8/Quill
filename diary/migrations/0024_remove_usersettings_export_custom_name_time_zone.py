from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("diary", "0023_title_case_choice_labels"),
    ]

    operations = [
        migrations.RemoveField(model_name="usersettings", name="export_custom_name"),
        migrations.RemoveField(model_name="usersettings", name="time_zone"),
    ]
