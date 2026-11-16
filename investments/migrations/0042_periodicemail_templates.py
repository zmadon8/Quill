from django.db import migrations, models


class Migration(migrations.Migration):
    """The report emails' wording can be edited (Investments > Settings > Email reports). Blank means the standard wording."""

    dependencies = [("investments", "0041_periodic_email")]

    operations = [
        migrations.AddField(model_name="periodicemail", name="subject_template", field=models.CharField(blank=True, default="", max_length=300)),
        migrations.AddField(model_name="periodicemail", name="body_template", field=models.TextField(blank=True, default="")),
    ]
