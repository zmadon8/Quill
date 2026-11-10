from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0027_user_show_home_button"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="colour_theme",
            field=models.CharField(
                choices=[
                    ("oxblood", "Oxblood"),
                    ("royal", "Royal Blue"),
                    ("navy", "Navy"),
                    ("violet", "Violet"),
                    ("plum", "Plum"),
                    ("teal", "Teal"),
                ],
                default="oxblood",
                max_length=10,
                verbose_name="Colour theme",
            ),
        ),
    ]
