from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("investments", "0023_instrument_taxed_as_interest")]

    operations = [
        migrations.AddField(
            model_name="transaction",
            name="auto_created",
            field=models.BooleanField(default=False, help_text="Made by the program from a demerger and not edited since; editing the demerger replaces it"),
        ),
        migrations.AlterField(
            model_name="corporateactionresponse",
            name="inherit_dates",
            field=models.BooleanField(default=False),
        ),
    ]
