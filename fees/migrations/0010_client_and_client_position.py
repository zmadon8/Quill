import django.db.models.deletion
import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):
    """Owner round 2026-11: the free-text "client" on matters and memos is the Client Position (renamed, data kept), and a matter may now
    name a Client from a list kept per profile (optional; blank for every existing matter)."""

    dependencies = [
        ("accounts", "0035_remove_profile_reading_all_default"),
        ("fees", "0009_feeshistory"),
    ]

    operations = [
        migrations.RenameField(model_name="matter", old_name="client", new_name="client_position"),
        migrations.RenameField(model_name="memo", old_name="client", new_name="client_position"),
        migrations.CreateModel(
            name="Client",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.profile")),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        django.db.models.functions.text.Lower("name"), models.F("profile"), name="fees_client_name_unique_per_profile"
                    ),
                ],
            },
        ),
        migrations.AddField(
            model_name="matter",
            name="client",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="matters", to="fees.client"
            ),
        ),
    ]
