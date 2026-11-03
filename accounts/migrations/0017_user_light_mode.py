from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0016_resetrequest"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="light_mode",
            field=models.BooleanField(default=False),
        ),
    ]
