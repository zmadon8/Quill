import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Owner round 2026-12, step 1 of 3: a client will belong to one firm. Add the firm (empty for now) and drop the per-profile
    name rule, so step 2 can copy a client that more than one firm uses. Kept apart from the data step so no table is altered in the
    same transaction that rewrote its rows (PostgreSQL refuses that)."""

    dependencies = [("fees", "0011_optional_partner")]

    operations = [
        migrations.RemoveConstraint(model_name="client", name="fees_client_name_unique_per_profile"),
        migrations.AddField(
            model_name="client",
            name="firm",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE, related_name="clients", to="fees.firm"
            ),
        ),
    ]
