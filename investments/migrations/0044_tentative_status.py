from django.db import migrations, models


def awaiting_to_tentative(apps, schema_editor):
    """The status "awaiting" (Awaiting allotment) is now "tentative" (Mark as Tentative). The History is never edited: a snapshot that still says
    "awaiting" is mapped when its entry is restored (``history.restore``)."""
    apps.get_model("investments", "Transaction").objects.filter(status="awaiting").update(status="tentative")


def tentative_to_awaiting(apps, schema_editor):
    apps.get_model("investments", "Transaction").objects.filter(status="tentative").update(status="awaiting")


class Migration(migrations.Migration):
    """Awaiting allotment becomes a general Tentative status: new labels, and existing rows are converted (reversibly)."""

    dependencies = [("investments", "0043_instrument_capital_gains")]

    operations = [
        migrations.AlterField(
            model_name="transaction",
            name="status",
            field=models.CharField(
                choices=[("final", "Final"), ("tentative", "Tentative"), ("pending_sip", "SIP, to confirm")], default="final", max_length=12
            ),
        ),
        migrations.AlterField(
            model_name="transaction",
            name="amount",
            field=models.DecimalField(
                blank=True,
                decimal_places=4,
                help_text="Tentative entries: the amount paid (purchase) or expected proceeds (sale)",
                max_digits=20,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="investmentsettings",
            name="awaiting_treatment",
            field=models.CharField(
                choices=[("cost", "Count at cost"), ("leave_out", "Leave out until finalised")], default="cost", max_length=10
            ),
        ),
        migrations.RunPython(awaiting_to_tentative, tentative_to_awaiting),
    ]
