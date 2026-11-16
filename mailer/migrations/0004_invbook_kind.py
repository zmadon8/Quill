from django.db import migrations, models


class Migration(migrations.Migration):
    """Investments: Holdings and Transactions (.xlsx) as a kind of emailed backup, with its own schedule (off by default)."""

    dependencies = [("mailer", "0003_price_archive_kind")]

    operations = [
        migrations.AddField(model_name="emailbackupschedule", name="invbook_enabled", field=models.BooleanField(default=False)),
        migrations.AddField(
            model_name="emailbackupschedule", name="invbook_frequency",
            field=models.CharField(choices=[("daily", "Every day"), ("weekly", "Every week"), ("monthly", "Every month")], default="weekly", max_length=10),
        ),
        migrations.AddField(
            model_name="emailbackupschedule", name="invbook_weekday",
            field=models.PositiveSmallIntegerField(
                choices=[(0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"), (4, "Friday"), (5, "Saturday"), (6, "Sunday")], default=0),
        ),
        migrations.AddField(model_name="emailbackupschedule", name="invbook_day_of_month", field=models.PositiveSmallIntegerField(default=1)),
        migrations.AddField(model_name="emailbackupschedule", name="invbook_last_sent_at", field=models.DateTimeField(blank=True, null=True)),
    ]
