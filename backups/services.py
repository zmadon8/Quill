"""Create, prune, validate, preview and restore backups.

Backups are stored inside the database (BackupFile.data), never on disk.
"""
import datetime
import gzip
import hashlib
import json
import logging
import zlib

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import serializers
from django.core.serializers.json import DjangoJSONEncoder
from django.core.management.color import no_style
from django.db import connection, transaction
from django.db.migrations.loader import MigrationLoader
from django.utils import timezone

from accounts.models import ROLE_EDITOR, ROLE_READER
from accounts.profiles import DEFAULT_PROFILE_NAME
from accounts.suite import KEY_DIARY as DEFAULT_PROGRAM

from diary.services import legacy

from . import policy, registry
from .models import KEEP_KINDS, BackupFile, BackupLog

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


def _build_document(now, app_registry=None):
    models_out = {}
    counts = {}
    # Registry models missing from the historical state have no table yet: record them as empty.
    # Optional models stay out of the file then, so an older state is read as an older backup.
    for label in registry.BACKUP_MODELS:
        if label in registry.OPTIONAL_MODELS and app_registry is not None:
            continue
        models_out[label] = []
        counts[label] = 0
    for model in registry.get_models(app_registry):
        label = model._meta.label
        models_out.setdefault(label, [])
        text = serializers.serialize(
            "json",
            model._default_manager.order_by("pk"),
            fields=registry.field_names(model),
            use_natural_foreign_keys=False,
            use_natural_primary_keys=False,
            cls=_ExactJSONEncoder,
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


def create_backup(kind, user=None, use_applied_state=False):
    """Make a full backup and store it. Returns the BackupFile.

    With ``use_applied_state`` the data is read through the historical models of
    the currently applied migrations (used before migrating), so a pending schema
    change cannot break the backup. On any error a failed BackupLog row is written
    and the error is re-raised.
    """
    started = timezone.now()
    try:
        app_registry = applied_state_apps() if use_applied_state else None
        outermost = not connection.in_atomic_block
        with transaction.atomic():
            if outermost and connection.vendor == "postgresql":
                # One consistent snapshot for every model (needs to be the first statement).
                with connection.cursor() as cursor:
                    cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            document, counts = _build_document(started, app_registry)
            raw = gzip.compress(json.dumps(document).encode("utf-8"))
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
    except Exception as exc:
        _log_failure(kind, started, exc, user)
        raise
    return backup


def prune_old_backups(now=None, retention_days=None):
    """Delete backups past the retention period (never the newest one, never an import or clear backup).

    Backups made around a Word import ("Before import" / "After import") or before clearing a profile stay until an Admin deletes them.

    Never raises: a failure is written to the log instead. Returns the number removed.
    """
    now = now or timezone.now()
    if retention_days is None:
        retention_days = settings.BACKUP_RETENTION_DAYS
    started = timezone.now()
    try:
        with transaction.atomic():
            entries = list(BackupFile.objects.values_list("id", "created_at"))
            kept = set(BackupFile.objects.filter(kind__in=KEEP_KINDS).values_list("id", flat=True))
            expired = [i for i in policy.select_expired(entries, now, retention_days) if i not in kept]
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
    old_roles = _normalise_user_records(models_in_file.get("accounts.User", []))
    upgrade_old_document(document, roles=old_roles)
    _fill_membership_roles(models_in_file.get("accounts.ProfileMembership", []), old_roles)
    upgrade_old_items(document)
    return document


def upgrade_old_items(document, now=None):
    """Map a backup made before the Multi-Item merge (10d) to the current Item shape.

    Items with kind "multi" or an own ``citation`` are mapped by ``diary.services.legacy``, the very code
    the data migration uses: citations move into a new first Case, Multi-Items become Items, and "migrate"
    history rows record each change. A file already in the new shape is left alone. The statistics are
    kept in ``document["legacy_mapping"]`` so the restore preview and log can say what was mapped.
    """
    try:
        stats = legacy.upgrade_document_items(document["models"], (now or timezone.now()).isoformat())
    except legacy.LegacyConflict as exc:
        raise BackupError(f"This backup holds data that cannot be mapped to the current format. {exc}")
    document["legacy_mapping"] = stats
    if stats["items_changed"]:
        counts = document.setdefault("counts", {})
        for label in ("diary.Item", "diary.Case", "diary.VersionHistory"):
            counts[label] = len(document["models"].get(label, []))
    return stats


def upgrade_old_document(document, now=None, roles=None):
    """Give a backup made before profiles existed a default "Main" profile.

    If the file has no profiles (no ``accounts.Profile`` section, or an empty one as written by
    a pre-migration backup taken before profiles existed), a "Main" Case Law Diary profile is added,
    every user in the file is given access to it, and every diary record without a ``profile``
    is put into it. A file that already has profiles is left untouched. Returns True if changed.
    ``roles`` maps user pk to the membership role (from an old ``User.role``); missing means Reader.
    """
    models_in_file = document["models"]
    if models_in_file.get("accounts.Profile"):
        return False
    stamp = (now or timezone.now()).isoformat()
    profile_pk = 1
    models_in_file["accounts.Profile"] = [
        {
            "model": "accounts.profile",
            "pk": profile_pk,
            "fields": {
                "program": DEFAULT_PROGRAM,
                "name": DEFAULT_PROFILE_NAME,
                "deleted_at": None,
                "created_at": stamp,
                "updated_at": stamp,
            },
        }
    ]
    models_in_file["accounts.ProfileMembership"] = [
        {
            "model": "accounts.profilemembership",
            "pk": number,
            "fields": {
                "user": user["pk"],
                "profile": profile_pk,
                "program": DEFAULT_PROGRAM,
                "role": (roles or {}).get(user["pk"], ROLE_READER),
                "created_at": stamp,
            },
        }
        for number, user in enumerate(models_in_file.get("accounts.User", []), start=1)
    ]
    for label in registry.PROFILE_MODELS:
        for record in models_in_file.get(label, []):
            record["fields"].setdefault("profile", profile_pk)
    document.setdefault("counts", {})
    document["counts"]["accounts.Profile"] = 1
    document["counts"]["accounts.ProfileMembership"] = len(models_in_file["accounts.ProfileMembership"])
    return True


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


def _normalise_user_records(records):
    """Make user records match the current User model, so older backups still restore.

    Older files have a ``role`` on each user (Admin, Editor or Reader); it now lives on the profile
    membership. The column is removed from the record, a user who was an Admin by role is a
    superuser, and the old role is returned as ``{user pk: "editor" or "reader"}`` (Editor and Admin
    map to Editor, anything else to Reader) for memberships that lack a role. ``is_staff`` follows
    ``is_superuser``. This is done here because restoring writes rows without calling ``User.save()``.
    """
    roles = {}
    for record in records:
        fields = record["fields"]
        old_role = fields.pop("role", None)
        is_superuser = bool(fields.get("is_superuser")) or old_role == "admin"
        fields["is_superuser"] = is_superuser
        fields["is_staff"] = is_superuser
        roles[record["pk"]] = ROLE_EDITOR if is_superuser or old_role == "editor" else ROLE_READER
    return roles


def _fill_membership_roles(records, roles):
    """Give memberships without a valid role the role mapped from the user's old role (else Reader)."""
    for record in records:
        fields = record["fields"]
        if fields.get("role") not in (ROLE_EDITOR, ROLE_READER):
            fields["role"] = roles.get(fields.get("user"), ROLE_READER)


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
        + ", ".join(f"{label} {n}" for label, n in counts.items())
        + (" " + legacy.describe(document.get("legacy_mapping") or legacy.new_stats())).rstrip(),
        created_by=survivor,
    )
    return counts
