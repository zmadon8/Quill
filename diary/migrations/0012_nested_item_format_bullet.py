from django.db import migrations, models

FORMATS = [
    ("upper_alpha", "A, B, C"),
    ("lower_alpha", "a, b, c"),
    ("decimal", "1, 2, 3"),
    ("upper_roman", "I, II, III"),
    ("lower_roman", "i, ii, iii"),
    ("paren_upper_alpha", "(A), (B), (C)"),
    ("paren_lower_roman", "(i), (ii), (iii)"),
    ("paren_lower_alpha", "(a), (b), (c)"),
    ("paren_decimal", "(1), (2), (3)"),
    ("bullet", "Bullet"),
    ("none", "None"),
]


def to_bullet(apps, schema_editor):
    """The field was never used before; rows still holding the old default now get the new one."""
    UserSettings = apps.get_model("diary", "UserSettings")
    UserSettings.objects.filter(nested_item_format="paren_decimal").update(nested_item_format="bullet")


class Migration(migrations.Migration):
    dependencies = [("diary", "0011_item_plain_has_no_citation")]

    operations = [
        migrations.AlterField(
            model_name="usersettings",
            name="nested_item_format",
            field=models.CharField(choices=FORMATS, default="bullet", max_length=20),
        ),
        migrations.RunPython(to_bullet, migrations.RunPython.noop),
    ]
