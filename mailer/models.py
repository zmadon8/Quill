from django.conf import settings
from django.db import models

FREQ_DAILY, FREQ_WEEKLY, FREQ_MONTHLY = "daily", "weekly", "monthly"
FREQUENCY_CHOICES = [
    (FREQ_DAILY, "Every day"),
    (FREQ_WEEKLY, "Every week"),
    (FREQ_MONTHLY, "Every month"),
]
#: What can be emailed, in the order the page and the emails list them: (key, label).
KIND_DATA, KIND_WORD, KIND_HTML, KIND_EXCEL = "data", "word", "html", "excel"
KIND_ARCHIVE = "archive"
KINDS = [
    (KIND_DATA, "Regular backup (.json.gz)"),
    (KIND_WORD, "Case Law Diary: Word copy (.docx)"),
    (KIND_HTML, "Case Law Diary: HTML copy (.html)"),
    (KIND_EXCEL, "Fee Register: Excel sheets (.xlsx)"),
    (KIND_ARCHIVE, "Investments: price archive (.zip)"),
]
KIND_KEYS = [key for key, _ in KINDS]
KIND_LABELS = dict(KINDS)
#: Default largest total of attachments in one email when splitting is on (Gmail refuses a message over 25 MB).
DEFAULT_MAX_MB = 15
WEEKDAY_CHOICES = [
    (0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"), (4, "Friday"), (5, "Saturday"), (6, "Sunday"),
]


class EmailBackupSchedule(models.Model):
    """The one row of settings for backups sent by email (managed by the Admin on the Backups > Email screen).

    The nightly scheduled job runs ``send_email_backups``, which sends when a send is due. Deliberately NOT in backup
    files (like the sessions): it holds addresses and a send log, not diary data.
    """

    enabled = models.BooleanField(default=False)
    recipients = models.TextField(blank=True)
    # Each kind of file has its own switch and its own schedule (the files of every kind that is due go out together).
    data_enabled = models.BooleanField(default=True)
    data_frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES, default=FREQ_WEEKLY)
    data_weekday = models.PositiveSmallIntegerField(choices=WEEKDAY_CHOICES, default=0)
    data_day_of_month = models.PositiveSmallIntegerField(default=1)
    data_last_sent_at = models.DateTimeField(null=True, blank=True)
    word_enabled = models.BooleanField(default=True)
    word_frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES, default=FREQ_WEEKLY)
    word_weekday = models.PositiveSmallIntegerField(choices=WEEKDAY_CHOICES, default=0)
    word_day_of_month = models.PositiveSmallIntegerField(default=1)
    word_last_sent_at = models.DateTimeField(null=True, blank=True)
    html_enabled = models.BooleanField(default=False)
    html_frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES, default=FREQ_WEEKLY)
    html_weekday = models.PositiveSmallIntegerField(choices=WEEKDAY_CHOICES, default=0)
    html_day_of_month = models.PositiveSmallIntegerField(default=1)
    html_last_sent_at = models.DateTimeField(null=True, blank=True)
    excel_enabled = models.BooleanField(default=False)
    excel_frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES, default=FREQ_WEEKLY)
    excel_weekday = models.PositiveSmallIntegerField(choices=WEEKDAY_CHOICES, default=0)
    excel_day_of_month = models.PositiveSmallIntegerField(default=1)
    excel_last_sent_at = models.DateTimeField(null=True, blank=True)
    # Investments price archive (plan 17.5). Off by default; monthly. Always sent in emails of its own (see services._send_archive).
    archive_enabled = models.BooleanField(default=False)
    archive_frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES, default=FREQ_MONTHLY)
    archive_weekday = models.PositiveSmallIntegerField(choices=WEEKDAY_CHOICES, default=0)
    archive_day_of_month = models.PositiveSmallIntegerField(default=1)
    archive_last_sent_at = models.DateTimeField(null=True, blank=True)
    # Full or Pruned; only used while the live price database is not pruned (a pruned database can only give a pruned archive).
    archive_version = models.CharField(max_length=6, default="full", choices=[("full", "Full"), ("pruned", "Pruned")])
    # Off (the default): everything due goes in one email. On: no email carries more than max_attachment_mb of files;
    # the files are shared out over as few emails as possible, keeping each kind's files together where that costs
    # no extra email.
    split_emails = models.BooleanField(default=False)
    max_attachment_mb = models.PositiveSmallIntegerField(default=DEFAULT_MAX_MB)
    include_review = models.BooleanField(default=True)
    # Whose My settings (number formats, date format) the emailed Word and HTML files use: the Admin who last saved it.
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    # The last time any email went out (each kind keeps its own <kind>_last_sent_at for its schedule).
    last_sent_at = models.DateTimeField(null=True, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_ok = models.BooleanField(null=True, blank=True)
    last_message = models.CharField(max_length=500, blank=True)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def kind_setting(self, kind, name):
        """One setting of one kind of file, e.g. ``kind_setting("word", "frequency")``."""
        return getattr(self, f"{kind}_{name}")

    def enabled_kinds(self):
        return [kind for kind in KIND_KEYS if self.kind_setting(kind, "enabled")]

    def __str__(self):
        return "Email backup schedule"
