from django.db import migrations, models


class Migration(migrations.Migration):
    """The page the Investments program opens on, chosen on My settings > Start Screens."""

    dependencies = [
        ("accounts", "0033_remove_user_header_style_and_show_home_button"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="investments_start_page",
            field=models.CharField(
                choices=[
                    ("dashboard", "Overview"), ("holdings", "Holdings"), ("transactions", "Transactions"),
                    ("performance", "Reports"), ("alerts", "Alerts"), ("admin_catalogue", "Catalogue"),
                ],
                default="dashboard", max_length=20, verbose_name="Investments start page",
            ),
        ),
    ]
