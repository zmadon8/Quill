"""Which models are included in backup files.

BACKUP_MODELS is ordered parents first (a model must come after every model it
points to). The diary models come after accounts.User (they point to it) and
keep parents before children; the Fee Register models follow the diary models and
keep the same parents-first rule. Any new model must be appended here. Restore
deletes in reverse order and loads in this order.

Deliberately NOT in a backup file:
  * FailedLogin and ResetRequest (short-lived login and password-reset throttling),
  * OfflineLink and OfflineDownload (round 21, D100): a saved Offline copy is derived data and must never be copied
    into backup files, emailed or sent off-site, and the secret token is not spread into backup files either.
    Effect: a restore deletes profiles by queryset delete, which cascades to their links and copies, so after any
    restore all links and saved copies are gone and the Admin makes a new link. (A restore can therefore never
    bring back a link that was revoked.)
  * PurgeLog (history of the deleted-profile purge job),
  * sessions (people simply sign in again),
  * BackupFile and BackupLog (a backup must never contain other backups).

Many-to-many fields are not backed up. Only plain columns and foreign keys
(``Model._meta.concrete_fields``) are. The current models have no many-to-many
data worth keeping (the User group and permission links are unused).
"""
from django.apps import apps

#: Investments models. Phase 0 registers no tables yet (the app has no models); the lists exist so the program
#: registration, purge and clear already read them, and each later phase appends its models parents first. Fetched
#: prices (``Price``), fetched exchange rates, caches, tokens and logs are deliberately NEVER listed (plan 17.2).
INVESTMENTS_BACKUP_MODELS = []

#: Investments models that carry a ``profile`` column, parents first. ``investments.apps`` reads this list.
INVESTMENT_PROFILE_MODELS = []

BACKUP_MODELS = [
    "accounts.User",
    "accounts.SuiteName",
    "accounts.Profile",
    "accounts.ProfileMembership",
    "diary.TrashBatch",
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
    # Fee Register models (T1.9, design 7.4), parents first so restore inserts a parent before any
    # child and the reversed delete removes children first. StatsCache (derived data) and FeesUserPrefs (per-user UI
    # state such as column widths; cascade-deleted with the profile or user) are never
    # backed up, so it is deliberately absent here and from OPTIONAL_MODELS and FEES_PROFILE_MODELS.
    "fees.FeesSettings",
    "fees.WordTemplate",
    "fees.BankAccount",
    "fees.Firm",
    "fees.Group",
    "fees.Matter",
    "fees.Memo",
    "fees.NumberSequence",
    "fees.Payment",
    "fees.Allocation",
    "fees.PeriodAdjustment",
    "fees.SavedView",
    *INVESTMENTS_BACKUP_MODELS,
]

#: The Fee Register model labels added to ``BACKUP_MODELS`` (T1.9). Kept as a named list so the
#: optional-model set and the restore guard can refer to exactly the fee models in one place.
FEES_BACKUP_MODELS = [
    "fees.FeesSettings",
    "fees.WordTemplate",
    "fees.BankAccount",
    "fees.Firm",
    "fees.Group",
    "fees.Matter",
    "fees.Memo",
    "fees.NumberSequence",
    "fees.Payment",
    "fees.Allocation",
    "fees.PeriodAdjustment",
    "fees.SavedView",
]

#: Models an older backup file may lack. Restoring such a file empties the table, so the built-in
#: defaults apply (a backup made before the Settings page existed has no display names). Profiles and
#: memberships are optional too, and so are Trash batches (added in Milestone 3; an older file simply has none): see ``services.upgrade_old_document`` for how an older file is
#: given a default "Main" profile.
#: Every fee model is optional too: a backup taken before the Fee Register existed has none of these
#: sections, and restoring such a file simply empties the fee tables (the restore guard R-BK-4 warns
#: when that would discard current fee data).
OPTIONAL_MODELS = {
    "accounts.SuiteName",
    "accounts.Profile",
    "accounts.ProfileMembership",
    "diary.TrashBatch",
    *FEES_BACKUP_MODELS,
    *INVESTMENTS_BACKUP_MODELS,
}

#: Diary models that carry a ``profile`` column. An older backup lacks it; such rows go into "Main".
PROFILE_MODELS = [
    "diary.TrashBatch",
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


#: Fee Register models that carry a ``profile`` column, parents first (same order as in
#: ``BACKUP_MODELS``). This is a SEPARATE list from the diary ``PROFILE_MODELS`` so
#: ``services.upgrade_old_document`` (which assigns unassigned diary rows to the diary "Main" profile)
#: never iterates over fee models. ``StatsCache`` is derived data and is not listed. All 12 fee models
#: are profile-scoped, so this is the same set as ``FEES_BACKUP_MODELS``.
FEES_PROFILE_MODELS = [
    "fees.FeesSettings",
    "fees.WordTemplate",
    "fees.BankAccount",
    "fees.Firm",
    "fees.Group",
    "fees.Matter",
    "fees.Memo",
    "fees.NumberSequence",
    "fees.Payment",
    "fees.Allocation",
    "fees.PeriodAdjustment",
    "fees.SavedView",
]


#: Profile-scoped model labels per program key, parents first (the same order as in ``BACKUP_MODELS``).
#: ``profile_models_for`` turns the labels into model classes in the order the profile purge and clear
#: delete them (children first). The diary and the Fee Register each have their own list; a profile's
#: ``program`` picks the list, so purge and clear of a fees profile delete only fee rows.
PROGRAM_PROFILE_MODELS = {
    "diary": PROFILE_MODELS,
    "fees": FEES_PROFILE_MODELS,
    "investments": INVESTMENT_PROFILE_MODELS,
}


def profile_models_for(program, app_registry=None):
    """Model classes carrying a ``profile`` column for ``program``, in delete order (children first).

    Returns an empty list for an unknown program. The order is the reverse of the parents-first label
    list, so a caller can delete rows straight down the list; this matches the order the profile purge
    and clear used before the registry existed.
    """
    app_registry = app_registry or apps
    labels = PROGRAM_PROFILE_MODELS.get(program, [])
    models = []
    for label in reversed(labels):
        try:
            models.append(app_registry.get_model(label))
        except LookupError:
            if app_registry is apps:
                raise
    return models


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
