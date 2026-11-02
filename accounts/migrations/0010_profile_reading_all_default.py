from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0009_profile_export_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="reading_all_default",
            field=models.BooleanField(default=True),
        ),
    ]
