"""Create, prune, validate, preview and restore backups.

Backups are stored inside the database (BackupFile.data), never on disk.
"""
import gzip
import hashlib
import json
import logging
import zlib

from django.conf import settings
from django.core import serializers
from django.core.management.color import no_style
from django.db import connection, transaction
from django.utils import timezone

from . import policy, registry
from .models import BackupFile, BackupLog

logger = logging.getLogger(__name__)

FORMAT_MARKER = "judgment-diary-backup"
FORMAT_VERSION = 1


class BackupError(Exception):
    """A problem that can be shown to the owner in plain language."""


def _label_key(label):
    return label.lower()


def _build_document(now):
    models_out = {}
    counts = {}
    for model in registry.get_models():
        label = model._meta.label
        text = serializers.serialize(
            "json",
            model._default_manager.order_by("pk"),
            fields=registry.field_names(model),
            use_natural_foreign_keys=False,
            use_natural_primary_keys=False,
        )
        records = json.loads(text)
        models_out[label] = records
        counts[label] = len(records)
    document = {
        "format": FORMAT_MARKER,
        "format_version": FORMAT_VERSION,
        "created_at": now.isoformat(),
        "models": models_out,
        "counts": counts,
    }
    return document, counts


def _log_failure(kind, started, exc, user):
    # Runs outside the failed transaction so the failure is always recorded.
    try:
        with transaction.atomic():
            BackupLog.objects.create(
                started_at=started,
                finished_at=timezone.now(),
                kind=kind,
                success=False,
                message=str(exc) or exc.__class__.__name__,
                created_by=user if user is not None and user.pk else None,
            )
    except Exception:  # pragma: no cover - logging must never hide the real error
        logger.exception("Could not write the backup failure log")


def create_backup(kind, user=None):
    """Make a full backup and store it. Returns the BackupFile.

    On any error a failed BackupLog row is written and the error is re-raised.
    """
    started = timezone.now()
    try:
        with transaction.atomic():
            document, counts = _build_document(started)
            raw = gzip.compress(json.dumps(document).encode("utf-8"))
            filename = f"judgment-diary-backup-{started:%Y%m%d-%H%M%S}-{kind}.json.gz"
            backup = BackupFile.objects.create(
                created_at=started,
                kind=kind,
                filename=filename,
                data=raw,
                size_bytes=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
                record_counts=counts,
                created_by=user,
            )
            BackupLog.objects.create(
                started_at=started,
                finished_at=timezone.now(),
                kind=kind,
                success=True,
                message=f"Backup created: {sum(counts.values())} records.",
                size_bytes=len(raw),
                backup=backup,
                created_by=user,
            )
    except Exception as exc:
        _log_failure(kind, started, exc, user)
        raise
    return backup


def prune_old_backups(now=None, retention_days=None):
    """Delete backups past the retention period (never the newest one).

    Never raises: a failure is written to the log instead. Returns the number removed.
    """
    now = now or timezone.now()
    if retention_days is None:
        retention_days = settings.BACKUP_RETENTION_DAYS
    started = timezone.now()
    try:
        with transaction.atomic():
            entries = list(BackupFile.objects.values_list("id", "created_at"))
            expired = policy.select_expired(entries, now, retention_days)
            if expired:
                BackupFile.objects.filter(id__in=expired).delete()
            BackupLog.objects.create(
                started_at=started,
                finished_at=timezone.now(),
                kind="prune",
                success=True,
                message=f"Removed {len(expired)} old backup(s).",
            )
        return len(expired)
    except Exception as exc:
        logger.exception("Pruning old backups failed")
        _log_failure("prune", started, exc, None)
        return 0


