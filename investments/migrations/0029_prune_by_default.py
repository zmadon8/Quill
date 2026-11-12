from django.db import migrations, models


def switch_on(apps, schema_editor):
    """Pruning is automatic now: settings rows still holding the old defaults (off, nothing pruned yet) get it on with 5 years kept.
    A row an Admin changed (pruning switched on, or a different retention) is left alone."""
    model = apps.get_model("investments", "PriceHistorySettings")
    model.objects.filter(prune_live=False, prune_archive=False, last_prune_at__isnull=True).update(prune_live=True, prune_archive=True)


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
