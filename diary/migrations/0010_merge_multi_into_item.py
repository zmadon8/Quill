from django.db import migrations, models
from django.db.migrations.exceptions import IrreversibleError

from diary import legacy_merge as legacy


def merge_forwards(apps, schema_editor):
    """Move every non-nested Item's citation into its first Case and turn Multi-Items into Items.

    The mapping, the before/after count check and the "migrate" history rows are in
    diary/legacy_merge.py, shared with the backup loader. Any failed check raises and the whole
    migration is rolled back.
    """
    legacy.migrate_items(apps)


def merge_backwards(apps, schema_editor):
    """Not reversible: refuse rather than guess which Cases came from a citation and which were typed."""
    raise IrreversibleError(
        "Migration diary.0010 (Multi-Item merged into Item) cannot be reversed automatically, because "
        "after it nothing records which Cases were once a single citation and which Items were Multi-Items "
        "without guessing. Restore the 'pre_migration' backup taken before the update instead."
    )


class Migration(migrations.Migration):
    """10d: Case becomes the single store of citations (docs/DESIGN.md, Proposal for 10d).

    Schema changes come first and the data move last, so no ALTER TABLE follows data changes inside
    the one transaction. ``Item.citation`` stays as a legacy column (empty for every non-nested Item).
    """

    dependencies = [
        ("diary", "0009_trash_batches_undo_groups"),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="item", name="item_multi_has_no_citation"),
        migrations.AlterField(
            model_name="item",
            name="kind",
            field=models.CharField(
                choices=[("plain", "Item"), ("nested", "Nested Item")], default="plain", max_length=10
            ),
        ),
        migrations.AlterField(
            model_name="versionhistory",
            name="change_kind",
            field=models.CharField(
                choices=[
                    ("create", "Create"),
                    ("edit", "Edit"),
                    ("move", "Move"),
                    ("reorder", "Reorder"),
                    ("delete", "Delete"),
                    ("restore", "Restore"),
                    ("convert", "Convert"),
                    ("import", "Import"),
                    ("migrate", "Migrate"),
                ],
                max_length=10,
            ),
        ),
        migrations.RunPython(merge_forwards, merge_backwards),
    ]
