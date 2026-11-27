from django.db import migrations, models


def arranged_to_bubbles(apps, schema_editor):
    """The "Bubbles, arranged" style is gone; those users get the (one) bubble style."""
    User = apps.get_model("accounts", "User")
    User.objects.filter(citation_style="arranged").update(citation_style="bubbles")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0045_user_short_letters"),
    ]

    operations = [
        migrations.RunPython(arranged_to_bubbles, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="citation_style",
            field=models.CharField(
                choices=[
                    ("plain", "Plain text after a hyphen, always numbered"),
                    ("bubbles", "Bubbles"),
                ],
                default="bubbles",
                max_length=10,
                verbose_name="Citations",
            ),
        ),
    ]
