from django.db import migrations, models

BATCH = 1000


def fill(apps, schema_editor):
    """Read the plan and option out of every stored AMFI name, a batch at a time. Rows the parser finds nothing in are left alone."""
    from investments.services import fund_names

    model = apps.get_model("investments", "AmfiScheme")
    changed = []
    for row in model.objects.only("pk", "name").iterator(chunk_size=BATCH):
        _, row.plan, row.option = fund_names.parse(row.name)
        if row.plan or row.option:
            changed.append(row)
        if len(changed) >= BATCH:
            model.objects.bulk_update(changed, ["plan", "option"])
            changed = []
    if changed:
        model.objects.bulk_update(changed, ["plan", "option"])


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0029_prune_by_default"),
    ]

    operations = [
        migrations.AddField(
            model_name="amfischeme",
            name="plan",
            field=models.CharField(blank=True, default="", help_text="Direct or Regular, read from the name; blank when the name does not say", max_length=10),
        ),
        migrations.AddField(
            model_name="amfischeme",
            name="option",
            field=models.CharField(blank=True, default="", help_text="Growth, IDCW Payout, IDCW Reinvestment, Bonus ...; blank when the name does not say", max_length=40),
        ),
        migrations.RunPython(fill, migrations.RunPython.noop),
    ]
