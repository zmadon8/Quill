from django.db import migrations, models
from django.db.models import F

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


def copy_inline_format(apps, schema_editor):
    """Existing users keep what they had: the format for citations on separate lines starts as their inline one."""
    apps.get_model("diary", "UserSettings").objects.update(multi_citation_lines_format=F("multi_citation_format"))


class Migration(migrations.Migration):
    dependencies = [
        ("diary", "0024_remove_usersettings_export_custom_name_time_zone"),
    ]

    operations = [
        migrations.AddField(
            model_name="usersettings",
            name="multi_citation_lines_format",
            field=models.CharField(choices=FORMATS, default="paren_lower_alpha", max_length=20),
        ),
        migrations.RunPython(copy_inline_format, migrations.RunPython.noop),
    ]
