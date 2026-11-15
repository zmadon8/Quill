from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("investments", "0038_backfill_lump_value_before")]
    operations = [
        migrations.AddField(
            model_name="investmentsettings", name="index_line_floor_zero",
            field=models.BooleanField(default=False, help_text="Stop the Index line on the charts at 0 instead of letting it go below 0")),
    ]
