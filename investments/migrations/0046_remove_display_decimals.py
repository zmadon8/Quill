from django.db import migrations


class Migration(migrations.Migration):
    """Owner round 2026-11: Settings > Display no longer sets the decimals of units and full rupee figures; both show up to 2 decimals
    with trailing zeros dropped, as the Fee Register."""

    dependencies = [
        ("investments", "0045_drop_duplicate_price_index"),
    ]

    operations = [
        migrations.RemoveField(model_name="investmentsettings", name="units_decimals"),
        migrations.RemoveField(model_name="investmentsettings", name="rupee_decimals"),
    ]
