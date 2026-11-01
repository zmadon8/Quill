from django.db import migrations, models


class Migration(migrations.Migration):
    """Backups taken before clearing a profile get their own kind (never pruned automatically)."""

    dependencies = [
        ("backups", "0002_import_backup_kinds"),
    ]

    operations = [
        migrations.AlterField(
            model_name="backupfile",
            name="kind",
            field=models.CharField(choices=[("daily", "Daily"), ("manual", "Manual"), ("pre_restore", "Before restore"), ("pre_migration", "Before update"), ("uploaded", "Uploaded"), ("pre_import", "Before import"), ("post_import", "After import"), ("pre_clear", "Before clearing profile")], max_length=20),
        ),
        migrations.AlterField(
            model_name="backuplog",
            name="kind",
            field=models.CharField(choices=[("daily", "Daily"), ("manual", "Manual"), ("pre_restore", "Before restore"), ("pre_migration", "Before update"), ("pre_import", "Before import"), ("post_import", "After import"), ("pre_clear", "Before clearing profile"), ("restore", "Restore"), ("prune", "Clean-up")], max_length=20),
        ),
    ]
