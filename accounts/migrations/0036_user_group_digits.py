from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0035_remove_profile_reading_all_default"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="group_digits",
            field=models.BooleanField(default=True, verbose_name="Add commas while typing numbers"),
        ),
    ]
