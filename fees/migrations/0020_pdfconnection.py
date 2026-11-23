from django.db import migrations, models


class Migration(migrations.Migration):
    """Owner round 2026-11: the Microsoft 365 sign-in for memo PDFs (docs/FEES_PDF_EXPORT.md). Never in a backup."""

    dependencies = [("fees", "0019_payment_modes")]

    operations = [
        migrations.CreateModel(
            name="PdfConnection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("account", models.CharField(blank=True, default="", max_length=200)),
                ("refresh_token", models.TextField(blank=True, default="")),
                ("access_token", models.TextField(blank=True, default="")),
                ("access_expires_at", models.DateTimeField(blank=True, null=True)),
                ("connected_at", models.DateTimeField(blank=True, null=True)),
                ("connected_by", models.CharField(blank=True, default="", max_length=150)),
                ("last_success_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.CharField(blank=True, default="", max_length=300)),
                ("last_error_at", models.DateTimeField(blank=True, null=True)),
            ],
        ),
    ]