def parse_backup(raw, max_bytes):
    """Check an uploaded or stored backup and return the parsed document.

    Raises BackupError with a plain-language message if it is not usable.
    """
    raw = bytes(raw)
    try:
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        data = decompressor.decompress(raw, max_bytes + 1)
        complete = decompressor.eof
    except zlib.error:
        raise BackupError("This is not a backup file (it is not a compressed .gz file).")
    if len(data) > max_bytes:
        raise BackupError("This file is too large to be a valid backup.")
    if not complete:
        raise BackupError("This backup file is incomplete or damaged.")
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise BackupError("This is not a backup file (the contents cannot be read).")
    if not isinstance(document, dict) or document.get("format") != FORMAT_MARKER:
        raise BackupError("This is not a Judgment Diary backup file.")
    if document.get("format_version") != FORMAT_VERSION:
        raise BackupError("This backup was made by a different version and cannot be read here.")
    models_in_file = document.get("models")
    if not isinstance(models_in_file, dict):
        raise BackupError("This backup file is damaged (no data section).")
    known = set(registry.BACKUP_MODELS)
    unknown = [label for label in models_in_file if label not in known]
    if unknown:
        raise BackupError("This backup contains data this version does not know: " + ", ".join(unknown))
    missing = [label for label in registry.BACKUP_MODELS if label not in models_in_file]
    if missing:
        raise BackupError("This backup file is missing data: " + ", ".join(missing))
    for label, records in models_in_file.items():
        if not isinstance(records, list):
            raise BackupError(f"This backup file is damaged (bad data for {label}).")
        for record in records:
            if (
                not isinstance(record, dict)
                or record.get("model") != _label_key(label)
                or "pk" not in record
                or not isinstance(record.get("fields"), dict)
            ):
                raise BackupError(f"This backup file is damaged (bad record in {label}).")
    return document


def _file_has_active_admin(document):
    for record in document["models"].get("accounts.User", []):
        fields = record["fields"]
        if fields.get("is_superuser") and fields.get("is_active", True):
            return True
    return False


def preview_restore(document):
    """Describe what a restore would change, one row per record type."""
    rows = []
    for model in registry.get_models():
        label = model._meta.label
        pk_field = model._meta.pk
        file_records = document["models"].get(label, [])
        file_pks = {pk_field.to_python(record["pk"]) for record in file_records}
        db_pks = set(model._default_manager.values_list("pk", flat=True))
        row = {
            "label": label,
            "name": model._meta.verbose_name_plural.title(),
            "in_file": len(file_pks),
            "in_database_now": len(db_pks),
            "would_be_added": len(file_pks - db_pks),
            "would_be_removed": len(db_pks - file_pks),
            "unchanged_or_overwritten": len(file_pks & db_pks),
            "added_names": [],
            "removed_names": [],
        }
        if label == "accounts.User":
            row["added_names"] = sorted(
                record["fields"].get("username", "?")
                for record in file_records
                if pk_field.to_python(record["pk"]) not in db_pks
            )
            row["removed_names"] = sorted(
                model._default_manager.exclude(pk__in=file_pks).values_list("username", flat=True)
            )
        rows.append(row)
    return rows


def restore_backup(document, user):
    """Replace the current data with the contents of ``document``.

    A safety backup is taken and committed first. The replacement itself is all
    or nothing: any error rolls everything back.
    """
    if not _file_has_active_admin(document):
        raise BackupError(
            "This backup has no active Admin user, so nobody could sign in afterwards. "
            "Nothing was changed."
        )
    try:
        create_backup("pre_restore", user)
    except Exception as exc:
        raise BackupError(f"The safety backup could not be made, so nothing was changed. ({exc})")

    started = timezone.now()
    try:
        with transaction.atomic():
            batches = []
            for model in registry.get_models():
                records = document["models"].get(model._meta.label, [])
                batches.append((model, list(serializers.deserialize("json", json.dumps(records)))))
            for model, _objects in reversed(batches):
                model._default_manager.all().delete()
            for _model, objects in batches:
                for obj in objects:
                    obj.save()
            sql = connection.ops.sequence_reset_sql(no_style(), [m for m, _ in batches])
            if sql:
                with connection.cursor() as cursor:
                    for statement in sql:
                        cursor.execute(statement)
    except Exception as exc:
        _log_failure("restore", started, exc, user)
        raise BackupError(f"The restore failed and nothing was changed. ({exc})")

    counts = {m._meta.label: len(objs) for m, objs in batches}
    survivor = None
    if user is not None and user.pk and type(user)._default_manager.filter(pk=user.pk).exists():
        survivor = user
    BackupLog.objects.create(
        started_at=started,
        finished_at=timezone.now(),
        kind="restore",
        success=True,
        message="Restored: " + ", ".join(f"{label} {n}" for label, n in counts.items()),
        created_by=survivor,
    )
    return counts
