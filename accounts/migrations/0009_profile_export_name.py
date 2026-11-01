from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0008_profile_recovery"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="export_name",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
    ]
