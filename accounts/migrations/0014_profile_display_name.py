from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0013_alter_profile_reading_all_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="display_name",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
    ]
