from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("investments", "0022_investmentsettings_corporate_auto")]

    operations = [
        migrations.AddField(
            model_name="instrument",
            name="taxed_as_interest",
            field=models.BooleanField(default=False, help_text="Profit or loss on sales is Interest Income, not Capital Gains"),
        ),
    ]
