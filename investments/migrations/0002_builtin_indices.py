from django.db import migrations

# Mirrors investments.services.masters.BUILTIN_INDICES (kept as a copy so the migration never changes with the code).
INDICES = [
    ("Nifty 50", "^NSEI", "INR"), ("Sensex", "^BSESN", "INR"), ("Nifty Next 50", "^NSMIDCP", "INR"), ("Nifty Bank", "^NSEBANK", "INR"),
    ("Nifty Midcap 150", "NIFTYMIDCAP150.NS", "INR"), ("Nifty Smallcap 250", "NIFTYSMLCAP250.NS", "INR"), ("Nifty IT", "^CNXIT", "INR"),
    ("S&P 500", "^GSPC", "USD"),
]


def add_indices(apps, schema_editor):
    Instrument = apps.get_model("investments", "Instrument")
    for name, code, currency in INDICES:
        Instrument.objects.get_or_create(
            profile=None, kind="index", code=code,
            defaults={"name": name, "currency": currency, "asset_class": "equity", "price_source": "yahoo"})


class Migration(migrations.Migration):
    dependencies = [("investments", "0001_initial")]
    operations = [migrations.RunPython(add_indices, migrations.RunPython.noop)]
