from django.db import migrations, models

SECTION_CHOICES = [
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
    ("section_n", "Section 1, Section 2"),
]
FORMATS = SECTION_CHOICES[:-1]


def to_new_defaults(apps, schema_editor):
    """Change only rows that still hold the old defaults."""
    UserSettings = apps.get_model("diary", "UserSettings")
    UserSettings.objects.filter(section_format="paren_upper_alpha").update(section_format="paren_lower_alpha")
    UserSettings.objects.filter(item_format="paren_lower_roman").update(item_format="paren_decimal")
    UserSettings.objects.filter(nested_item_format="paren_lower_roman").update(nested_item_format="paren_decimal")


def to_old_defaults(apps, schema_editor):
    UserSettings = apps.get_model("diary", "UserSettings")
    UserSettings.objects.filter(section_format="paren_lower_alpha").update(section_format="paren_upper_alpha")
    UserSettings.objects.filter(item_format="paren_decimal").update(item_format="paren_lower_roman")
    UserSettings.objects.filter(nested_item_format="paren_decimal").update(nested_item_format="paren_lower_roman")


class Migration(migrations.Migration):
    dependencies = [("diary", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="usersettings",
            name="section_format",
            field=models.CharField(choices=SECTION_CHOICES, default="paren_lower_alpha", max_length=20),
        ),
        migrations.AlterField(
            model_name="usersettings",
            name="item_format",
            field=models.CharField(choices=FORMATS, default="paren_decimal", max_length=20),
        ),
        migrations.AlterField(
            model_name="usersettings",
            name="nested_item_format",
            field=models.CharField(choices=FORMATS, default="paren_decimal", max_length=20),
        ),
        migrations.RunPython(to_new_defaults, to_old_defaults),
    ]
