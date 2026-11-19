"""Create, prune, validate, preview and restore backups.

Backups are stored inside the database (BackupFile.data), never on disk.
"""
import datetime
import gzip
import hashlib
import json
import logging
import re
import tempfile
import zlib

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import serializers
from django.core.serializers.json import DjangoJSONEncoder
from django.core.management.color import no_style
from django.db import connection, transaction
from django.db.migrations.loader import MigrationLoader
from django.utils import timezone

from fees.services.heavy import Busy, heavy_operation

from . import policy, registry, storage as offsite_storage
from .models import BackupFile, BackupLog

logger = logging.getLogger(__name__)

FORMAT_MARKER = "judgment-diary-backup"
FORMAT_VERSION = 1


class _ExactJSONEncoder(DjangoJSONEncoder):
    """Like Django's encoder, but keeps full microseconds on datetimes and times.

    DjangoJSONEncoder cuts them to milliseconds, which would change stored values on
    restore. The file layout is unchanged, so FORMAT_VERSION stays 1 and older files
    (millisecond values) still load.
    """

    def default(self, o):
        if isinstance(o, datetime.datetime):
            value = o.isoformat()
            return value[:-6] + "Z" if value.endswith("+00:00") else value
        if isinstance(o, datetime.time):
            if o.utcoffset() is not None:
                raise ValueError("JSON can't represent timezone-aware times.")
            return o.isoformat()
        return super().default(o)
GZIP_MAGIC = b"\x1f\x8b"


class BackupError(Exception):
    """A problem that can be shown to the owner in plain language."""


def _label_key(label):
    return label.lower()


def applied_state_apps():
    """Historical models for the migrations that are APPLIED in the database right now.

    Used for the pre-migration backup: the code's models may already describe
    tables or columns that the pending migrations have not created yet.
    """
    loader = MigrationLoader(connection)
    nodes = [key for key in loader.applied_migrations if key in loader.graph.nodes]
    return loader.project_state(nodes).apps


def _backup_labels(app_registry=None):
    """Labels that make up the ``models`` section, in backup order (parents first).

    Registry models missing from a historical state have no table yet, so they are recorded as empty.
    Optional models stay out of the file then, so an older state is read as an older backup.
    """
    seeded = [
        label
        for label in registry.BACKUP_MODELS
        if not (label in registry.OPTIONAL_MODELS and app_registry is not None)
    ]
    present = {model._meta.label for model in registry.get_models(app_registry)}
    # A model present in the state but somehow not pre-seeded (future-proofing) is still appended.
    for label in present:
        if label not in seeded:
            seeded.append(label)
    return seeded


def _serialize_model_records(model):
    """Serialise one model to a list of record dicts, exactly as the backup file stores them.

    Same field selection, ordering and encoder as the streaming writer, so a caller can compare the
    two builders record by record.
    """
    text = serializers.serialize(
        "json",
        model._default_manager.order_by("pk"),
        fields=registry.field_names(model),
        use_natural_foreign_keys=False,
        use_natural_primary_keys=False,
        cls=_ExactJSONEncoder,
    )
    return json.loads(text)


def _build_document(now, app_registry=None):
    """Build the whole backup document in memory.

    Kept as the reference builder: the streaming ``write_document`` must produce a gzip whose parsed
    content equals this document. ``create_backup`` uses the streaming writer; the equality is a test.
    """
    models_out = {}
    counts = {}
    for label in _backup_labels(app_registry):
        models_out[label] = []
        counts[label] = 0
    for model in registry.get_models(app_registry):
        records = _serialize_model_records(model)
        models_out[model._meta.label] = records
        counts[model._meta.label] = len(records)
    document = {
        "format": FORMAT_MARKER,
        "format_version": FORMAT_VERSION,
        "created_at": now.isoformat(),
        "models": models_out,
        "counts": counts,
    }
    return document, counts


def _iter_model_record_chunks(model, chunk_size=500):
    """Yield already-serialised record JSON text for ``model``, a chunk at a time.

    Each yielded string is the inner text of a JSON array (no surrounding brackets), so chunks can be
    joined with commas straight into the file. ``queryset.iterator`` keeps only one chunk of rows in
    memory at a time, and the serialiser is given the same fields and encoder as ``_build_document``.
    """
    field_names = registry.field_names(model)
    queryset = model._default_manager.order_by("pk")
    for rows in _chunked(queryset.iterator(chunk_size=chunk_size), chunk_size):
        text = serializers.serialize(
            "json",
            rows,
            fields=field_names,
            use_natural_foreign_keys=False,
            use_natural_primary_keys=False,
            cls=_ExactJSONEncoder,
        )
        # serializers.serialize returns "[ {..}, {..} ]"; drop the brackets, keep the records.
        inner = text.strip()
        inner = inner[1:-1] if inner.startswith("[") and inner.endswith("]") else inner
        count = len(rows)
        yield inner, count


