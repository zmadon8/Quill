from django.db import migrations, models


class Migration(migrations.Migration):
    """Backups made around a Word import get their own kinds (never pruned automatically)."""

    dependencies = [
        ("backups", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="backupfile",
            name="kind",
            field=models.CharField(choices=[("daily", "Daily"), ("manual", "Manual"), ("pre_restore", "Before restore"), ("pre_migration", "Before update"), ("uploaded", "Uploaded"), ("pre_import", "Before import"), ("post_import", "After import")], max_length=20),
        ),
        migrations.AlterField(
            model_name="backuplog",
            name="kind",
            field=models.CharField(choices=[("daily", "Daily"), ("manual", "Manual"), ("pre_restore", "Before restore"), ("pre_migration", "Before update"), ("pre_import", "Before import"), ("post_import", "After import"), ("restore", "Restore"), ("prune", "Clean-up")], max_length=20),
        ),
    ]
