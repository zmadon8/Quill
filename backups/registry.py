"""Which models are included in backup files.

BACKUP_MODELS is ordered parents first (a model must come after every model it
points to). The diary models come after accounts.User (they point to it) and
keep parents before children; any new model must be appended here. Restore deletes in
reverse order and loads in this order.

Deliberately NOT in a backup file:
  * FailedLogin (short-lived login throttling),
  * PurgeLog (history of the deleted-profile purge job),
  * sessions (people simply sign in again),
  * BackupFile and BackupLog (a backup must never contain other backups).

Many-to-many fields are not backed up. Only plain columns and foreign keys
(``Model._meta.concrete_fields``) are. The current models have no many-to-many
data worth keeping (the User group and permission links are unused).
"""
from django.apps import apps

BACKUP_MODELS = [
    "accounts.User",
    "accounts.SuiteName",
    "accounts.Profile",
    "accounts.ProfileMembership",
    "diary.Subject",
    "diary.Topic",
    "diary.Subtopic",
    "diary.Section",
    "diary.Item",
    "diary.Case",
    "diary.Note",
    "diary.NoteLink",
    "diary.UserSettings",
    "diary.VersionHistory",
]

#: Models an older backup file may lack. Restoring such a file empties the table, so the built-in
#: defaults apply (a backup made before the Settings page existed has no display names). Profiles and
#: memberships are optional too: see ``services.upgrade_old_document`` for how an older file is
#: given a default "Main" profile.
OPTIONAL_MODELS = {"accounts.SuiteName", "accounts.Profile", "accounts.ProfileMembership"}

#: Diary models that carry a ``profile`` column. An older backup lacks it; such rows go into "Main".
PROFILE_MODELS = [
    "diary.Subject",
    "diary.Topic",
    "diary.Subtopic",
    "diary.Section",
    "diary.Item",
    "diary.Case",
    "diary.Note",
    "diary.NoteLink",
    "diary.VersionHistory",
]


def get_models(app_registry=None):
    """The registry models, in backup order (parents first).

    ``app_registry`` may be the ``apps`` of a historical migration state; a model
    that does not exist in that state yet is left out of the result.
    """
    app_registry = app_registry or apps
    found = []
    for label in BACKUP_MODELS:
        try:
            found.append(app_registry.get_model(label))
        except LookupError:
            if app_registry is apps:
                raise
    return found


def field_names(model):
    """Names of the fields written to a backup for ``model``."""
    return [field.name for field in model._meta.concrete_fields]
