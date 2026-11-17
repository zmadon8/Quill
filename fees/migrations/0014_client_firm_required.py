import django.db.models.deletion
import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):
    """Owner round 2026-12, step 3 of 3: the firm is required, and a client name is unique within its firm (any case), like a Partner."""

    dependencies = [("fees", "0013_client_firm_data")]

    operations = [
        migrations.AlterField(
            model_name="client",
            name="firm",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="clients", to="fees.firm"),
        ),
        migrations.AddConstraint(
            model_name="client",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("name"), models.F("firm"), name="fees_client_name_unique_per_firm"
            ),
        ),
        migrations.AddIndex(
            model_name="client",
            index=models.Index(fields=["profile", "firm"], name="fees_client_profile_firm_idx"),
        ),
    ]
