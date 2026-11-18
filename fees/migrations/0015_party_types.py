from django.db import migrations, models

import fees.models


class Migration(migrations.Migration):
    """Owner round 2026-12: the Plaintiff type and Defendant type drop-down lists, one pair per profile (existing profiles get the initial lists)."""

    dependencies = [("fees", "0014_client_firm_required")]

    operations = [
        migrations.AddField(
            model_name="feessettings",
            name="plaintiff_types",
            field=models.JSONField(blank=True, default=fees.models.default_plaintiff_types),
        ),
        migrations.AddField(
            model_name="feessettings",
            name="defendant_types",
            field=models.JSONField(blank=True, default=fees.models.default_defendant_types),
        ),
    ]
