from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fees", "0004_round2_settings_signature_prefs"),
    ]

    operations = [
        migrations.AddField(
            model_name="feessettings",
            name="items_per_page",
            field=models.PositiveIntegerField(default=50),
        ),
    ]
