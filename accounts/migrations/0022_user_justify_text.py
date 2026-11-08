from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0021_offline_link"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="justify_text",
            field=models.BooleanField(default=False),
        ),
    ]
