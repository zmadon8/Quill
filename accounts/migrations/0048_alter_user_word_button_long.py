from django.db import migrations, models


class Migration(migrations.Migration):
    """The memo's Word button option now reads Save & Download (the label changes; no data does)."""

    dependencies = [("accounts", "0047_user_statistics_enabled")]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="word_button_long",
            field=models.BooleanField(default=False, verbose_name="Fee Register: name the Word button Save & Download"),
        ),
    ]
