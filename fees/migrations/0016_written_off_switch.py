from django.db import migrations, models


class Migration(migrations.Migration):
    """Owner round 2027-01: the Written Off feature can be switched off in Settings (on for every existing profile)."""

    dependencies = [("fees", "0015_party_types")]

    operations = [
        migrations.AddField(
            model_name="feessettings",
            name="written_off_enabled",
            field=models.BooleanField(default=True),
        ),
    ]
