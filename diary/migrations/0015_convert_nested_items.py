from django.db import migrations
from django.db.migrations.exceptions import IrreversibleError

from diary.migrations._retired import refuse_old_data


def convert_forwards(apps, schema_editor):
    """The data move this migration once made has been retired (see diary/migrations/_retired.py): it only checks that
    there is nothing for it to move."""
    refuse_old_data(apps, "Item", "Case")


def convert_backwards(apps, schema_editor):
    """Reverse only when there is nothing to un-convert (no Item or Case rows, trashed ones included).

    With data present, nothing records which Cases were once the sub-items of a Nested Item, so reversing
    would be a guess: refuse. An empty database (such as a test database rolling migrations back) reverses
    cleanly because only the schema operations remain.
    """
    if apps.get_model("diary", "Item").objects.exists() or apps.get_model("diary", "Case").objects.exists():
        raise IrreversibleError(
            "Migration diary.0015 (Nested Items converted to Items with several citations) cannot be reversed "
            "while any Item or Case exists, because after it nothing records which citations were once "
            "sub-items of a Nested Item. Restore the 'pre_migration' backup taken before the update instead."
        )


class Migration(migrations.Migration):
    """Round 10: the data move. Kept apart from the schema changes (0014 before, 0016 after) because an ALTER
    TABLE must not follow data changes inside one PostgreSQL transaction."""

    dependencies = [
        ("diary", "0014_item_citation_layout"),
    ]

    operations = [
        migrations.RunPython(convert_forwards, convert_backwards),
    ]
