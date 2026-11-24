from django.db import migrations, models


class Migration(migrations.Migration):
    """Owner round 2026-11: each user can have the Fee Register memo's Word button read "Download Memo (Word)" (off by default)."""

    dependencies = [("accounts", "0043_user_pdf_export")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="word_button_long",
            field=models.BooleanField(default=False, verbose_name="Fee Register: name the Word button Download Memo (Word)"),
        ),
    ]
