from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0023_user_last_seen_can_see_active"),
    ]

    operations = [
        migrations.AlterField(
            model_name="profile",
            name="reading_all_mode",
            field=models.CharField(
                choices=[
                    ("always_on", "The Whole Subject"),
                    ("always_off", "Only That Topic Or Sub-topic"),
                    ("remember", "The View I Used Last"),
                ],
                default="remember",
                max_length=10,
            ),
        ),
    ]
