from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fees", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="feessettings",
            name="memo_default_name",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="feessettings",
            name="memo_default_designation",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="feessettings",
            name="memo_default_address",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="feessettings",
            name="memo_default_bank_details",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="feessettings",
            name="memo_default_pan",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
        migrations.AddField(
            model_name="wordtemplate",
            name="signature_data",
            field=models.BinaryField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="wordtemplate",
            name="signature_filename",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="wordtemplate",
            name="signature_content_type",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
    ]
