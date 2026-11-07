"""Sending email: is it set up, who gets it, when a scheduled backup email is due, and building and sending it.

Nothing here is called while a page is being drawn; sending happens in a request the Admin made (Send now, Send a
test) or in the nightly scheduled job (``manage.py send_email_backups``).
"""
import logging
import re
from datetime import date, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone

from accounts.models import Profile
from accounts.suite import KEY_DIARY
from backups import services as backup_services
from backups.models import BackupFile
from diary.wordexport import service as word_export
from diary.wordexport.service import ExportError

from . import sender
from .models import (
    DELIVERY_BOTH_ONE,
    DELIVERY_BOTH_SEPARATE,
    DELIVERY_DATA,
    DELIVERY_WORD,
    FREQ_MONTHLY,
    FREQ_WEEKLY,
)

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

def newest_backup_size():
    latest = BackupFile.objects.defer("data").order_by("-created_at", "-id").first()
    return latest.size_bytes if latest is not None else 0


def _fresh_backup(now):
    latest = BackupFile.objects.order_by("-created_at", "-id").first()
    if latest is not None and now - latest.created_at < timedelta(hours=FRESH_BACKUP_HOURS):
        return latest
    return backup_services.create_backup("manual")


def _data_files(schedule, now):
    backup = _fresh_backup(now)
    return [(backup.filename, bytes(backup.data), GZIP_TYPE)], []


def _word_files(schedule, now):
    """One .docx per live diary profile: ([(name, bytes, type)], [notes about any that could not be made])."""
    files, notes = [], []
    for profile in Profile.objects.filter(program=KEY_DIARY, deleted_at__isnull=True).order_by("name"):
        try:
            exported = word_export.full(profile, schedule.owner, include_review=schedule.include_review, now=now)
        except ExportError as exc:
            notes.append(f"The Word file for {profile.name} could not be made: {exc}")
            continue
        files.append((exported.name, exported.data, exported.content_type))
    return files, notes


def plan_emails(delivery):
    """The emails to send for a delivery choice: a list of emails, each a list of parts ("data" / "word")."""
    return {
        DELIVERY_DATA: [["data"]],
        DELIVERY_WORD: [["word"]],
        DELIVERY_BOTH_ONE: [["data", "word"]],
        DELIVERY_BOTH_SEPARATE: [["data"], ["word"]],
    }.get(delivery, [["data", "word"]])


def fit_to_limit(files, limit_bytes, max_mb):
    """(files that fit within the limit in total, notes about the ones left out). Names are made unique."""
    kept, notes, used, names = [], [], 0, set()
    for name, data, content_type in files:
        if used + len(data) > limit_bytes:
            notes.append(f"{name} ({max(1, len(data) // 1024)} KB) was left out: the files would be more than {max_mb} MB in this email.")
            continue
        base, n = name, 1
        while name in names:
            n += 1
            name = f"{n}-{base}"
        names.add(name)
        kept.append((name, data, content_type))
        used += len(data)
    return kept, notes


def _body(files, notes, now, part_label):
    local = timezone.localtime(now)
    lines = [f"Your Case Law Diary backup ({part_label}), made {local:%Y-%m-%d %H:%M} (IST).", ""]
    if files:
        lines.append("Attached:")
        lines += [f"  - {name} ({max(1, len(data) // 1024)} KB)" for name, data, _ in files]
    else:
        lines.append("No files could be attached.")
    if notes:
        lines += ["", "PLEASE NOTE (this backup is incomplete):"] + [f"  - {n}" for n in notes]
    lines += [
        "",
        "The .json.gz file is a full backup: restore it on the Backups screen. The .docx file is the whole diary as a Word document.",
        "These files hold your private diary. Keep them safe and delete this email if you no longer need it.",
    ]
    return "\n".join(lines)


def _describe_error(exc):
    # Shown on the Admin's screen: our own errors say what is wrong; anything else is reduced to its type.
    return str(exc) if isinstance(exc, ValueError) else sender.describe_smtp_error(exc)


# ------------------------------------------------------------------ sending

