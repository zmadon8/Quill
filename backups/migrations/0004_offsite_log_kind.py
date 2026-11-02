from django.db import migrations, models


class Migration(migrations.Migration):
    """Off-site copy attempts are recorded in the backup history with their own kind."""

    dependencies = [
        ("backups", "0003_pre_clear_kind"),
    ]

    operations = [
        migrations.AlterField(
            model_name="backuplog",
            name="kind",
            field=models.CharField(choices=[("daily", "Daily"), ("manual", "Manual"), ("pre_restore", "Before restore"), ("pre_migration", "Before update"), ("pre_import", "Before import"), ("post_import", "After import"), ("pre_clear", "Before clearing profile"), ("restore", "Restore"), ("prune", "Clean-up"), ("offsite", "Off-site copy")], max_length=20),
        ),
    ]