def _chunked(iterable, size):
    """Group an iterable into lists of at most ``size`` items (one chunk alive at a time)."""
    chunk = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def write_document(fileobj, now, app_registry=None):
    """Stream the backup document as gzip-compressed JSON into ``fileobj``. Returns ``counts``.

    Writes the exact same document layout as ``_build_document`` (``format``, ``format_version``,
    ``created_at``, ``models`` then ``counts``), one model at a time and, within a model, one chunk of
    500 rows at a time via ``queryset.iterator``. The peak memory is a single chunk plus the gzip
    window, not several whole copies of the data. ``counts`` is written after ``models``; key order
    inside the JSON object is irrelevant to ``parse_backup``, which reads a dict.
    """
    labels = _backup_labels(app_registry)
    present = {model._meta.label: model for model in registry.get_models(app_registry)}
    counts = {label: 0 for label in labels}
    gz = gzip.GzipFile(fileobj=fileobj, mode="wb", mtime=0)
    try:
        def write(text):
            gz.write(text.encode("utf-8"))

        write("{")
        write('"format": ' + json.dumps(FORMAT_MARKER) + ", ")
        write('"format_version": ' + json.dumps(FORMAT_VERSION) + ", ")
        write('"created_at": ' + json.dumps(now.isoformat()) + ", ")
        write('"models": {')
        for label_index, label in enumerate(labels):
            if label_index:
                write(", ")
            write(json.dumps(label) + ": [")
            model = present.get(label)
            if model is not None:
                first = True
                for inner, count in _iter_model_record_chunks(model):
                    if inner:
                        if not first:
                            write(", ")
                        write(inner)
                        first = False
                    counts[label] += count
            write("]")
        write("}, ")
        write('"counts": ' + json.dumps(counts))
        write("}")
    finally:
        gz.close()
    return counts


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


def create_backup(kind, user=None, use_applied_state=False):
    """Make a full backup and store it. Returns the BackupFile.

    With ``use_applied_state`` the data is read through the historical models of
    the currently applied migrations (used before migrating), so a pending schema
    change cannot break the backup. On any error a failed BackupLog row is written
    and the error is re-raised.
    """
    started = timezone.now()
    try:
        # R-NFR-6: only one heavy suite operation at a time. restore_backup also takes this
        # "suite_backup" lock for the whole restore, so a backup and a restore cannot run at
        # once. The pre-restore safety backup runs inside restore_backup on the same session;
        # PostgreSQL advisory locks are re-entrant and counted, so this nested acquire succeeds
        # and each finally releases once, keeping the count balanced.
        with heavy_operation("suite_backup"):
            app_registry = applied_state_apps() if use_applied_state else None
            outermost = not connection.in_atomic_block
            with transaction.atomic():
                if outermost and connection.vendor == "postgresql":
                    # One consistent snapshot for every model (needs to be the first statement).
                    with connection.cursor() as cursor:
                        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                # Stream the gzip into a spooled temp file (in memory up to 2 MB, then on disk), so the
                # peak is one chunk of rows, not several whole copies. Read the finished bytes back once
                # for storage, so BackupFile.data, size_bytes and sha256 are identical to before.
                with tempfile.SpooledTemporaryFile(max_size=2 * 1024 * 1024) as spool:
                    counts = write_document(spool, started, app_registry)
                    spool.seek(0)
                    raw = spool.read()
                filename = f"judgment-diary-backup-{timezone.localtime(started):%Y%m%d-%H%M%S}-{kind}.json.gz"
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
    except Busy:
        # Another backup or a restore is running: that is not a failed backup, so no failure is logged and the Admin banner stays quiet.
        raise
    except Exception as exc:
        _log_failure(kind, started, exc, user)
        raise
    # Keep only the newest backups, whatever made this one. Never touches the backup just made and never raises.
    prune_old_backups(protect_ids=(backup.pk,))
    return backup


