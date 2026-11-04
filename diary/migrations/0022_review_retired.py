from django.db import migrations, models


class Migration(migrations.Migration):
    """Round 16 (D88): the For review switch is retired. A check rule keeps it off, so nothing can hide there."""

    dependencies = [
        ("diary", "0021_review_into_flags"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="item",
            constraint=models.CheckConstraint(condition=models.Q(needs_review=False), name="item_review_retired"),
        ),
        migrations.AddConstraint(
            model_name="section",
            constraint=models.CheckConstraint(condition=models.Q(needs_review=False), name="section_review_retired"),
        ),
    ]
