from django.db import migrations, models


def switch_on(apps, schema_editor):
    """Pruning is automatic now: existing settings rows get it on, with 5 years of daily detail kept."""
    apps.get_model("investments", "PriceHistorySettings").objects.update(prune_live=True, prune_archive=True, years_kept=5)


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0028_remove_twelvedata"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pricehistorysettings",
            name="prune_live",
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name="pricehistorysettings",
            name="prune_archive",
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(switch_on, migrations.RunPython.noop),
    ]
