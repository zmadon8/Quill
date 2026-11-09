"""The Investments app and its registration into the shared-core program registry.

``ready()`` registers ``KEY_INVESTMENTS`` in ``accounts.programs`` so the Profiles, Users, profile switch, landing
redirect and Home screens pick the program up. Registration only records the key, the landing URL name and a lazy
``profile_models`` callable; it never calls ``reverse`` or touches the database.

The model labels returned by ``_investments_profile_models`` are the tables that carry a ``profile`` column, parents
first. They must stay identical to ``backups.registry.INVESTMENT_PROFILE_MODELS`` (a test checks it), the same two-list
arrangement the Fee Register uses.
"""
from django.apps import AppConfig

LANDING_URL_NAME = "investments_landing"


def _investments_profile_models():
    from backups import registry

    return list(registry.INVESTMENT_PROFILE_MODELS)


class InvestmentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "investments"
    verbose_name = "Investments"

    def ready(self):
        from accounts import programs
        from accounts.suite import KEY_INVESTMENTS

        programs.register_program(
            programs.Program(
                key=KEY_INVESTMENTS,
                landing_url_name=LANDING_URL_NAME,
                profile_models=_investments_profile_models,
            )
        )
