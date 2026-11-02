from django.db import migrations
from django.db.migrations.exceptions import IrreversibleError

from diary import topic_one


def house_forwards(apps, schema_editor):
    """Move every Item and Section that sits directly under a Subject (one that holds no Sub-topic directly) into the
    Subject's Topic named "1". The mapping, the count checks and the "migrate" history rows are in diary/topic_one.py,
    shared with the backup loader. Any failed check raises and the whole migration is rolled back."""
    topic_one.migrate_loose(apps)


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
