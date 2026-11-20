from django.db import migrations, models

import fees.models


class Migration(migrations.Migration):
    """Owner round 2026-11: the payment form's Mode is a drop-down (RTGS, NEFT, Cheque, UPI and Custom), its list edited in Settings."""

    dependencies = [
        ("fees", "0018_fee_line_defaults"),
    ]

    operations = [
        migrations.AddField(model_name="feessettings", name="payment_modes",
                            field=models.JSONField(blank=True, default=fees.models.default_payment_modes)),
    ]
