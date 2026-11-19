from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0038_user_citation_style"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="citation_full_size",
            field=models.BooleanField(default=False, verbose_name="Citations as large as the Item's text"),
        ),
    ]
