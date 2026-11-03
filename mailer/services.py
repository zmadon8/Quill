"""Sending email: is it set up, who gets it, when a scheduled backup email is due, and building and sending it.

Nothing here is called while a page is being drawn; sending happens in a request the Admin made (Send now, Send a
test) or in the nightly scheduled job (``manage.py send_email_backups``).
"""
import logging
import re
from datetime import date, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.utils import timezone

from accounts.models import Profile
from accounts.suite import KEY_DIARY
from backups import services as backup_services
from backups.models import BackupFile
from diary.wordexport import service as word_export
from diary.wordexport.service import ExportError

from .models import FREQ_DAILY, FREQ_MONTHLY, FREQ_WEEKLY, EmailBackupSchedule

logger = logging.getLogger(__name__)

MAX_RECIPIENTS = 10
#: A stored backup newer than this is emailed as it is; an older one (or none) is replaced by a fresh backup first.
FRESH_BACKUP_HOURS = 20
GZIP_TYPE = "application/gzip"


def is_configured():
    """True if this server can send email at all (an SMTP host is set, or DEBUG / tests use a local backend)."""
    return settings.EMAIL_BACKEND != "mailer.backends.NotConfiguredBackend"


def parse_recipients(text):
    """The addresses in ``text`` (separated by commas, semicolons, spaces or new lines), without repeats, in order."""
    found, seen = [], set()
    for part in re.split(r"[,;\s]+", text or ""):
        part = part.strip()
        if part and part.lower() not in seen:
            seen.add(part.lower())
            found.append(part)
    return found


def check_recipients(text):
    """(addresses, error message or ""). Every address must look right; at most MAX_RECIPIENTS."""
    addresses = parse_recipients(text)
    for address in addresses:
        try:
            validate_email(address)
        except ValidationError:
            return addresses, f"\u201c{address}\u201d is not a valid email address."
    if len(addresses) > MAX_RECIPIENTS:
        return addresses, f"At most {MAX_RECIPIENTS} addresses."
    return addresses, ""


# ------------------------------------------------------------------ when is a send due

def last_due_date(frequency, weekday, day_of_month, today):
    """The most recent date (today or earlier) on which a send was meant to happen."""
    if frequency == FREQ_WEEKLY:
        return today - timedelta(days=(today.weekday() - weekday) % 7)
    if frequency == FREQ_MONTHLY:
        day = max(1, min(28, day_of_month))
        if today.day >= day:
            return date(today.year, today.month, day)
        year, month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
        return date(year, month, day)
    return today


def is_due(schedule, now=None):
    """True if the schedule is on, has someone to send to, and the latest planned send has not happened yet.

    A planned day that was missed (the job did not run, or the send failed) is made up on the next run, and it
    is made up only once.
    """
    if not schedule.enabled or not parse_recipients(schedule.recipients):
        return False
    now = now or timezone.now()
    today = timezone.localdate(now)
    wanted = last_due_date(schedule.frequency, schedule.weekday, schedule.day_of_month, today)
    return schedule.last_sent_at is None or timezone.localdate(schedule.last_sent_at) < wanted


# ------------------------------------------------------------------ what is attached

def _fresh_backup(now):
    latest = BackupFile.objects.order_by("-created_at", "-id").first()
    if latest is not None and now - latest.created_at < timedelta(hours=FRESH_BACKUP_HOURS):
        return latest
    return backup_services.create_backup("manual")


def collect_attachments(schedule, now=None):
    """([(file name, bytes, content type)], [notes about what was left out]) within EMAIL_BACKUP_MAX_MB in total."""
    now = now or timezone.now()
    limit = settings.EMAIL_BACKUP_MAX_MB * 1024 * 1024
    files, notes, used, names = [], [], 0, set()

    def add(name, data, content_type):
        nonlocal used
        if used + len(data) > limit:
            notes.append(f"{name} ({len(data) // 1024} KB) was left out: the files would be more than {settings.EMAIL_BACKUP_MAX_MB} MB in all.")
            return
        base, n = name, 1
        while name in names:
            n += 1
            name = f"{n}-{base}"
        names.add(name)
        files.append((name, data, content_type))
        used += len(data)

    if schedule.include_data:
        backup = _fresh_backup(now)
        add(backup.filename, bytes(backup.data), GZIP_TYPE)
    if schedule.include_word:
        profiles = Profile.objects.filter(program=KEY_DIARY, deleted_at__isnull=True).order_by("name")
        for profile in profiles:
            try:
                exported = word_export.full(profile, schedule.owner, include_review=schedule.include_review, now=now)
            except ExportError as exc:
                notes.append(f"The Word file for {profile.name} could not be made: {exc}")
                continue
            add(exported.name, exported.data, exported.content_type)
    return files, notes


