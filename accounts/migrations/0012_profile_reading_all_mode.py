from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0011_user_landing_program"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="reading_all_mode",
            field=models.CharField(
                choices=[
                    ("always_on", "Always ticked"),
                    ("always_off", "Always unticked"),
                    ("remember", "Remember each user's choice"),
                ],
                default="remember",
                max_length=10,
            ),
        ),
    ]