def _record(schedule, ok, message, now, sent=None):
    """Save the outcome. ``ok`` False raises the warning bar; ``sent`` (default: ok) says whether to move last_sent_at."""
    sent = ok if sent is None else sent
    schedule.last_attempt_at = now
    schedule.last_ok = ok
    schedule.last_message = message[:500]
    fields = ["last_attempt_at", "last_ok", "last_message"]
    if sent:
        schedule.last_sent_at = now
        fields.append("last_sent_at")
    schedule.save(update_fields=fields)


def send_scheduled_backup(schedule, now=None):
    """Make the files and email them as the schedule's ``delivery`` says. Returns (ok, message); never raises.

    Each email is built, sent and let go before the next, to keep memory low. ``ok`` is False if any email failed OR
    any file had to be left out for size (the email still goes with what fits, and the warning bar tells the Admin).
    Only a send that got at least one email out moves ``last_sent_at``; a total failure is tried again next run.
    """
    now = now or timezone.now()
    recipients = parse_recipients(schedule.recipients)
    if not recipients:
        _record(schedule, False, "FAILED: There is nobody to send to. Add an email address.", now)
        return False, "There is nobody to send to. Add an email address."
    if not is_configured():
        _record(schedule, False, "FAILED: Email is not set up on this server (EMAIL_HOST is missing).", now)
        return False, "Email is not set up on this server (EMAIL_HOST is missing)."
    limit = settings.EMAIL_BACKUP_MAX_MB * 1024 * 1024
    labels = {"data": "JSON backup", "word": "Word export"}
    sent_count, problems, summaries = 0, [], []
    plan = plan_emails(schedule.delivery)
    for number, parts in enumerate(plan, start=1):
        label = " + ".join(labels[p] for p in parts)
        try:
            files, notes = [], []
            for part in parts:
                got, extra = (_data_files if part == "data" else _word_files)(schedule, now)
                files += got
                notes += extra
            files, left_out = fit_to_limit(files, limit, settings.EMAIL_BACKUP_MAX_MB)
            notes += left_out
            if not files:
                raise ValueError("there was nothing to attach. " + " ".join(notes))
            message = sender.build_message(
                f"Case Law Diary backup {timezone.localtime(now):%Y-%m-%d}: {label}" + (" (incomplete)" if notes else ""),
                _body(files, notes, now, label),
                recipients,
            )
            for name, data, content_type in files:
                message.attach(name, data, content_type)
            message.send(fail_silently=False)
        except Exception as exc:
            detail = _describe_error(exc)
            logger.warning("Emailed backup (%s) failed: %s", label, detail)
            problems.append(f"{label}: {detail}")
            continue
        sent_count += 1
        summaries.append(f"{label}: {len(files)} file{'s' if len(files) != 1 else ''}")
        problems += [f"{label}: {n}" for n in notes]
    text = f"Sent {sent_count} of {len(plan)} email{'s' if len(plan) != 1 else ''} to {', '.join(recipients)} ({'; '.join(summaries)})." if sent_count else "Nothing was sent."
    if problems:
        text += " PROBLEMS: " + " | ".join(problems)
    ok = sent_count == len(plan) and not problems
    _record(schedule, ok, text if ok else f"FAILED: {text}", now, sent=sent_count > 0)
    return ok, text


def send_test_email(to):
    """A short message to ``to`` (a list) to prove the settings work. Returns (ok, message); never raises."""
    try:
        if not is_configured():
            raise ValueError("Email is not set up on this server (EMAIL_HOST is missing).")
        if not to:
            raise ValueError("There is nobody to send to. Add an email address.")
        message = sender.build_message(
            "Case Law Diary: test email",
            "This is a test. If you can read it, email from the Case Law Diary works.",
            to,
        )
        message.send(fail_silently=False)
    except Exception as exc:
        detail = _describe_error(exc)
        logger.warning("Test email failed: %s", detail)
        return False, detail
    info = sender.diagnostics()
    return True, (f"Test email sent to {', '.join(to)} from {message.from_email} through {info['host']}:{info['port']}. "
                  "If it does not arrive, check the spam folder; a rejection can also come back later as a bounce email.")
