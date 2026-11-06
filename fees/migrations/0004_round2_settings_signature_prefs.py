import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounts", "0021_offline_link"),
        ("fees", "0003_memo_date_nullable"),
    ]

    operations = [
        migrations.AddField(
            model_name="memo",
            name="include_signature",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="feessettings",
            name="memo_signature_default",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="feessettings",
            name="list_default_filter",
            field=models.CharField(default="all", max_length=10),
        ),
        migrations.AlterField(
            model_name="feessettings",
            name="default_court_name",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AlterField(
            model_name="memo",
            name="court_name",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AlterField(
            model_name="matter",
            name="court_name",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.CreateModel(
            name="FeesUserPrefs",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("key", models.CharField(max_length=60)),
                ("data", models.JSONField(default=dict)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="accounts.profile",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("profile", "user", "key"),
                        name="fees_userprefs_unique_per_profile_user_key",
                    ),
                ],
            },
        ),
    ]
