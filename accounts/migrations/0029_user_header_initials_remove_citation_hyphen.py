from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0028_user_colour_theme"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="header_initials",
            field=models.CharField(blank=True, default="", max_length=3, verbose_name="Header letters"),
        ),
        migrations.AddField(
            model_name="user",
            name="remove_citation_hyphen",
            field=models.BooleanField(default=False, verbose_name="Remove the hyphen before the citation"),
        ),
    ]
