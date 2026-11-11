from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0030_user_investments_period"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="home_metrics",
            field=models.JSONField(blank=True, default=dict, verbose_name="Home card figures"),
        ),
    ]