def prune_old_backups(keep_count=None, protect_ids=()):
    """Keep only the newest ``settings.BACKUP_KEEP_COUNT`` backups (default 30) and delete the rest.

    Every kind counts the same (nightly, before update, before restore, manual, and the Before import /
    After import / Before clearing profile backups too). Never deletes the newest backup or any id in
    ``protect_ids``. Never raises: a failure is written to the log instead. Returns the number removed.
    """
    if keep_count is None:
        keep_count = settings.BACKUP_KEEP_COUNT
    started = timezone.now()
    try:
        with transaction.atomic():
            entries = list(BackupFile.objects.values_list("id", "created_at"))
            expired = policy.select_over_count(entries, keep_count, protect_ids)
            if expired:
                BackupFile.objects.filter(id__in=expired).delete()
                BackupLog.objects.create(
                    started_at=started,
                    finished_at=timezone.now(),
                    kind="prune",
                    success=True,
                    message=f"Removed {len(expired)} old backup(s); the newest {policy.effective_keep_count(keep_count)} are kept.",
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
    if raw[:2] == GZIP_MAGIC:
        try:
            decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
            data = decompressor.decompress(raw, max_bytes + 1)
            complete = decompressor.eof
        except zlib.error:
            raise BackupError("This is not a backup file (the compressed file is damaged).")
        if len(data) > max_bytes:
            raise BackupError("This file is too large to be a valid backup.")
        if not complete:
            raise BackupError("This backup file is incomplete or damaged.")
    else:
        # Some browsers unzip .gz downloads automatically, so a plain JSON file is accepted too.
        data = raw
        if len(data) > max_bytes:
            raise BackupError("This file is too large to be a valid backup.")
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):  # RecursionError: JSON nested absurdly deep
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
    missing = [
        label
        for label in registry.BACKUP_MODELS
        if label not in models_in_file and label not in registry.OPTIONAL_MODELS
    ]
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


def profile_summary(document):
    """Per profile in the file: its name, program, how many users have it and how many diary records."""
    models_in_file = document["models"]
    users = {}
    for record in models_in_file.get("accounts.ProfileMembership", []):
        users[record["fields"].get("profile")] = users.get(record["fields"].get("profile"), 0) + 1
    records = {}
    for label in registry.PROFILE_MODELS:
        for record in models_in_file.get(label, []):
            key = record["fields"].get("profile")
            records[key] = records.get(key, 0) + 1
    rows = []
    for record in models_in_file.get("accounts.Profile", []):
        rows.append(
            {
                "name": record["fields"].get("name", "?"),
                "program": record["fields"].get("program", ""),
                "deleted": bool(record["fields"].get("deleted_at")),
                "users": users.get(record["pk"], 0),
                "records": records.get(record["pk"], 0),
            }
        )
    return sorted(rows, key=lambda row: (row["program"], row["name"].lower()))


def _file_has_active_admin(document):
    for record in document["models"].get("accounts.User", []):
        fields = record["fields"]
        if fields.get("is_superuser") and fields.get("is_active", True):
            return True
    return False


def _program_of_label(label):
    """A short program name for the app a backup label belongs to, for the restore warning box."""
    app_label = label.split(".", 1)[0]
    return {
        "diary": "Case Law Diary",
        "fees": "Fee Register",
        "investments": "Investments",
        "accounts": "Accounts",
    }.get(app_label, app_label)


def models_that_would_empty(document):
    """Record types a restore would wipe because the file lacks them but the database has rows (R-BK-4).

    One dict per optional model that is both absent from ``document["models"]`` AND currently has at
    least one row: ``{label, name, program, count_now}``. ``name`` is the model's plural verbose name,
    ``program`` names the program the record type belongs to. Used by the restore preview to warn that
    restoring an older file (for example one taken before the Fee Register existed) would discard data
    that is only in the database, and to require an extra confirmation before it may proceed.
    """
    models_in_file = document.get("models", {})
    warnings = []
    for label in registry.BACKUP_MODELS:
        if label not in registry.OPTIONAL_MODELS or label in models_in_file:
            continue
        try:
            model = apps.get_model(label)
        except LookupError:
            continue
        count_now = model._default_manager.count()
        if count_now:
            warnings.append(
                {
                    "label": label,
                    "name": model._meta.verbose_name_plural.title(),
                    "program": _program_of_label(label),
                    "count_now": count_now,
                }
            )
    return warnings


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
        # R-NFR-6: guard the destructive restore. The pre-restore safety backup above
        # has already finished and released its own "suite_backup" lock, so this takes
        # "suite_restore" cleanly; a backup or restore on another connection is refused.
        # "suite_backup" is taken as well, so a nightly or manual backup cannot start in the middle of the replacement.
        with heavy_operation("suite_backup"), heavy_operation("suite_restore"), transaction.atomic():
            batches = []
            for model in registry.get_models():
                records = document["models"].get(model._meta.label, [])
                # R4: deserialise in chunks of 500 rather than json.dumps-ing a whole model at once,
                # so the largest live text is one chunk. The deserialised objects are collected exactly
                # as before (delete order, saves, counts and sequence reset are unchanged).
                objects = []
                for start in range(0, len(records), 500):
                    chunk = records[start:start + 500]
                    objects.extend(serializers.deserialize("json", json.dumps(chunk), ignorenonexistent=True))
                batches.append((model, objects))
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
    # ``user`` may be a request.user SimpleLazyObject, so do not use type(user).
    survivor = None
    if user is not None and user.pk and get_user_model()._default_manager.filter(pk=user.pk).exists():
        survivor = user
    BackupLog.objects.create(
        started_at=started,
        finished_at=timezone.now(),
        kind="restore",
        success=True,
        message="Restored: "
        + ", ".join(f"{label} {n}" for label, n in counts.items()),
        created_by=survivor,
    )
    return counts


