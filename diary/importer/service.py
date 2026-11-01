"""Ties the reader, plan, loader and reports together for the screen and the command."""
from django.utils import timezone

from backups import services as backup_services

from . import loader, report
from .docx_reader import DocxError, file_digest, read_docx
from .plan import build_plan

__all__ = ["DocxError", "ImportRefused", "dry_run", "reconcile", "run_import"]

ImportRefused = loader.ImportRefused


def _now():
    return timezone.now().strftime("%Y-%m-%d %H:%M:%S %Z")


def _prepare(data):
    paragraphs, notes = read_docx(data)
    return build_plan(paragraphs, notes)


def dry_run(data, filename):
    """Read the file and describe what an import would do. Saves nothing. Returns (plan, text)."""
    plan = _prepare(data)
    return plan, report.dry_run_report(plan, filename, file_digest(data), len(data), _now())


def reconcile(data, filename, profile):
    """Compare the file with what profile holds. Read-only. Returns (plan, text)."""
    plan = _prepare(data)
    text = report.reconciliation_report(plan, loader.read_back(profile), filename, file_digest(data), _now(),
                                        profile.name)
    return plan, text


def run_import(data, filename, profile, user=None, expected_sha256=None):
    """Back up, import in one transaction, back up again, reconcile. Returns (text, notes).

    Raises ImportRefused (nothing changed) when the file differs from the approved dry run, the file
    has problems, the profile is not empty of earlier imports/clashes, or the safety backup fails.
    ``notes`` are plain sentences for the user (backup results).
    """
    if expected_sha256 and expected_sha256 != file_digest(data):
        raise ImportRefused("This is not the same file as the one in the dry run. Run the dry run again.")
    plan = _prepare(data)
    state, messages = loader.check_state(plan, profile)
    if state == loader.STATE_DONE:
        _, text = reconcile(data, filename, profile)
        return text, messages
    if state != loader.STATE_FRESH:
        raise ImportRefused(" ".join(messages))
    notes = []
    try:
        before = backup_services.create_backup("manual", user)
    except Exception as exc:  # the import must not start without a safety copy
        raise ImportRefused(f"The backup before the import could not be made, so nothing was changed. ({exc})")
    notes.append(f"Backup before the import: {before.filename}.")
    created = loader.import_plan(plan, profile, user)
    notes.append(f"{created} records imported into profile '{profile.name}'.")
    try:
        after = backup_services.create_backup("manual", user)
        notes.append(f"Backup after the import: {after.filename}.")
    except Exception as exc:
        notes.append(f"WARNING: the import is saved, but the backup after it failed ({exc}). Make one by hand.")
    _, text = reconcile(data, filename, profile)
    return text, notes
