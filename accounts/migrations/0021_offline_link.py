import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounts", "0020_deleted_users_and_several_profiles"),
    ]

    operations = [
        migrations.CreateModel(
            name="OfflineLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token", models.CharField(max_length=64)),
                ("token_hash", models.CharField(max_length=64, unique=True)),
                ("enabled", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("copy_data", models.BinaryField(blank=True, null=True)),
                ("copy_name", models.CharField(blank=True, max_length=255)),
                ("copy_made_at", models.DateTimeField(blank=True, null=True)),
                ("copy_items", models.PositiveIntegerField(default=0)),
                ("copy_size", models.PositiveIntegerField(default=0)),
                ("copy_error", models.CharField(blank=True, max_length=300)),
                (
                    "made_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "profile",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="offline_link",
                        to="accounts.profile",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="OfflineDownload",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ip", models.CharField(blank=True, max_length=64)),
                ("at", models.DateTimeField(db_index=True)),
                (
                    "link",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="accounts.offlinelink",
                    ),
                ),
            ],
        ),
    ]
