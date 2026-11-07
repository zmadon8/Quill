from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("diary", "0022_review_retired"),
    ]

    operations = [
        migrations.AlterField(
            model_name="usersettings",
            name="opening_page",
            field=models.CharField(
                choices=[
                    ("home", "Home"),
                    ("other_subjects", "Other Subjects"),
                    ("search", "Global Search"),
                    ("last", "The Last Page I Viewed"),
                    ("subject", "A Chosen Subject"),
                ],
                default="home",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="item",
            name="citation_layout",
            field=models.CharField(
                choices=[("inline", "Inline"), ("lines", "On Separate Lines")], default="inline", max_length=10
            ),
        ),
    ]
