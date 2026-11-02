from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0014_profile_display_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="last_diary_path",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
    ]
