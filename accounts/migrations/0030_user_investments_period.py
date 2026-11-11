from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0029_user_header_initials_remove_citation_hyphen"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="investments_period",
            field=models.CharField(
                choices=[("1m", "1M"), ("3m", "3M"), ("6m", "6M"), ("1y", "1Y"), ("3y", "3Y"), ("5y", "5Y"), ("all", "All")],
                default="all", max_length=3, verbose_name="Investments period for returns",
            ),
        ),
    ]
