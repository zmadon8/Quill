from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0031_user_home_metrics"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="home_details",
            field=models.JSONField(blank=True, default=dict, verbose_name="Home page extras"),
        ),
    ]
