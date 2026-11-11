from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("investments", "0018_origin_demerger_methods")]

    operations = [
        migrations.AddField(
            model_name="instrument",
            name="interest_type",
            field=models.CharField(
                choices=[("simple", "Simple interest"), ("compound", "Compound interest (yearly)")],
                default="compound",
                help_text="Alternative investments with an interest rate: simple or compounded yearly",
                max_length=10,
            ),
        ),
    ]
