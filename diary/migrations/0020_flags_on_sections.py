from django.db import migrations, models

FLAG_CHOICES = [("none", "None"), ("pending", "Pending"), ("overruled", "Overruled"), ("doubted", "Doubted"), ("other", "Other")]


class Migration(migrations.Migration):
    """Round 16 (D88), schema: the Pending flag, flags on Sections, and room for longer flag texts (a For review note can be
    long). Data comes in 0021, the check rules in 0022 (kept apart so PostgreSQL never alters a table it has just updated)."""

    dependencies = [
        ("diary", "0019_case_url"),
    ]

    operations = [
        migrations.AlterField(
            model_name="item",
            name="flag",
            field=models.CharField(choices=FLAG_CHOICES, default="none", max_length=10),
        ),
        migrations.AlterField(
            model_name="item",
            name="flag_text",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="section",
            name="flag",
            field=models.CharField(choices=FLAG_CHOICES, default="none", max_length=10),
        ),
        migrations.AddField(
            model_name="section",
            name="flag_text",
            field=models.TextField(blank=True),
        ),
    ]
