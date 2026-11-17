from django.db import migrations, models


def taxed_to_capital_gains(apps, schema_editor):
    """Capital Gains is the opposite of the old Taxed as Interest flag: old on -> off, old off -> on."""
    Instrument = apps.get_model("investments", "Instrument")
    Instrument.objects.filter(taxed_as_interest=True).update(capital_gains=False)
    Instrument.objects.filter(taxed_as_interest=False).update(capital_gains=True)


def capital_gains_to_taxed(apps, schema_editor):
    Instrument = apps.get_model("investments", "Instrument")
    Instrument.objects.filter(capital_gains=False).update(taxed_as_interest=True)
    Instrument.objects.filter(capital_gains=True).update(taxed_as_interest=False)


class Migration(migrations.Migration):
    """Every investment has a Capital Gains checkbox (on by default) in place of Taxed as Interest. Off means the gain is Other income."""

    dependencies = [("investments", "0042_periodicemail_templates")]

    operations = [
        migrations.AddField(
            model_name="instrument",
            name="capital_gains",
            field=models.BooleanField(default=True, help_text="Profit or loss on sales is Capital Gains; when off it is Other income"),
        ),
        migrations.RunPython(taxed_to_capital_gains, capital_gains_to_taxed),
        migrations.RemoveField(model_name="instrument", name="taxed_as_interest"),
    ]
