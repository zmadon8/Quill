"""Sending email: is it set up, who gets it, when each kind of emailed backup is due, and building and sending it.

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
from accounts.profiles import effective_export_name, safe_file_name
from accounts.suite import KEY_DIARY, KEY_FEES
from backups import services as backup_services
from backups.models import BackupFile
from diary.wordexport import service as word_export
from diary.wordexport.service import ExportError

from . import sender
from .models import (
    DEFAULT_MAX_MB,
    FREQ_MONTHLY,
    FREQ_WEEKLY,
    KIND_ARCHIVE,
    KIND_DATA,
    KIND_EXCEL,
    KIND_HTML,
    KIND_KEYS,
    KIND_LABELS,
    KIND_WORD,
)

logger = logging.getLogger(__name__)

MAX_RECIPIENTS = 10
#: The most parts of the price archive that are emailed (plan 17.5, owner-approved); a bigger archive is downloaded instead.
ARCHIVE_MAX_PARTS = 5
#: A stored backup newer than this is emailed as it is; an older one (or none) is replaced by a fresh backup first.
FRESH_BACKUP_HOURS = 20
GZIP_TYPE = "application/gzip"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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


def kind_is_due(schedule, kind, now=None):
    """True if ``kind`` is switched on and its latest planned send has not happened yet (the master switch aside)."""
    if not schedule.kind_setting(kind, "enabled"):
        return False
    now = now or timezone.now()
    wanted = last_due_date(schedule.kind_setting(kind, "frequency"), schedule.kind_setting(kind, "weekday"),
                           schedule.kind_setting(kind, "day_of_month"), timezone.localdate(now))
    last = schedule.kind_setting(kind, "last_sent_at")
    return last is None or timezone.localdate(last) < wanted


def due_kinds(schedule, now=None):
    """The kinds of file whose turn it is, in page order."""
    return [kind for kind in KIND_KEYS if kind_is_due(schedule, kind, now)]


def is_due(schedule, now=None):
    """True if the schedule is on, has someone to send to, and at least one kind of file is due.

    A planned day that was missed (the job did not run, or the send failed) is made up on the next run, and it
    is made up only once.
    """
    if not schedule.enabled or not parse_recipients(schedule.recipients):
        return False
    return bool(due_kinds(schedule, now))


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


def _diary_files(schedule, now, make, what):
    """One file per live diary profile from ``make`` (the Word or the HTML maker): (files, notes)."""
    files, notes = [], []
    for profile in Profile.objects.filter(program=KEY_DIARY, deleted_at__isnull=True).order_by("name"):
        try:
            exported = make(profile, schedule.owner, include_review=schedule.include_review, now=now)
        except ExportError as exc:
            notes.append(f"The {what} file for {profile.name} could not be made: {exc}")
            continue
        files.append((exported.name, exported.data, exported.content_type))
    return files, notes


def _word_files(schedule, now):
    return _diary_files(schedule, now, word_export.full, "Word")


def _html_files(schedule, now):
    # The same single-file HTML copy as the Export page's download, for the whole diary.
    return _diary_files(schedule, now, word_export.offline_copy, "HTML")


def _excel_files(schedule, now):
    """One .xlsx per live Fee Register profile, the same workbook as Fee Register > Settings > Backup."""
    from fees.services import excel_backup
    from fees.services.heavy import heavy_operation

    files, notes = [], []
    day = timezone.localdate(now).isoformat()
    for profile in Profile.objects.filter(program=KEY_FEES, deleted_at__isnull=True).order_by("name"):
        try:
            with heavy_operation("excel_backup"):
                fileobj = excel_backup.export_workbook(profile)
            try:
                data = fileobj.read()
            finally:
                fileobj.close()
        except Exception as exc:  # a busy lock or a bad row: the other files still go
            notes.append(f"The Excel file for {profile.name} could not be made: {exc}")
            continue
        name = safe_file_name(f"{effective_export_name(profile)} Backup {day}.xlsx")
        files.append((name, data, XLSX_TYPE))
    return files, notes


MAKERS = {KIND_DATA: _data_files, KIND_WORD: _word_files, KIND_HTML: _html_files, KIND_EXCEL: _excel_files}
# KIND_ARCHIVE has no maker on purpose: the price archive is built and sent one part at a time by ``_send_archive`` (plan 17.5).


def unique_names(files):
    """The same files with any repeated name made unique ("2-name")."""
    named, seen = [], set()
    for name, data, content_type in files:
        base, n = name, 1
        while name in seen:
            n += 1
            name = f"{n}-{base}"
        seen.add(name)
        named.append((name, data, content_type))
    return named


# ------------------------------------------------------------------ sharing the files out over emails

#: Up to this many pieces the fewest emails are found exactly; above it, largest-first filling is used.
EXACT_PACK_LIMIT = 12


def _first_fit(sizes, limit):
    """Largest first, each into the first email it fits: a list of emails, each a list of indexes."""
    bins, room = [], []
    for i in sorted(range(len(sizes)), key=lambda j: -sizes[j]):
        for b, free in enumerate(room):
            if sizes[i] <= free:
                bins[b].append(i)
                room[b] -= sizes[i]
                break
        else:
            bins.append([i])
            room.append(limit - sizes[i])
    return bins


def _fewest(sizes, limit):
    """The fewest emails of at most ``limit`` each that hold every piece (every piece fits alone)."""
    best = _first_fit(sizes, limit)
    if len(sizes) > EXACT_PACK_LIMIT or len(best) <= 1:
        return best
    order = sorted(range(len(sizes)), key=lambda j: -sizes[j])
    total = sum(sizes)

    def search(k, bins, room):
        nonlocal best
        if len(bins) >= len(best):
            return
        if k == len(order):
            best = [list(b) for b in bins]
            return
        i = order[k]
        # Not enough room left for the rest even if every gap were filled: no better answer down this way.
        rest = sum(sizes[j] for j in order[k:])
        if len(bins) + max(0, -(-(rest - sum(room)) // limit)) >= len(best):
            return
        tried = set()
        for b in range(len(bins)):
            if sizes[i] <= room[b] and room[b] not in tried:
                tried.add(room[b])
                bins[b].append(i)
                room[b] -= sizes[i]
                search(k + 1, bins, room)
                room[b] += sizes[i]
                bins[b].pop()
        bins.append([i])
        room.append(limit - sizes[i])
        search(k + 1, bins, room)
        room.pop()
        bins.pop()

    if -(-total // limit) < len(best):
        search(0, [], [])
    return best


def plan_emails(groups, split, limit_bytes):
    """Share the files out over emails.

    ``groups`` is [(kind, [(name, data, type), ...])]. Without ``split`` everything goes in one email. With it, no
    email carries more than ``limit_bytes`` of files and as few emails as possible are sent: each kind's files stay
    together in one email when that needs no more emails than splitting them up, and a single file that is larger
    than the limit by itself goes alone in its own email. Returns a list of emails, each [(kind, file), ...].
    """
    pieces = [(kind, f) for kind, files in groups for f in files]
    if not pieces:
        return []
    if not split:
        return [pieces]
    alone = [[p] for p in pieces if len(p[1][1]) > limit_bytes]
    fitting = [(kind, [f for f in files if len(f[1]) <= limit_bytes]) for kind, files in groups]
    fitting = [(kind, files) for kind, files in fitting if files]
    singles = [(kind, f) for kind, files in fitting for f in files]
    by_file = _fewest([len(f[1]) for _, f in singles], limit_bytes) if singles else []
    # The same, keeping each kind together (a kind that is too big for one email is split by file anyway).
    units = []
    for kind, files in fitting:
        if sum(len(f[1]) for f in files) <= limit_bytes:
            units.append([(kind, f) for f in files])
        else:
            units += [[(kind, f)] for f in files]
    by_kind = _fewest([sum(len(f[1]) for _, f in u) for u in units], limit_bytes) if units else []
    if units and len(by_kind) <= len(by_file):
        emails = [[p for u in b for p in units[u]] for b in by_kind]
    else:
        emails = [[singles[i] for i in b] for b in by_file]
    order = {kind: n for n, kind in enumerate(KIND_KEYS)}
    emails = [sorted(e, key=lambda p: order[p[0]]) for e in emails]
    emails.sort(key=lambda e: min(order[p[0]] for p in e))
    return emails + alone


def _body(files, notes, now, label, number, count, over_limit):
    local = timezone.localtime(now)
    which = f" (email {number} of {count})" if count > 1 else ""
    lines = [f"Your {sender.site_name()} backup{which}: {label}. Made {local:%Y-%m-%d %H:%M} (IST).", ""]
    lines.append("Attached:")
    lines += [f"  - {name} ({max(1, len(data) // 1024)} KB)" for name, data, _ in files]
    if over_limit:
        lines += ["", "This file is larger than the most you set for one email, so it was sent by itself. If your email "
                  "service refuses it, raise the limit or switch this kind of file off."]
    if notes:
        lines += ["", "PLEASE NOTE (this backup is incomplete):"] + [f"  - {n}" for n in notes]
    lines += [
        "",
        "The .json.gz file is a full backup: restore it on the Backups screen. The .docx and .html files are the whole "
        "Case Law Diary to read (one per diary profile). The .xlsx files are the Fee Register sheets (one per profile).",
        "These files hold your private data. Keep them safe and delete this email if you no longer need it.",
    ]
    return "\n".join(lines)


def _describe_error(exc):
    # Shown on the Admin's screen: our own errors say what is wrong; anything else is reduced to its type.
    return str(exc) if isinstance(exc, ValueError) else sender.describe_smtp_error(exc)


# ------------------------------------------------------------------ sending

def _record(schedule, ok, message, now, sent=None, sent_kinds=()):
    """Save the outcome. ``ok`` False raises the warning bar; ``sent`` (default: ok) says whether to move last_sent_at.
    Each kind in ``sent_kinds`` went out in full, so its own schedule moves on."""
    sent = ok if sent is None else sent
    schedule.last_attempt_at = now
    schedule.last_ok = ok
    schedule.last_message = message[:500]
    fields = ["last_attempt_at", "last_ok", "last_message"]
    if sent:
        schedule.last_sent_at = now
        fields.append("last_sent_at")
    for kind in sent_kinds:
        setattr(schedule, f"{kind}_last_sent_at", now)
        fields.append(f"{kind}_last_sent_at")
    schedule.save(update_fields=fields)


def _fail(schedule, text, now):
    _record(schedule, False, f"FAILED: {text}", now)
    return False, text


def send_scheduled_backup(schedule, now=None, kinds=None):
    """Make the files of each kind in ``kinds`` (default: the kinds that are due) and email them. Returns (ok, message);
    never raises.

    By default every file goes in one email. With ``split_emails`` on, the files are shared out so that no email
    carries more than ``max_attachment_mb``, in as few emails as possible. ``ok`` is False if any email failed or any
    file could not be made (the warning bar tells the Admin). A kind's own schedule moves on only when all its files
    went out; anything else is tried again at the next nightly run.
    """
    now = now or timezone.now()
    recipients = parse_recipients(schedule.recipients)
    if not recipients:
        return _fail(schedule, "There is nobody to send to. Add an email address.", now)
    if not is_configured():
        return _fail(schedule, "Email is not set up on this server (EMAIL_HOST is missing).", now)
    kinds = due_kinds(schedule, now) if kinds is None else [k for k in KIND_KEYS if k in kinds]
    if not kinds:
        return _fail(schedule, "Nothing to send: tick at least one kind of file.", now)
    groups, problems, empty, notes_for, failed_kinds = [], [], [], {}, set()
    for kind in kinds:
        if kind == KIND_ARCHIVE:
            continue
        try:
            files, notes = MAKERS[kind](schedule, now)
        except Exception as exc:
            files, notes = [], [f"could not be made: {_describe_error(exc)}"]
        notes_for[kind] = [f"{KIND_LABELS[kind]}: {n}" for n in notes]
        problems += notes_for[kind]
        if notes:
            failed_kinds.add(kind)  # a file is missing, so this kind is tried again next run
        if files:
            groups.append((kind, files))
        elif not notes:
            empty.append(kind)  # nothing of this kind exists (no profiles): nothing to send, and nothing wrong
    limit = max(1, schedule.max_attachment_mb or DEFAULT_MAX_MB) * 1024 * 1024
    emails = plan_emails(groups, schedule.split_emails, limit)
    sent_count, summaries = 0, []
    stamp = f"{timezone.localtime(now):%Y-%m-%d}"
    for number, pieces in enumerate(emails, start=1):
        in_email = list(dict.fromkeys(kind for kind, _ in pieces))
        label = " + ".join(KIND_LABELS[k] for k in in_email)
        files = unique_names([f for _, f in pieces])
        over = schedule.split_emails and len(pieces) == 1 and len(pieces[0][1][1]) > limit
        which = f" ({number} of {len(emails)})" if len(emails) > 1 else ""
        notes = [n for k in in_email for n in notes_for[k]]
        try:
            message = sender.build_message(
                f"{sender.site_name()} backup {stamp}{which}: {label}" + (" (incomplete)" if notes else ""),
                _body(files, notes, now, label, number, len(emails), over),
                recipients,
            )
            for name, data, content_type in files:
                message.attach(name, data, content_type)
            message.send(fail_silently=False)
        except Exception as exc:
            detail = _describe_error(exc)
            logger.warning("Emailed backup (%s) failed: %s", label, detail)
            problems.append(f"Email {number} ({label}): {detail}")
            failed_kinds.update(in_email)
            continue
        sent_count += 1
        summaries.append(f"{label}: {len(pieces)} file{'s' if len(pieces) != 1 else ''}")
    if KIND_ARCHIVE in kinds:
        archive_sent, archive_planned, archive_problems, archive_summary = _send_archive(schedule, recipients, now)
        sent_count += archive_sent
        if archive_summary:
            summaries.append(archive_summary)
        if archive_problems:
            problems += [f"{KIND_LABELS[KIND_ARCHIVE]}: {p}" for p in archive_problems]
            failed_kinds.add(KIND_ARCHIVE)
        elif archive_planned == 0:
            empty.append(KIND_ARCHIVE)
        emails = emails + [None] * archive_planned
    planned = len(emails)
    sent_kinds = [k for k in kinds if k not in failed_kinds]
    if sent_count:
        text = f"Sent {sent_count} of {planned} email{'s' if planned != 1 else ''} to {', '.join(recipients)} ({'; '.join(summaries)})."
    else:
        text = "Nothing was sent."
    if empty:
        text += " Nothing to attach for: " + ", ".join(KIND_LABELS[k] for k in empty) + "."
    if problems:
        text += " PROBLEMS: " + " | ".join(problems)
    ok = not problems and (sent_count > 0 or bool(empty))
    _record(schedule, ok, text if ok else f"FAILED: {text}", now, sent=sent_count > 0, sent_kinds=sent_kinds)
    return ok, text


def send_test_email(to):
    """A short message to ``to`` (a list) to prove the settings work. Returns (ok, message); never raises."""
    try:
        if not is_configured():
            raise ValueError("Email is not set up on this server (EMAIL_HOST is missing).")
        if not to:
            raise ValueError("There is nobody to send to. Add an email address.")
        message = sender.build_message(
            f"{sender.site_name()}: test email",
            f"This is a test. If you can read it, email from {sender.site_name()} works.",
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


# ------------------------------------------------------------------ the price archive (plan 17.5)

def _send_archive(schedule, recipients, now):
    """Build the Investments price archive and send each part in an email of its own, whatever the split setting says.

    Parts are written to temporary files and read back one at a time, so memory stays near one part. Returns
    ``(emails sent, emails planned, problems, summary text)``. More than the cap of parts means nothing is sent and the Admin is told
    to download it instead (the warning bar shows the problem)."""
    from investments.services import archive as archive_service
    from investments.services import locks, pruning
    from investments.models import PriceMaintenanceLog

    limit = max(1, schedule.max_attachment_mb or DEFAULT_MAX_MB) * 1024 * 1024
    try:
        with locks.heavy("price_archive"):
            pruned = archive_service.effective_pruned(schedule.archive_version)
            parts = archive_service.build(pruned=pruned, max_part_bytes=limit, now=now)
    except Exception as exc:
        PriceMaintenanceLog.objects.create(kind="archive", ok=False, message=f"not sent: {_describe_error(exc)}"[:300])
        return 0, 0, [f"could not be made: {_describe_error(exc)}"], ""
    try:
        if not any(parts):
            return 0, 0, [], ""
        if len(parts) > ARCHIVE_MAX_PARTS:
            note = (f"the archive needs {len(parts)} parts, more than the {ARCHIVE_MAX_PARTS} that can be emailed, so it was not sent. "
                    "Download it from Investments > Settings > Price history.")
            PriceMaintenanceLog.objects.create(kind="archive", ok=False, message=note[:300])
            return 0, 0, [note], ""
        sent, problems = 0, []
        stamp = f"{timezone.localtime(now):%-d %b %Y}"
        for number, path in enumerate(parts, start=1):
            data = path.read_bytes()
            which = f"part {number} of {len(parts)}"
            try:
                message = sender.build_message(
                    f"{sender.site_name()}: price archive, {which}, {stamp}",
                    f"Investments price archive ({'pruned' if pruned else 'full'}), {which}, made {timezone.localtime(now):%Y-%m-%d %H:%M} (IST).\n\n"
                    f"Attached: {path.name} ({max(1, len(data) // 1024)} KB).\n\nRestore it on Investments > Settings > Upload price history, or with "
                    "'python manage.py import_prices --archive file.zip'. It holds only prices, no transactions.",
                    recipients)
                message.attach(path.name, data, "application/zip")
                message.send(fail_silently=False)
                sent += 1
            except Exception as exc:
                problems.append(f"{which}: {_describe_error(exc)}")
            finally:
                del data
        PriceMaintenanceLog.objects.create(kind="archive", ok=not problems, size_bytes=sum(p.stat().st_size for p in parts),
                                           counts={"parts": len(parts), "sent": sent}, message=("sent" if not problems else "; ".join(problems))[:300])
        if sent and not problems:
            pruning.get_settings()
            from investments.models import PriceHistorySettings

            PriceHistorySettings.objects.filter(pk=1).update(last_archive_at=now)
        return sent, len(parts), problems, f"price archive: {len(parts)} part{'s' if len(parts) != 1 else ''}"
    finally:
        for path in parts:
            path.unlink(missing_ok=True)
        if parts:
            try:
                parts[0].parent.rmdir()
            except OSError:
                pass
