from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0037_user_home_show_figures"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="citation_style",
            field=models.CharField(
                choices=[
                    ("plain", "Plain text after a hyphen, always numbered"),
                    ("bubbles", "Bubbles"),
                    ("arranged", "Bubbles, arranged to fill the space"),
                ],
                default="bubbles",
                max_length=10,
                verbose_name="Citations",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="number_citation_lines",
            field=models.BooleanField(default=True, verbose_name="Number citations on separate lines"),
        ),
    ]
