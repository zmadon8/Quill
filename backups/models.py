from django.conf import settings
from django.db import models
from django.utils import timezone

BACKUP_KINDS = [
    ("daily", "Daily"),
    ("manual", "Manual"),
    ("pre_restore", "Before restore"),
    ("pre_migration", "Before update"),
    ("uploaded", "Uploaded"),
    ("pre_import", "Before import"),
    ("post_import", "After import"),
    ("pre_clear", "Before clearing profile"),
]

#: Import and clear backups: the only kinds an Admin may delete by hand (they also count toward the newest-30 limit).
KEEP_KINDS = ("pre_import", "post_import", "pre_clear")

LOG_KINDS = [
    ("daily", "Daily"),
    ("manual", "Manual"),
    ("pre_restore", "Before restore"),
    ("pre_migration", "Before update"),
    ("pre_import", "Before import"),
    ("post_import", "After import"),
    ("pre_clear", "Before clearing profile"),
    ("restore", "Restore"),
    ("prune", "Clean-up"),
    ("offsite", "Off-site copy"),
]


class BackupFile(models.Model):
    """A whole backup, stored inside the database as gzip bytes.

    Never included in backup files themselves.
    """

    created_at = models.DateTimeField(default=timezone.now)
    kind = models.CharField(max_length=20, choices=BACKUP_KINDS)
    filename = models.CharField(max_length=200)
    data = models.BinaryField()
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    record_counts = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    note = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.filename


class BackupLog(models.Model):
    """One line of history: a backup, restore or clean-up, and whether it worked.

    Never included in backup files themselves.
    """

    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    kind = models.CharField(max_length=20, choices=LOG_KINDS)
    success = models.BooleanField(default=False)
    message = models.TextField(blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    backup = models.ForeignKey(
        BackupFile,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    def __str__(self):
        return f"{self.kind} {'ok' if self.success else 'FAILED'} at {self.started_at:%Y-%m-%d %H:%M}"
