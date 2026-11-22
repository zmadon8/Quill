from django.db import migrations, models


class Migration(migrations.Migration):
    """Owner round 2026-11: the investment type 'Share' is called 'Equity'. Only the label changes; the stored value stays "share", so no data moves."""

    dependencies = [
        ("investments", "0046_remove_display_decimals"),
    ]

    operations = [
        migrations.AlterField(
            model_name="instrument",
            name="kind",
            field=models.CharField(
                choices=[("share", "Equity"), ("fund", "Mutual fund"), ("alternative", "Alternative"), ("foreign", "Foreign"), ("index", "Index")],
                max_length=12,
            ),
        ),
    ]
