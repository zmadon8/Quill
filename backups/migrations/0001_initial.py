import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="BackupFile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("kind", models.CharField(choices=[("daily", "Daily"), ("manual", "Manual"), ("pre_restore", "Before restore"), ("pre_migration", "Before update"), ("uploaded", "Uploaded")], max_length=20)),
                ("filename", models.CharField(max_length=200)),
                ("data", models.BinaryField()),
                ("size_bytes", models.BigIntegerField()),
                ("sha256", models.CharField(max_length=64)),
                ("record_counts", models.JSONField(blank=True, default=dict)),
                ("note", models.CharField(blank=True, max_length=255)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="BackupLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("kind", models.CharField(choices=[("daily", "Daily"), ("manual", "Manual"), ("pre_restore", "Before restore"), ("pre_migration", "Before update"), ("restore", "Restore"), ("prune", "Clean-up")], max_length=20)),
                ("success", models.BooleanField(default=False)),
                ("message", models.TextField(blank=True)),
                ("size_bytes", models.BigIntegerField(blank=True, null=True)),
                ("backup", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="backups.backupfile")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
