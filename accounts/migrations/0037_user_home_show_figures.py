from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0036_user_group_digits"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="home_show_figures",
            field=models.BooleanField(default=True, verbose_name="Show figures on the Home page"),
        ),
    ]
