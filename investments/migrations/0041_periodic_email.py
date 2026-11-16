from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """The report emails (Investments > Settings > Email reports): weekly, monthly, quarterly and annual, to chosen users of the profile."""

    dependencies = [
        ("accounts", "0035_remove_profile_reading_all_default"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("investments", "0040_remove_profileinvestment_hidden"),
    ]
    operations = [
        migrations.CreateModel(
            name="PeriodicEmail",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("weekly", models.BooleanField(default=False)),
                ("monthly", models.BooleanField(default=False)),
                ("quarterly", models.BooleanField(default=False)),
                ("annual", models.BooleanField(default=False)),
                ("weekly_last_end", models.DateField(blank=True, null=True)),
                ("monthly_last_end", models.DateField(blank=True, null=True)),
                ("quarterly_last_end", models.DateField(blank=True, null=True)),
                ("annual_last_end", models.DateField(blank=True, null=True)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("last_ok", models.BooleanField(blank=True, null=True)),
                ("last_message", models.CharField(blank=True, default="", max_length=500)),
                ("profile", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.profile")),
            ],
        ),
        migrations.CreateModel(
            name="PeriodicEmailRecipient",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.profile")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("profile", "user"), name="inv_periodic_recipient_unique")],
            },
        ),
    ]
