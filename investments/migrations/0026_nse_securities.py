from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("investments", "0025_demerger_units_override")]

    operations = [
        migrations.CreateModel(
            name="NseSecurity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("symbol", models.CharField(max_length=40, unique=True)),
                ("name", models.CharField(max_length=250)),
                ("isin", models.CharField(blank=True, default="", max_length=20)),
                ("series", models.CharField(blank=True, default="", max_length=4)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["name"], name="inv_nsesec_name_idx"),
                    models.Index(fields=["isin"], name="inv_nsesec_isin_idx"),
                ],
            },
        ),
    ]
