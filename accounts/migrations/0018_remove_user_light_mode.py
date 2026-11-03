from django.db import migrations


class Migration(migrations.Migration):
    """The Light version was withdrawn (docs/DESIGN.md D81); its switch is removed again."""

    dependencies = [
        ("accounts", "0017_user_light_mode"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="user",
            name="light_mode",
        ),
    ]
