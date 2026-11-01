import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0007_remove_user_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="deleted_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="profilemembership",
            name="suspended",
            field=models.BooleanField(default=False),
        ),
        migrations.RemoveConstraint(
            model_name="profilemembership",
            name="membership_one_profile_per_program",
        ),
        migrations.AddConstraint(
            model_name="profilemembership",
            constraint=models.UniqueConstraint(
                condition=models.Q(("suspended", False)),
                fields=("user", "program"),
                name="membership_one_profile_per_program",
            ),
        ),
        migrations.CreateModel(
            name="PurgeLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ran_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("success", models.BooleanField(default=False)),
                ("message", models.TextField(blank=True)),
                ("counts", models.JSONField(blank=True, default=dict)),
            ],
        ),
    ]