def _body(files, notes, now):
    local = timezone.localtime(now)
    lines = [f"Your Case Law Diary backup, made {local:%Y-%m-%d %H:%M} (IST).", ""]
    if files:
        lines.append("Attached:")
        lines += [f"  - {name} ({max(1, len(data) // 1024)} KB)" for name, data, _ in files]
    else:
        lines.append("No files could be attached.")
    if notes:
        lines += ["", "Please note:"] + [f"  - {n}" for n in notes]
    lines += [
        "",
        "The .json.gz file is a full backup: restore it on the Backups screen. The .docx file is the whole diary as a Word document.",
        "These files hold your private diary. Keep them safe and delete this email if you no longer need it.",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ sending

def _record(schedule, ok, message, now):
    schedule.last_attempt_at = now
    schedule.last_ok = ok
    schedule.last_message = message[:500]
    fields = ["last_attempt_at", "last_ok", "last_message"]
    if ok:
        schedule.last_sent_at = now
        fields.append("last_sent_at")
    schedule.save(update_fields=fields)


def send_scheduled_backup(schedule, now=None):
    """Make the files and email them to the recipients. Returns (ok, message); never raises, and records the result.

    Only a successful send moves ``last_sent_at``, so a failed send is tried again on the next run.
    """
    now = now or timezone.now()
    recipients = parse_recipients(schedule.recipients)
    try:
        if not recipients:
            raise ValueError("There is nobody to send to. Add an email address.")
        if not (schedule.include_data or schedule.include_word):
            raise ValueError("Nothing is chosen to send. Tick the backup file, the Word file, or both.")
        if not is_configured():
            raise ValueError("Email is not set up on this server (EMAIL_HOST is missing).")
        files, notes = collect_attachments(schedule, now)
        if not files:
            raise ValueError("There was nothing to attach. " + " ".join(notes))
        message = EmailMessage(
            subject=f"Case Law Diary backup {timezone.localtime(now):%Y-%m-%d}",
            body=_body(files, notes, now),
            to=recipients,
        )
        for name, data, content_type in files:
            message.attach(name, data, content_type)
        message.send(fail_silently=False)
    except Exception as exc:
        # The text is shown on the Admin's screen: our own errors say what is wrong; anything else is reduced to its type.
        detail = str(exc) if isinstance(exc, ValueError) else exc.__class__.__name__ + (f": {exc}" if str(exc) else "")
        logger.warning("Emailed backup failed: %s", detail)
        _record(schedule, False, f"FAILED: {detail}", now)
        return False, detail
    summary = f"Sent to {', '.join(recipients)} with {len(files)} file{'s' if len(files) != 1 else ''}."
    if notes:
        summary += " " + " ".join(notes)
    _record(schedule, True, summary, now)
    return True, summary


def send_test_email(to):
    """A short message to ``to`` (a list) to prove the settings work. Returns (ok, message); never raises."""
    try:
        if not is_configured():
            raise ValueError("Email is not set up on this server (EMAIL_HOST is missing).")
        if not to:
            raise ValueError("There is nobody to send to. Add an email address.")
        EmailMessage(
            subject="Case Law Diary: test email",
            body="This is a test. If you can read it, email from the Case Law Diary works.",
            to=list(to),
        ).send(fail_silently=False)
    except Exception as exc:
        detail = str(exc) if isinstance(exc, ValueError) else exc.__class__.__name__ + (f": {exc}" if str(exc) else "")
        logger.warning("Test email failed: %s", detail)
        return False, detail
    return True, f"Test email sent to {', '.join(to)}."
