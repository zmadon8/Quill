from django.db import migrations
from django.db.migrations.exceptions import IrreversibleError

from diary import subtopic_one, topic_one


def house_forwards(apps, schema_editor):
    """Move every Sub-topic that sits directly under a Subject into the Subject's Topic named "1" (made when needed), then
    house any Items and Sections that were left loose under such a Subject (migration 0017 skipped them) in the same Topic.
    The mapping, the count checks and the "migrate" history rows are in diary/subtopic_one.py and diary/topic_one.py, shared
    with the backup loader. Any failed check raises and the whole migration is rolled back."""
    subtopic_one.migrate_direct(apps)
    topic_one.migrate_loose(apps)


def house_backwards(apps, schema_editor):
    """Reverse only when there is nothing to un-house (no Sub-topic rows, trashed ones included): afterwards nothing
    records which Sub-topics sat directly under a Subject before."""
    if apps.get_model("diary", "Subtopic").objects.exists():
        raise IrreversibleError(
            "Migration diary.0018 (Sub-topics housed in a Topic called \"1\") cannot be reversed while any Sub-topic "
            "exists, because after it nothing records which ones sat directly under a Subject. Restore the "
            "'pre_migration' backup taken before the update instead."
        )


class Migration(migrations.Migration):
    """Round 14: data only (no schema change)."""

    dependencies = [
        ("diary", "0017_house_loose_in_topic_one"),
    ]

    operations = [
        migrations.RunPython(house_forwards, house_backwards),
    ]
