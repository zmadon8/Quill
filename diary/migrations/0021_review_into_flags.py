from django.db import migrations
from django.db.migrations.exceptions import IrreversibleError

from diary.migrations._retired import refuse_old_data


def forwards(apps, schema_editor):
    """The data move this migration once made has been retired (see diary/migrations/_retired.py): it only checks that
    there is nothing for it to move."""
    refuse_old_data(apps, "Item", "Section")


def backwards(apps, schema_editor):
    """Reverse only when there is nothing to un-merge: afterwards nothing records which flags came from a For review mark."""
    if apps.get_model("diary", "Item").objects.exists() or apps.get_model("diary", "Section").objects.exists():
        raise IrreversibleError(
            "Migration diary.0021 (For review merged into Flags) cannot be reversed while any Item or Section exists. "
            "Restore the 'pre_migration' backup taken before the update instead."
        )


class Migration(migrations.Migration):
    """Round 16 (D88): data only."""

    dependencies = [
        ("diary", "0020_flags_on_sections"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
