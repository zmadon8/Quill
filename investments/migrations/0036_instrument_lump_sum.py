from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("investments", "0035_alert_switches")]
    operations = [
        migrations.AddField(
            model_name="instrument", name="lump_sum",
            field=models.BooleanField(default=False, help_text="Alternative investment bought and sold in lump sums: no units or price per unit are asked for")),
    ]
