"""Owner round (2026-11): Nifty 50 is the only built-in index. The seven others seeded by 0002 are removed with their prices and pins,
unless a profile uses one (as its Default Index or as an investment's sector index); one in use stays as an ordinary added index,
which can be deleted in Settings > Indices."""
from django.db import migrations

REMOVED = ("^BSESN", "^NSMIDCP", "^NSEBANK", "NIFTYMIDCAP150.NS", "NIFTYSMLCAP250.NS", "^CNXIT", "^GSPC")


def forwards(apps, schema_editor):
    Instrument = apps.get_model("investments", "Instrument")
    InvestmentSettings = apps.get_model("investments", "InvestmentSettings")
    ProfileInvestment = apps.get_model("investments", "ProfileInvestment")
    used = set(InvestmentSettings.objects.exclude(default_index=None).values_list("default_index_id", flat=True))
    used |= set(ProfileInvestment.objects.exclude(sectoral_index=None).values_list("sectoral_index_id", flat=True))
    Instrument.objects.filter(profile=None, kind="index", code__in=REMOVED).exclude(pk__in=used).delete()


class Migration(migrations.Migration):
    dependencies = [("investments", "0015_column_picker_and_overview")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
