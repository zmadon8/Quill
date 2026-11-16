import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Owner round 2026-11: a matter (and so its memos) may have no partner. Existing rows keep theirs."""

    dependencies = [("fees", "0010_client_and_client_position")]

    operations = [
        migrations.AlterField(
            model_name="matter",
            name="group",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="matters", to="fees.group"
            ),
        ),
        migrations.AlterField(
            model_name="memo",
            name="group",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="memos", to="fees.group"
            ),
        ),
    ]
