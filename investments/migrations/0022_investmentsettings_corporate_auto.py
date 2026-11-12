from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0021_remove_investmentsettings_hidden_pages"),
    ]

    operations = [
        migrations.AddField(
            model_name="investmentsettings",
            name="corporate_auto",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="dividendsignal",
            name="logged_for",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
