from django.db import migrations
from django.db.migrations.exceptions import IrreversibleError

from diary.migrations._retired import refuse_old_data


def house_forwards(apps, schema_editor):
    """The data move this migration once made has been retired (see diary/migrations/_retired.py): it only checks that
    there is nothing for it to move."""
    refuse_old_data(apps, "Subtopic", "Item", "Section")


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
