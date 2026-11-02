from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0012_profile_reading_all_mode"),
    ]

    operations = [
        migrations.AlterField(
            model_name="profile",
            name="reading_all_mode",
            field=models.CharField(
                choices=[
                    ("always_on", "The whole Subject"),
                    ("always_off", "Only that Topic or Sub-topic"),
                    ("remember", "The view I used last"),
                ],
                default="remember",
                max_length=10,
            ),
        ),
    ]
