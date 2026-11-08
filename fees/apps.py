"""The Fee Register app and its registration into the shared-core program registry.

``ready()`` registers ``KEY_FEES`` in ``accounts.programs`` (design 10.2 step C) so the shared-core
screens (Profiles, Users, the profile switch, the landing redirect, Home) pick up a second program
without any edit to those screens. Registration only records the program's key, its landing URL name
and a lazy ``profile_models`` callable; it does not call ``reverse`` or touch the database, so it is
safe to run at startup before the URL configuration or the database is available.

The profile-scoped model labels returned here are the Fee Register's own tables, parents first (the
backups registry gains its own copy in T1.9; this keeps the registry self-contained until then and
does not change the diary's purge or clear, which read ``backups.registry.profile_models_for``).
"""
from django.apps import AppConfig

#: The Fee Register tables that carry a ``profile`` column, parents first. ``StatsCache`` is derived
#: data (rebuilt on demand, never backed up) so it is not listed for program-level profile iteration.
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

#: The URL name of the Fee Register's first page: ``fees_landing`` redirects to the user's chosen
#: ``default_tab``. Registration stores the name only and never resolves it, so it does not touch
#: ``reverse`` at startup.
FEES_LANDING_URL_NAME = "fees_landing"


def _fees_profile_models():
    """The Fee Register profile-scoped model labels (parents first). Lazy: read only when needed."""
    return list(FEES_PROFILE_MODELS)


class FeesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "fees"
    verbose_name = "Fee Register"

    def ready(self):
        from accounts import programs
        from accounts.suite import KEY_FEES

        programs.register_program(
            programs.Program(
                key=KEY_FEES,
                landing_url_name=FEES_LANDING_URL_NAME,
                profile_models=_fees_profile_models,
            )
        )
