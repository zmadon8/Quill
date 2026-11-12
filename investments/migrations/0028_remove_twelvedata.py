from django.db import migrations, models

SOURCES = [
    ("manual", "Entered by hand"),
    ("yahoo", "Yahoo"),
    ("amfi", "AMFI"),
    ("mfapi", "mfapi.in"),
    ("upload", "Uploaded"),
]


def remove_twelvedata(apps, schema_editor):
    """Twelve Data is gone: its instruments get the default source for their kind (as ``fetch_defaults`` gives a new one), its fallback is
    cleared, and the rows kept for that source are deleted."""
    Instrument = apps.get_model("investments", "Instrument")
    for kind, source in (("share", "yahoo"), ("foreign", "yahoo"), ("index", "yahoo"), ("fund", "amfi")):
        Instrument.objects.filter(price_source="twelvedata", kind=kind).update(
            price_source=source, price_basis="split_adjusted" if source == "yahoo" else "")
    Instrument.objects.filter(price_source="twelvedata").update(price_source="manual", price_basis="")
    Instrument.objects.filter(fallback_source="twelvedata").update(fallback_source="")
    apps.get_model("investments", "DataSourceFormat").objects.filter(key="twelvedata").delete()
    apps.get_model("investments", "SourceSetting").objects.filter(source="twelvedata").delete()
    apps.get_model("investments", "SourceSymbol").objects.filter(source="twelvedata").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0027_datasourceformat"),
    ]

    operations = [
        migrations.RunPython(remove_twelvedata, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="instrument",
            name="fallback_source",
            field=models.CharField(blank=True, choices=SOURCES, default="", max_length=10),
        ),
        migrations.AlterField(
            model_name="instrument",
            name="price_source",
            field=models.CharField(choices=SOURCES, default="manual", max_length=10),
        ),
    ]
