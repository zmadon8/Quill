from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0015_user_last_diary_path"),
    ]

    operations = [
        migrations.CreateModel(
            name="ResetRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email_lower", models.CharField(db_index=True, max_length=254)),
                ("ip", models.CharField(blank=True, max_length=64)),
                ("at", models.DateTimeField(db_index=True)),
            ],
        ),
    ]
