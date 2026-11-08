from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0025_profile_header_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="profilemembership",
            name="last_seen_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
