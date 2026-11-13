from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0031_infer_regular_plan"),
    ]

    operations = [
        migrations.AddField(
            model_name="amfischeme",
            name="category",
            field=models.CharField(blank=True, default="", help_text="AMFI's category heading, such as Open Ended Schemes(Debt Scheme - Liquid Fund)", max_length=80),
        ),
    ]
