from django.db import migrations, models


class Migration(migrations.Migration):
    """Owner round 2026-12: Draft memos can be switched off for a profile (on by default)."""

    dependencies = [("fees", "0021_remove_fee_line_defaults")]

    operations = [
        migrations.AddField(model_name="feessettings", name="draft_memos_enabled", field=models.BooleanField(default=True)),
    ]
