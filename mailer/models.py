from django.conf import settings
from django.db import models

FREQ_DAILY, FREQ_WEEKLY, FREQ_MONTHLY = "daily", "weekly", "monthly"
FREQUENCY_CHOICES = [
    (FREQ_DAILY, "Every day"),
    (FREQ_WEEKLY, "Every week"),
    (FREQ_MONTHLY, "Every month"),
]
DELIVERY_DATA, DELIVERY_WORD, DELIVERY_BOTH_ONE, DELIVERY_BOTH_SEPARATE = "data", "word", "both_one", "both_separate"
DELIVERY_CHOICES = [
    (DELIVERY_DATA, "The JSON backup only"),
    (DELIVERY_WORD, "The complete Word export only"),
    (DELIVERY_BOTH_ONE, "Both, in one email"),
    (DELIVERY_BOTH_SEPARATE, "Both, in separate emails"),
]
WEEKDAY_CHOICES = [
    (0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"), (4, "Friday"), (5, "Saturday"), (6, "Sunday"),
]


class EmailBackupSchedule(models.Model):
    """The one row of settings for backups sent by email (managed by the Admin on the Backups > Email screen).

    The nightly scheduled job runs ``send_email_backups``, which sends when a send is due. Deliberately NOT in backup
    files (like the sessions): it holds addresses and a send log, not diary data.
    """

    enabled = models.BooleanField(default=False)
    frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES, default=FREQ_WEEKLY)
    weekday = models.PositiveSmallIntegerField(choices=WEEKDAY_CHOICES, default=0)
    day_of_month = models.PositiveSmallIntegerField(default=1)
    recipients = models.TextField(blank=True)
    delivery = models.CharField(max_length=15, choices=DELIVERY_CHOICES, default=DELIVERY_BOTH_ONE)
    include_review = models.BooleanField(default=True)
    # Whose My settings (number formats, date format) the emailed Word file uses: the Admin who last saved the schedule.
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    last_sent_at = models.DateTimeField(null=True, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_ok = models.BooleanField(null=True, blank=True)
    last_message = models.CharField(max_length=500, blank=True)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Email backup schedule"
