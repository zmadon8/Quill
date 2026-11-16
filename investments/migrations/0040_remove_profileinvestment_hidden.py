from django.db import migrations


class Migration(migrations.Migration):
    """Hidden investments are no longer a feature: every investment now shows by its status (Held, Sold out, Not bought yet)."""

    dependencies = [("investments", "0039_investmentsettings_index_line_floor_zero")]
    operations = [
        migrations.RemoveField(model_name="profileinvestment", name="hidden"),
    ]
