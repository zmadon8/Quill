from django.db import migrations, models


class Migration(migrations.Migration):
    """Owner round 2026-11: each user chooses the letters shown after shortened numbers (blank: k, lac, cr)."""

    dependencies = [("accounts", "0044_user_word_button_long")]

    operations = [
        migrations.AddField(model_name="user", name="short_thousands", field=models.CharField(blank=True, default="", max_length=12, verbose_name="Letters for thousands")),
        migrations.AddField(model_name="user", name="short_lac", field=models.CharField(blank=True, default="", max_length=12, verbose_name="Letters for lacs")),
        migrations.AddField(model_name="user", name="short_crore", field=models.CharField(blank=True, default="", max_length=12, verbose_name="Letters for crores")),
    ]
