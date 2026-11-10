from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """Bonus shares, units from a split and shares received on a demerger as transactions, and demerger terms on the corporate action.

    Existing transactions become origin "purchase" and existing responses keep the automatic method, so nothing already recorded changes."""

    dependencies = [
        ("investments", "0017_decimals_settings"),
    ]

    operations = [
        migrations.AddField(
            model_name="transaction",
            name="origin",
            field=models.CharField(
                choices=[
                    ("purchase", "Purchase"),
                    ("bonus", "Bonus shares"),
                    ("split", "Split (units recorded at no cost)"),
                    ("demerger", "Received on a demerger"),
                    ("other", "Other, at no cost (gift, transfer in)"),
                ],
                default="purchase",
                help_text="How the units came to be held: bought, bonus, split, received on a demerger, or at no cost",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="transaction",
            name="corporate_action",
            field=models.ForeignKey(
                blank=True,
                help_text="The bonus, split or demerger these units belong to",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="investments.corporateaction",
            ),
        ),
        migrations.AlterField(
            model_name="corporateaction",
            name="kind",
            field=models.CharField(
                choices=[
                    ("split", "Split"),
                    ("bonus", "Bonus"),
                    ("demerger", "Demerger (shares in a new company)"),
                    ("other", "Other (merger, ...)"),
                ],
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="corporateaction",
            name="target_instrument",
            field=models.ForeignKey(
                blank=True,
                help_text="Demerger: the new company whose shares are received",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="demergers_in",
                to="investments.instrument",
            ),
        ),
        migrations.AddField(
            model_name="corporateaction",
            name="cost_percent_to_target",
            field=models.DecimalField(
                blank=True,
                decimal_places=4,
                help_text="Demerger: the share of the parent's cost, in percent, that moves to the new company's shares",
                max_digits=7,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="corporateactionresponse",
            name="method",
            field=models.CharField(
                choices=[
                    ("events", "Automatic: the program adds the units"),
                    ("transactions", "I record the units as transactions"),
                ],
                default="events",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="corporateactionresponse",
            name="inherit_dates",
            field=models.BooleanField(default=True),
        ),
    ]
