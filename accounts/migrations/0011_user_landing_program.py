from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0010_profile_reading_all_default"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="landing_program",
            field=models.CharField(blank=True, default="", max_length=30),
        ),
    ]
