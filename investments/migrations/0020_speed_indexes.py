from django.db import migrations, models


class Migration(migrations.Migration):
    """Indexes for the reads behind the Overview, Holdings and transaction pages (docs/INVESTMENTS_SPEED.md)."""

    dependencies = [("investments", "0019_instrument_interest_type")]

    operations = [
        migrations.AddIndex(
            model_name="transfer",
            index=models.Index(fields=["profile", "instrument", "date"], name="inv_xfer_prof_instr_date_idx"),
        ),
        migrations.AddIndex(
            model_name="transaction",
            index=models.Index(fields=["profile", "date"], name="inv_txn_prof_date_idx"),
        ),
    ]
