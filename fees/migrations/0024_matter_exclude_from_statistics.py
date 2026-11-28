from django.db import migrations, models


class Migration(migrations.Migration):
    """Owner round 2026-12: a matter can be left out of Statistics, the Dashboard and the Home figures (off for every matter)."""

    dependencies = [("fees", "0023_addressee_firm_name_into_line1")]

    operations = [
        migrations.AddField(
            model_name="matter",
            name="exclude_from_statistics",
            field=models.BooleanField(default=False, verbose_name="Leave out of Statistics"),
        ),
    ]
