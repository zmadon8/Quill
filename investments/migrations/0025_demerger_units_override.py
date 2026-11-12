from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("investments", "0024_demerger_allotments")]

    operations = [
        migrations.AddField(
            model_name="corporateactionresponse",
            name="units_override",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
