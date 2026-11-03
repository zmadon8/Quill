import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EmailBackupSchedule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("enabled", models.BooleanField(default=False)),
                ("frequency", models.CharField(choices=[("daily", "Every day"), ("weekly", "Every week"), ("monthly", "Every month")], default="weekly", max_length=10)),
                ("weekday", models.PositiveSmallIntegerField(choices=[(0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"), (4, "Friday"), (5, "Saturday"), (6, "Sunday")], default=0)),
                ("day_of_month", models.PositiveSmallIntegerField(default=1)),
                ("recipients", models.TextField(blank=True)),
                ("include_data", models.BooleanField(default=True)),
                ("include_word", models.BooleanField(default=True)),
                ("include_review", models.BooleanField(default=True)),
                ("owner", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("last_sent_at", models.DateTimeField(blank=True, null=True)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("last_ok", models.BooleanField(blank=True, null=True)),
                ("last_message", models.CharField(blank=True, max_length=500)),
            ],
        ),
    ]
