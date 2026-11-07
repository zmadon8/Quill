from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0022_user_justify_text"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="last_seen_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="can_see_active",
            field=models.BooleanField(default=False, verbose_name="Can See Who Is Active"),
        ),
    ]
