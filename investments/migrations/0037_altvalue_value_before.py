from django.db import migrations, models

TAG_BEFORE_SALE = "Before sale"
SALE_TAGS = ("From sale", "Remaining after a sale")


def move_before_sale_values(apps, schema_editor):
    """Lump Sum "Before sale" entries used to be saved on the day before the sale. Each one that sits on the day before a sale-tagged entry of
    the same investment becomes that sale entry's ``value_before`` and is deleted. Any other "Before sale" entry is left as it is."""
    AltValue = apps.get_model("investments", "AltValue")
    from datetime import timedelta

    for old in list(AltValue.objects.filter(note=TAG_BEFORE_SALE)):
        sale = AltValue.objects.filter(profile_id=old.profile_id, instrument_id=old.instrument_id, date=old.date + timedelta(days=1),
                                       note__in=SALE_TAGS).first()
        if sale is None:
            continue
        sale.value_before = old.total_value
        sale.save(update_fields=["value_before"])
        old.delete()


def restore_before_sale_rows(apps, schema_editor):
    """Reverse: each ``value_before`` becomes a "Before sale" entry on the day before again (unless that day already has an entry), then is emptied."""
    AltValue = apps.get_model("investments", "AltValue")
    from datetime import timedelta

    for sale in list(AltValue.objects.filter(value_before__isnull=False)):
        day = sale.date - timedelta(days=1)
        if not AltValue.objects.filter(profile_id=sale.profile_id, instrument_id=sale.instrument_id, date=day).exists():
            AltValue.objects.create(profile_id=sale.profile_id, instrument_id=sale.instrument_id, date=day, total_value=sale.value_before,
                                    note=TAG_BEFORE_SALE)
        sale.value_before = None
        sale.save(update_fields=["value_before"])


class Migration(migrations.Migration):
    dependencies = [("investments", "0036_instrument_lump_sum")]
    operations = [
        migrations.AddField(
            model_name="altvalue", name="value_before",
            field=models.DecimalField(blank=True, decimal_places=4, help_text="Lump Sum: the whole holding's value just before that day's sale",
                                      max_digits=20, null=True)),
        migrations.RunPython(move_before_sale_values, restore_before_sale_rows),
    ]
