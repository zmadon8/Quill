from django.db import migrations, models


class Migration(migrations.Migration):
    """10d: from now on the database itself refuses a citation on a non-nested Item.

    Kept apart from 0010 on purpose: 0010 moves the data, and an ALTER TABLE must not follow data changes
    inside one PostgreSQL transaction. Every old row has been mapped by 0010 by the time this runs, and
    old backup files are mapped by the backup loader before anything is inserted, so no row can violate it.
    """

    dependencies = [
        ("diary", "0010_merge_multi_into_item"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="item",
            constraint=models.CheckConstraint(
                condition=models.Q(("kind", "nested"), ("citation", ""), _connector="OR"),
                name="item_plain_has_no_citation",
            ),
        ),
    ]
