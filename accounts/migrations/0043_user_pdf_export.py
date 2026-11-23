from django.db import migrations, models


class Migration(migrations.Migration):
    """Owner round 2026-11: each user chooses whether the Fee Register memo page shows a PDF button (on by default)."""

    dependencies = [("accounts", "0042_user_feebook_group_payments")]

    operations = [
        migrations.AddField(model_name="user", name="pdf_export", field=models.BooleanField(default=True, verbose_name="Fee Register: PDF button on memos")),
    ]
