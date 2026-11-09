from django.db import migrations


def set_basis(apps, schema_editor):
    apps.get_model("investments", "Instrument").objects.filter(kind="index", price_source="yahoo", price_basis="").update(price_basis="split_adjusted")


class Migration(migrations.Migration):
    dependencies = [("investments", "0003_prices")]
    operations = [migrations.RunPython(set_basis, migrations.RunPython.noop)]
