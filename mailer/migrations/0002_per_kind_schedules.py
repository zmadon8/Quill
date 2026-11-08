"""Each kind of emailed file (regular backup, Word copy, HTML copy, Fee Register Excel) gets its own switch and
schedule, and splitting by size becomes a setting. The old single schedule and "What to send" choice are copied over."""
from django.conf import settings
from django.db import migrations, models

FREQUENCY = [("daily", "Every day"), ("weekly", "Every week"), ("monthly", "Every month")]
WEEKDAYS = [(0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"), (4, "Friday"), (5, "Saturday"), (6, "Sunday")]
KINDS = (("data", True), ("word", True), ("html", False), ("excel", False))


def copy_old_settings(apps, schema_editor):
    Schedule = apps.get_model("mailer", "EmailBackupSchedule")
    limit = max(1, min(100, int(getattr(settings, "EMAIL_BACKUP_MAX_MB", 15) or 15)))
    for row in Schedule.objects.all():
        for kind, _ in KINDS:
            setattr(row, f"{kind}_frequency", row.frequency)
            setattr(row, f"{kind}_weekday", row.weekday)
            setattr(row, f"{kind}_day_of_month", row.day_of_month)
        row.data_enabled = row.delivery in ("data", "both_one", "both_separate")
        row.word_enabled = row.delivery in ("word", "both_one", "both_separate")
        row.data_last_sent_at = row.last_sent_at if row.data_enabled else None
        row.word_last_sent_at = row.last_sent_at if row.word_enabled else None
        # "Both, in separate emails" was the old way round the size limit.
        row.split_emails = row.delivery == "both_separate"
        row.max_attachment_mb = limit
        row.save()


def fields():
    for kind, on in KINDS:
        yield f"{kind}_enabled", models.BooleanField(default=on)
        yield f"{kind}_frequency", models.CharField(choices=FREQUENCY, default="weekly", max_length=10)
        yield f"{kind}_weekday", models.PositiveSmallIntegerField(choices=WEEKDAYS, default=0)
        yield f"{kind}_day_of_month", models.PositiveSmallIntegerField(default=1)
        yield f"{kind}_last_sent_at", models.DateTimeField(blank=True, null=True)


class Migration(migrations.Migration):
    dependencies = [("mailer", "0001_initial")]

    operations = [
        *[migrations.AddField("emailbackupschedule", name, field) for name, field in fields()],
        migrations.AddField("emailbackupschedule", "split_emails", models.BooleanField(default=False)),
        migrations.AddField("emailbackupschedule", "max_attachment_mb", models.PositiveSmallIntegerField(default=15)),
        migrations.RunPython(copy_old_settings, migrations.RunPython.noop),
        migrations.RemoveField("emailbackupschedule", "frequency"),
        migrations.RemoveField("emailbackupschedule", "weekday"),
        migrations.RemoveField("emailbackupschedule", "day_of_month"),
        migrations.RemoveField("emailbackupschedule", "delivery"),
    ]
