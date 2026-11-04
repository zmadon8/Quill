from django.db import migrations, models


class Migration(migrations.Migration):
    """Round 16 (D87): a hyperlink on each citation. Schema only; every existing citation gets an empty address."""

    dependencies = [
        ("diary", "0018_house_direct_subtopics"),
    ]

    operations = [
        migrations.AddField(
            model_name="case",
            name="url",
            field=models.CharField(blank=True, default="", max_length=2000),
        ),
    ]