def upload_offsite(backup, storage=None, user=None):
    """Copy one stored backup to the off-site storage and record the attempt.

    Does nothing (and writes no log row) when off-site backup is not set up.
    Never raises: a failure is logged as a failed "Off-site copy" row, which the warning banner shows.
    Returns True (copied), False (failed) or None (not set up).
    """
    started = timezone.now()
    try:
        storage = storage if storage is not None else offsite_storage.get_storage()
    except offsite_storage.StorageError as exc:
        logger.warning("Off-site storage is misconfigured: %s", exc)
        _log_failure_offsite(started, f"Off-site copy FAILED: {exc}", user)
        return False
    if not storage.configured:
        return None
    try:
        raw = bytes(backup.data)
        storage.put(backup.filename, raw)
    except Exception as exc:
        # Only the safe message of our own error type is kept; anything else is reduced to its class name.
        detail = str(exc) if isinstance(exc, offsite_storage.StorageError) else exc.__class__.__name__
        logger.warning("Off-site copy of %s failed: %s", backup.filename, detail)
        _log_failure_offsite(started, f"Off-site copy FAILED to {storage.destination}: {detail}", user)
        return False
    BackupLog.objects.create(
        started_at=started,
        finished_at=timezone.now(),
        kind="offsite",
        success=True,
        message=f"Copied {backup.filename} to {storage.destination}.",
        size_bytes=len(raw),
        backup=backup,
        created_by=user if user is not None and user.pk else None,
    )
    return True


def _log_failure_offsite(started, message, user):
    try:
        with transaction.atomic():
            BackupLog.objects.create(
                started_at=started,
                finished_at=timezone.now(),
                kind="offsite",
                success=False,
                message=message,
                created_by=user if user is not None and user.pk else None,
            )
    except Exception:  # pragma: no cover
        logger.exception("Could not write the off-site failure log")


_BACKUP_NAME_RE = re.compile(r"judgment-diary-backup-\d{8}-\d{6}-[A-Za-z0-9_-]+\.json\.gz$")


def _is_our_backup_key(key):
    return bool(_BACKUP_NAME_RE.search(key.rsplit("/", 1)[-1]))


def prune_offsite(storage=None, now=None, retention_days=None):
    """Delete off-site copies older than the retention period (never the newest one). Never raises.

    Returns the number removed (0 when not set up).
    """
    try:
        storage = storage if storage is not None else offsite_storage.get_storage()
    except offsite_storage.StorageError as exc:
        logger.warning("Off-site storage is misconfigured: %s", exc)
        _log_failure_offsite(timezone.now(), f"Off-site clean-up FAILED: {exc}", None)
        return 0
    if not storage.configured:
        return 0
    now = now or timezone.now()
    if retention_days is None:
        retention_days = settings.OFFSITE_BACKUP_RETENTION_DAYS
    try:
        # Only this app's own backup files are ever deleted, even in a shared bucket or prefix.
        ours = [o for o in storage.list() if _is_our_backup_key(o.key)]
        objects = sorted(ours, key=lambda o: o.last_modified, reverse=True)
        cutoff = now - datetime.timedelta(days=retention_days)
        removed = 0
        for obj in objects[1:]:
            if obj.last_modified < cutoff:
                storage.delete(obj.key)
                removed += 1
        return removed
    except Exception as exc:
        detail = str(exc) if isinstance(exc, offsite_storage.StorageError) else exc.__class__.__name__
        logger.warning("Off-site clean-up failed: %s", detail)
        _log_failure_offsite(timezone.now(), f"Off-site clean-up FAILED: {detail}", None)
        return 0


def offsite_status():
    """Read-only facts for the Backups screen."""
    try:
        storage = offsite_storage.get_storage()
    except offsite_storage.StorageError as exc:
        last = BackupLog.objects.filter(kind="offsite").order_by("-started_at", "-id").first()
        return {"configured": True, "destination": f"(not usable: {exc})", "last": last, "last_ok": None}
    if not storage.configured:
        return {"configured": False}
    last = BackupLog.objects.filter(kind="offsite").order_by("-started_at", "-id").first()
    last_ok = BackupLog.objects.filter(kind="offsite", success=True).order_by("-started_at", "-id").first()
    return {"configured": True, "destination": storage.destination, "last": last, "last_ok": last_ok}
