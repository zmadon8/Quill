from django.db import migrations, models

from diary.constraints import exactly_one


class Migration(migrations.Migration):
    """Round 10: the schema after the conversion of 0015. Every Item is now a top-level Item (a Subject, Topic
    or Sub-topic is its parent), so the nesting column, its rules and the setting for it go."""

    dependencies = [
        ("diary", "0015_convert_nested_items"),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="item", name="item_child_of_nested_is_plain"),
        migrations.RemoveConstraint(model_name="item", name="item_exactly_one_parent"),
        migrations.RemoveConstraint(model_name="item", name="item_plain_has_no_citation"),
        migrations.RemoveField(model_name="item", name="parent_item"),
        migrations.AddConstraint(
            model_name="item",
            constraint=models.CheckConstraint(
                condition=exactly_one(["subject", "topic", "subtopic"]),
                name="item_exactly_one_parent",
            ),
        ),
        migrations.AddConstraint(
            model_name="item",
            constraint=models.CheckConstraint(condition=models.Q(("citation", "")), name="item_plain_has_no_citation"),
        ),
        migrations.AlterField(
            model_name="item",
            name="kind",
            field=models.CharField(choices=[("plain", "Item")], default="plain", max_length=10),
        ),
        migrations.RemoveField(model_name="usersettings", name="nested_item_format"),
    ]
