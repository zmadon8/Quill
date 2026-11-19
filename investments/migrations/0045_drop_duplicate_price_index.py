from django.db import migrations


class Migration(migrations.Migration):
    """The unique constraint on (instrument, date) already serves as that index; the second copy only slowed every price write."""

    dependencies = [
        ("investments", "0044_tentative_status"),
    ]

    operations = [
        migrations.RemoveIndex(model_name="price", name="inv_price_instr_date_idx"),
    ]
