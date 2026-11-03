from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0018_remove_user_light_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="header_style",
            field=models.CharField(choices=[("icons", "Icons"), ("words", "Words")], default="icons", max_length=10),
        ),
    ]
