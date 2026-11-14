import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounts", "0021_offline_link"),
        ("fees", "0008_merge_dashboard_switches_personal_prefs"),
    ]

    operations = [
        migrations.CreateModel(
            name="FeesHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("at", models.DateTimeField(default=django.utils.timezone.now)),
                ("action", models.CharField(max_length=20)),
                ("object_type", models.CharField(max_length=20)),
                ("object_id", models.BigIntegerField(blank=True, null=True)),
                ("summary", models.CharField(blank=True, default="", max_length=300)),
                (
                    "profile",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.profile"),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "fees history",
                "ordering": ["-at", "-id"],
                "indexes": [models.Index(fields=["profile", "at"], name="fees_hist_profile_at_idx")],
            },
        ),
    ]
