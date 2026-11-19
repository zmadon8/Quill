from django.db import migrations
from django.db.migrations.exceptions import IrreversibleError

from diary.migrations._retired import refuse_old_data


def house_forwards(apps, schema_editor):
    """The data move this migration once made has been retired (see diary/migrations/_retired.py): it only checks that
    there is nothing for it to move."""
    refuse_old_data(apps, "Item", "Section")


def house_backwards(apps, schema_editor):
    """Reverse only when there is nothing to un-house (no Item or Section rows, trashed ones included): afterwards
    nothing records which Items sat under a Subject before."""
    if apps.get_model("diary", "Item").objects.exists() or apps.get_model("diary", "Section").objects.exists():
        raise IrreversibleError(
            "Migration diary.0017 (loose Items housed in a Topic called \"1\") cannot be reversed while any Item or "
            "Section exists, because after it nothing records which ones sat directly under a Subject. Restore the "
            "'pre_migration' backup taken before the update instead."
        )


class Migration(migrations.Migration):
    """Round 10: data only (no schema change), after the Nested Item conversion of 0015 and 0016."""

    dependencies = [
        ("diary", "0016_remove_nested_items"),
    ]

    operations = [
        migrations.RunPython(house_forwards, house_backwards),
    ]
