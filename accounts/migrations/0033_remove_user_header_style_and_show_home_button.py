from django.db import migrations


class Migration(migrations.Migration):
    """The header always shows words (plus the fixed icons) and the Home button is always there, so both columns go."""

    dependencies = [
        ("accounts", "0032_user_home_details"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="user",
            name="header_style",
        ),
        migrations.RemoveField(
            model_name="user",
            name="show_home_button",
        ),
    ]
